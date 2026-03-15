"""
scripts/run_rl_trading.py — RL trading lane 단독 실행기

사용 예:
  python scripts/run_rl_trading.py --tickers 005930,000660
  python scripts/run_rl_trading.py --tickers 005930 --execute-orders
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.collector import CollectorAgent
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.agents.rl_trading import RLTradingAgent
from src.utils.market_hours import market_session_status


async def _seed_yahoo_history(tickers: list[str], range_: str) -> dict:
    collector = CollectorAgent()
    try:
        points = await collector.collect_yahoo_daily_bars(tickers=tickers, range_=range_, interval="1d")
        seeded_tickers = sorted({point.ticker for point in points})
        return {
            "enabled": True,
            "status": "completed",
            "range": range_,
            "rows": len(points),
            "tickers": seeded_tickers,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "status": "error",
            "range": range_,
            "error": str(exc),
        }


async def _prime_kis_ticks(tickers: list[str], seconds: int) -> dict:
    if seconds <= 0:
        return {"enabled": False, "status": "skipped", "reason": "collection disabled"}

    market_status = await market_session_status()
    if market_status != "open":
        return {"enabled": True, "status": "skipped", "market_status": market_status}

    collector = CollectorAgent()
    try:
        received = await collector.collect_realtime_ticks(
            tickers,
            duration_seconds=seconds,
            fallback_on_error=False,
        )
        return {
            "enabled": True,
            "status": "completed",
            "market_status": market_status,
            "received_ticks": received,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "status": "error",
            "market_status": market_status,
            "error": str(exc),
        }


async def _main_async(args: argparse.Namespace) -> None:
    tickers = [ticker.strip() for ticker in args.tickers.split(",") if ticker.strip()]
    history_seed = await _seed_yahoo_history(tickers, args.seed_yahoo_range)
    collection = await _prime_kis_ticks(tickers, args.collect_ticks_seconds)

    rl_agent = RLTradingAgent(
        dataset_interval=args.dataset_interval,
        training_window_days=args.window_days,
        training_window_seconds=args.window_seconds,
        dataset_limit=args.dataset_limit,
    )
    predictions, summaries = await rl_agent.run_cycle(tickers, account_scope=args.account_scope)

    result = {
        "mode": "rl_trading",
        "tickers": tickers,
        "dataset_interval": args.dataset_interval,
        "history_seed": history_seed,
        "collection": collection,
        "predictions": [prediction.model_dump() for prediction in predictions],
        "summaries": summaries,
        "orders": [],
    }

    if args.execute_orders:
        portfolio = PortfolioManagerAgent()
        result["orders"] = await portfolio.process_predictions(
            predictions,
            signal_source_override="RL",
        )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="RL trading lane 단독 실행")
    parser.add_argument("--tickers", required=True, help="쉼표 구분 티커 목록")
    parser.add_argument("--dataset-interval", default="daily", choices=["daily", "tick"], help="RL dataset interval")
    parser.add_argument("--window-days", type=int, default=3650, help="학습용 OHLCV 조회 일수")
    parser.add_argument("--window-seconds", type=int, default=None, help="tick 학습용 조회 초 단위 범위")
    parser.add_argument("--dataset-limit", type=int, default=None, help="학습용 최대 샘플 수 제한")
    parser.add_argument("--seed-yahoo-range", default="10y", help="RL history seed용 Yahoo range")
    parser.add_argument(
        "--collect-ticks-seconds",
        type=int,
        default=30,
        help="장중 KIS 실시간 틱을 선수집할 시간(초)",
    )
    parser.add_argument("--account-scope", default="paper", choices=["paper", "real"], help="현재 포지션 조회 scope")
    parser.add_argument("--execute-orders", action="store_true", help="RL 신호를 paper/real 주문 파이프에 전달")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
