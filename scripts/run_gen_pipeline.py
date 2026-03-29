#!/usr/bin/env python3
"""
scripts/run_gen_pipeline.py — Gen 파이프라인 원커맨드 실행

Gen 서버(데이터 생성)와 GenCollector(수집→저장)를 하나의 프로세스에서
동시에 기동하여, 수집→저장 파이프라인을 E2E로 검증합니다.

Usage:
    python scripts/run_gen_pipeline.py
    python scripts/run_gen_pipeline.py --mode full --lookback-days 60
    python scripts/run_gen_pipeline.py --mode tick --tick-cycles 30
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


async def run_gen_server(port: int = 9999) -> None:
    """Gen 서버를 백그라운드에서 실행합니다."""
    import uvicorn
    from src.gen.server import app

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_gen_collector(
    gen_url: str,
    mode: str,
    lookback_days: int,
    tick_interval: float,
    tick_cycles: int | None,
) -> None:
    """GenCollector를 실행합니다."""
    from src.agents.gen_collector import GenCollectorAgent

    await asyncio.sleep(2.0)

    agent = GenCollectorAgent(gen_api_url=gen_url)
    try:
        if mode == "daily":
            result = await agent.collect_daily_bars(lookback_days=lookback_days)
            print(f"\n✅ 일봉 수집 완료: {len(result)}건")

        elif mode == "tick":
            count = await agent.collect_realtime_ticks(
                interval_sec=tick_interval,
                max_cycles=tick_cycles,
            )
            print(f"\n✅ 틱 수집 완료: {count}건")

        elif mode == "full":
            result = await agent.run_full_cycle(lookback_days=lookback_days)
            print("\n✅ 통합 수집 완료:")
            print(f"   일봉: {result['daily_bars_count']}건")
            print(f"   틱:   {result['tick_count']}건")
            print(f"   지수: {result['indices_count']}건")
            print(f"   매크로: {result['macro_count']}건")

        elif mode == "continuous":
            daily = await agent.collect_daily_bars(lookback_days=lookback_days)
            print(f"\n✅ 일봉 수집 완료: {len(daily)}건")
            print("🔄 틱 수집 시작 (Ctrl+C로 종료)...")
            await agent.collect_realtime_ticks(
                interval_sec=tick_interval,
                max_cycles=None,
            )
    finally:
        await agent.close()


async def main_async(args: argparse.Namespace) -> None:
    gen_url = f"http://localhost:{args.port}"

    print("=" * 60)
    print("  Gen Pipeline — 수집→저장 파이프라인 테스트")
    print("=" * 60)
    print(f"  Gen Server:    http://0.0.0.0:{args.port}")
    print(f"  Mode:          {args.mode}")
    print(f"  Lookback:      {args.lookback_days}일")
    if args.mode in ("tick", "continuous"):
        print(f"  Tick Interval: {args.tick_interval}초")
        print(f"  Tick Cycles:   {args.tick_cycles or '무한'}")
    print("=" * 60)

    server_task = asyncio.create_task(run_gen_server(port=args.port))
    collector_task = asyncio.create_task(
        run_gen_collector(
            gen_url=gen_url,
            mode=args.mode,
            lookback_days=args.lookback_days,
            tick_interval=args.tick_interval,
            tick_cycles=args.tick_cycles,
        )
    )

    done, pending = await asyncio.wait(
        [server_task, collector_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Gen Pipeline Runner")
    parser.add_argument(
        "--mode",
        choices=["daily", "tick", "full", "continuous"],
        default="full",
        help="수집 모드",
    )
    parser.add_argument("--port", type=int, default=9999, help="Gen 서버 포트")
    parser.add_argument("--lookback-days", type=int, default=120, help="일봉 lookback 기간")
    parser.add_argument("--tick-interval", type=float, default=1.0, help="틱 수집 주기 (초)")
    parser.add_argument("--tick-cycles", type=int, default=None, help="틱 수집 최대 횟수")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n⏹️  Gen Pipeline 종료")


if __name__ == "__main__":
    main()
