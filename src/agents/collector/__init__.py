"""src/agents/collector — CollectorAgent 패키지.

기존 `from src.agents.collector import CollectorAgent` 호환성을 유지하는 facade.
"""
from __future__ import annotations

import argparse
import asyncio

from src.agents.collector._base import _CollectorBase

# Mixins — created by parallel agents
try:
    from src.agents.collector._daily import _DailyMixin
except ImportError:
    _DailyMixin = object  # type: ignore[assignment,misc]

try:
    from src.agents.collector._realtime import _RealtimeMixin
except ImportError:
    _RealtimeMixin = object  # type: ignore[assignment,misc]

try:
    from src.agents.collector._historical import _HistoricalMixin
except ImportError:
    _HistoricalMixin = object  # type: ignore[assignment,misc]


class CollectorAgent(_CollectorBase, _DailyMixin, _RealtimeMixin, _HistoricalMixin):  # type: ignore[misc]
    pass


__all__ = ["CollectorAgent"]


# ── CLI ────────────────────────────────────────────────────────────────────


async def _main_async(args: argparse.Namespace) -> None:
    agent = CollectorAgent()
    tickers = args.tickers.split(",") if args.tickers else None

    if args.realtime:
        await agent.collect_realtime_ticks(
            tickers=tickers or [],
            duration_seconds=args.duration_seconds,
            tr_id=args.tr_id,
            reconnect_max=args.reconnect_max,
            fallback_on_error=not args.no_fallback,
        )
    else:
        await agent.collect_daily_bars(tickers=tickers, lookback_days=args.lookback_days)


def main() -> None:
    parser = argparse.ArgumentParser(description="CollectorAgent")
    parser.add_argument("--tickers", default="", help="쉼표 구분 티커 목록 (예: 005930,000660)")
    parser.add_argument("--lookback-days", type=int, default=120, help="일봉 수집 lookback 기간")
    parser.add_argument("--realtime", action="store_true", help="KIS WebSocket 실시간 틱 수집 모드")
    parser.add_argument("--duration-seconds", type=int, default=None, help="실시간 수집 실행 시간(초)")
    parser.add_argument("--tr-id", default="H0STCNT0", help="KIS WebSocket 구독 TR ID")
    parser.add_argument("--reconnect-max", type=int, default=3, help="WebSocket 최대 재연결 횟수")
    parser.add_argument("--no-fallback", action="store_true", help="WebSocket 실패 시 폴백 수집 비활성화")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
