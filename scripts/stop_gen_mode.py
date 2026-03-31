"""
scripts/stop_gen_mode.py — Gen 모드 중지 + 생성 데이터 정리

Gen 모드에서 KIS 실거래/모의투자로 전환할 때 사용합니다.
Gen이 생성한 가상 시세, 거래 이력, 포지션, 캐시를 정리합니다.

사용법:
  # K3s에서 실행
  kubectl exec -n alpha-trading deployment/worker -- python scripts/stop_gen_mode.py

  # 로컬에서 실행
  python scripts/stop_gen_mode.py

  # dry-run (실제 삭제 없이 확인만)
  python scripts/stop_gen_mode.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.utils.db_client import get_pool
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


async def cleanup_gen_data(dry_run: bool = False) -> dict:
    """Gen 모드에서 생성된 데이터를 정리합니다."""
    pool = await get_pool()
    result = {}

    async with pool.acquire() as conn:
        # 1. Gen이 생성한 가상 거래 이력 (signal_source가 Gen 관련)
        gen_trades = await conn.fetchval(
            "SELECT count(*) FROM trade_history WHERE signal_source IN ('BLEND', 'EXIT') AND is_paper = true"
        )
        result["gen_trades"] = gen_trades
        if not dry_run and gen_trades > 0:
            await conn.execute(
                "DELETE FROM trade_history WHERE signal_source IN ('BLEND', 'EXIT') AND is_paper = true"
            )
            logger.info("거래 이력 %d건 삭제", gen_trades)

        # 2. 포지션 전체 클리어 (paper)
        positions = await conn.fetchval(
            "SELECT count(*) FROM portfolio_positions WHERE account_scope = 'paper'"
        )
        result["positions"] = positions
        if not dry_run and positions > 0:
            await conn.execute("DELETE FROM portfolio_positions WHERE account_scope = 'paper'")
            logger.info("포지션 %d건 삭제", positions)

        # 3. Gen이 생성한 predictions (agent_id가 gen 관련이 아닌, 전략 predictions은 유지)
        # Gen 모드에서 생성된 predictions은 trading_date 기준으로 판단하기 어려우므로
        # 오늘 날짜 predictions만 삭제 (안전)
        today_preds = await conn.fetchval(
            "SELECT count(*) FROM predictions WHERE trading_date = CURRENT_DATE"
        )
        result["today_predictions"] = today_preds
        if not dry_run and today_preds > 0:
            await conn.execute("DELETE FROM predictions WHERE trading_date = CURRENT_DATE")
            logger.info("오늘 predictions %d건 삭제", today_preds)

        # 4. event_logs 중 Gen 관련
        gen_events = await conn.fetchval(
            "SELECT count(*) FROM event_logs WHERE ts::date = CURRENT_DATE"
        )
        result["today_events"] = gen_events

    # 5. Redis 캐시 정리
    try:
        from src.utils.redis_client import get_redis
        redis = await get_redis()
        # 틱 캐시
        tick_keys = [k async for k in redis.scan_iter("redis:latest_ticks:*")]
        series_keys = [k async for k in redis.scan_iter("redis:realtime_series:*")]
        llm_keys = [k async for k in redis.scan_iter("redis:usage:llm:*")]

        result["redis_tick_keys"] = len(tick_keys)
        result["redis_series_keys"] = len(series_keys)
        result["redis_llm_keys"] = len(llm_keys)

        if not dry_run:
            all_keys = tick_keys + series_keys + llm_keys
            if all_keys:
                await redis.delete(*all_keys)
                logger.info("Redis 캐시 %d건 삭제", len(all_keys))
    except Exception as e:
        logger.warning("Redis 정리 실패 (비필수): %s", e)
        result["redis_error"] = str(e)

    return result


async def main(args: argparse.Namespace) -> None:
    logger.info("=== Gen 모드 데이터 정리 %s ===", "(DRY-RUN)" if args.dry_run else "")

    result = await cleanup_gen_data(dry_run=args.dry_run)

    logger.info(
        "\n정리 결과:\n"
        "  거래 이력: %d건\n"
        "  포지션: %d건\n"
        "  오늘 predictions: %d건\n"
        "  Redis tick 캐시: %d건\n"
        "  Redis series 캐시: %d건\n"
        "  Redis LLM 카운터: %d건\n"
        "  %s",
        result.get("gen_trades", 0),
        result.get("positions", 0),
        result.get("today_predictions", 0),
        result.get("redis_tick_keys", 0),
        result.get("redis_series_keys", 0),
        result.get("redis_llm_keys", 0),
        "DRY-RUN — 실제 삭제 없음" if args.dry_run else "삭제 완료",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gen 모드 데이터 정리")
    parser.add_argument("--dry-run", action="store_true", help="실제 삭제 없이 확인만")
    asyncio.run(main(parser.parse_args()))
