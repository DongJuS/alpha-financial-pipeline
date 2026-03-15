"""
scripts/seed_historical_data.py — 과거 데이터 초기 적재 배치 스크립트

사용법:
    python scripts/seed_historical_data.py --tickers 005930,035420 --start 2020-01-01 --end 2026-03-15
    python scripts/seed_historical_data.py --ticker-file tickers.txt --start 2020-01-01
    python scripts/seed_historical_data.py --tickers 005930 --start 2024-01-01 --interval 5 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.agents.collector import CollectorAgent
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


async def run_seed(args: argparse.Namespace) -> None:
    agent = CollectorAgent(agent_id="seed_historical")

    # 티커 목록 결정
    tickers: list[str] = []
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    elif args.ticker_file:
        ticker_path = Path(args.ticker_file)
        if not ticker_path.exists():
            logger.error("티커 파일을 찾을 수 없습니다: %s", args.ticker_file)
            sys.exit(1)
        tickers = [
            line.strip()
            for line in ticker_path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        # 기본: KRX 상위 20종목
        selected = await agent.resolve_tickers(None, limit=20)
        tickers = [t[0] for t in selected]

    if not tickers:
        logger.error("수집할 티커가 없습니다.")
        sys.exit(1)

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    interval_label = "일봉" if args.interval == "D" else f"{args.interval}분봉"

    logger.info(
        "=== 과거 데이터 수집 시작 ===\n"
        "  티커: %d개\n"
        "  기간: %s ~ %s\n"
        "  간격: %s\n"
        "  Dry-run: %s",
        len(tickers),
        args.start,
        end_date,
        interval_label,
        args.dry_run,
    )

    if args.dry_run:
        for i, ticker in enumerate(tickers, 1):
            logger.info("[DRY-RUN] [%d/%d] %s", i, len(tickers), ticker)
        logger.info("=== Dry-run 완료. 실제 수집은 --dry-run 플래그를 제거하세요. ===")
        return

    # 티커 메타 정보 조회
    selected = await agent.resolve_tickers(tickers, limit=len(tickers) + 10)
    meta = {t: (n, m) for t, n, m in selected}

    total_points = 0
    succeeded = 0
    skipped = 0
    failed = 0

    for i, ticker in enumerate(tickers, 1):
        name, market = meta.get(ticker, (ticker, "KOSPI"))

        # 이미 데이터가 있으면 스킵 (resume 기능)
        if not args.force:
            db_interval = "daily" if args.interval == "D" else "tick"
            existing = await agent.check_data_exists(ticker, db_interval)
            if existing > 0:
                logger.info("[%d/%d] %s (%s) — 이미 %d건 존재, 스킵", i, len(tickers), ticker, name, existing)
                skipped += 1
                continue

        try:
            points = await agent.fetch_historical_ohlcv(
                ticker=ticker,
                start_date=args.start,
                end_date=end_date,
                interval=args.interval,
                name=name,
                market=market,
            )
            count = len(points)
            total_points += count
            succeeded += 1
            logger.info(
                "[%d/%d] %s (%s) — %d건 수집 완료",
                i, len(tickers), ticker, name, count,
            )
        except Exception as e:
            failed += 1
            logger.error("[%d/%d] %s (%s) — 수집 실패: %s", i, len(tickers), ticker, name, e)

        # rate limiting between tickers
        if i < len(tickers):
            await asyncio.sleep(0.5)

    logger.info(
        "\n=== 과거 데이터 수집 완료 ===\n"
        "  전체: %d개 티커\n"
        "  성공: %d개\n"
        "  스킵: %d개 (기존 데이터)\n"
        "  실패: %d개\n"
        "  총 데이터: %d건",
        len(tickers), succeeded, skipped, failed, total_points,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="과거 OHLCV 데이터 초기 적재",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="쉼표 구분 티커 목록 (예: 005930,035420,000660)",
    )
    parser.add_argument(
        "--ticker-file",
        default="",
        help="티커 목록 파일 경로 (한 줄에 티커 하나)",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="수집 시작일 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        default="",
        help="수집 종료일 (YYYY-MM-DD, 기본: 오늘)",
    )
    parser.add_argument(
        "--interval",
        default="D",
        choices=["D", "1", "5", "15", "30", "60"],
        help="수집 간격 (D=일봉, 1/5/15/30/60=분봉)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 수집 없이 대상 티커만 표시",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 데이터가 있어도 강제 재수집",
    )
    args = parser.parse_args()
    asyncio.run(run_seed(args))


if __name__ == "__main__":
    main()
