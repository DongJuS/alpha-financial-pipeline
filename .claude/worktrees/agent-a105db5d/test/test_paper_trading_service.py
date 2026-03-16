import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.services.paper_trading import (
    build_account_overview,
    build_account_snapshot_series,
    build_broker_order_activity,
)


class PaperTradingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_account_overview_uses_latest_snapshot(self) -> None:
        snapshot_at = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
        with (
            patch(
                "src.services.paper_trading.get_trading_account",
                new=AsyncMock(
                    return_value={
                        "broker_name": "한국투자증권 KIS",
                        "account_label": "KIS 모의투자 계좌",
                        "base_currency": "KRW",
                        "seed_capital": 10_000_000,
                    }
                ),
            ),
            patch(
                "src.services.paper_trading.latest_account_snapshot",
                new=AsyncMock(
                    return_value={
                        "cash_balance": 9_700_000,
                        "buying_power": 9_700_000,
                        "position_market_value": 350_000,
                        "total_equity": 10_050_000,
                        "realized_pnl": 20_000,
                        "unrealized_pnl": 30_000,
                        "position_count": 2,
                        "snapshot_at": snapshot_at,
                    }
                ),
            ),
        ):
            overview = await build_account_overview("paper")

        self.assertEqual(overview["total_pnl"], 50_000)
        self.assertEqual(overview["total_pnl_pct"], 0.5)
        self.assertEqual(overview["last_snapshot_at"], snapshot_at)

    async def test_build_account_snapshot_series_falls_back_to_computed_state(self) -> None:
        with (
            patch("src.services.paper_trading.list_account_snapshots", new=AsyncMock(return_value=[])),
            patch(
                "src.services.paper_trading.recompute_account_state",
                new=AsyncMock(
                    return_value={
                        "cash_balance": 9_900_000,
                        "buying_power": 9_900_000,
                        "position_market_value": 100_000,
                        "total_equity": 10_000_000,
                        "realized_pnl": 0,
                        "unrealized_pnl": 0,
                        "position_count": 1,
                    }
                ),
            ),
        ):
            points = await build_account_snapshot_series("paper", limit=30)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["snapshot_source"], "computed")
        self.assertIsNone(points[0]["snapshot_at"])

    async def test_build_broker_order_activity_returns_query_rows(self) -> None:
        with patch(
            "src.services.paper_trading.list_broker_orders",
            new=AsyncMock(return_value=[{"client_order_id": "paper-1"}]),
        ):
            rows = await build_broker_order_activity("paper", limit=10)

        self.assertEqual(rows, [{"client_order_id": "paper-1"}])


if __name__ == "__main__":
    unittest.main()
