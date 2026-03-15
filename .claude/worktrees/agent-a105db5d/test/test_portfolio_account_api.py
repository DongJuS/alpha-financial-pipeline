import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.api.routers.portfolio import (
    get_account_overview,
    get_account_snapshots,
    get_broker_orders,
)


class PortfolioAccountApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_account_overview_returns_typed_response(self) -> None:
        snapshot_at = datetime(2026, 3, 13, 13, 0, tzinfo=timezone.utc)
        payload = {
            "account_scope": "paper",
            "broker_name": "한국투자증권 KIS",
            "account_label": "KIS 모의투자 계좌",
            "base_currency": "KRW",
            "seed_capital": 10_000_000,
            "cash_balance": 9_700_000,
            "buying_power": 9_650_000,
            "position_market_value": 450_000,
            "total_equity": 10_150_000,
            "realized_pnl": 40_000,
            "unrealized_pnl": 110_000,
            "total_pnl": 150_000,
            "total_pnl_pct": 1.5,
            "position_count": 2,
            "last_snapshot_at": snapshot_at,
        }

        with (
            patch("src.api.routers.portfolio._resolve_mode_account_scope", new=AsyncMock(return_value="paper")),
            patch("src.api.routers.portfolio.build_account_overview", new=AsyncMock(return_value=payload)),
        ):
            response = await get_account_overview({"sub": "tester"}, mode="current")

        self.assertEqual(response.account_scope, "paper")
        self.assertEqual(response.total_pnl, 150_000)
        self.assertEqual(response.last_snapshot_at, snapshot_at)

    async def test_get_broker_orders_returns_serialized_items(self) -> None:
        requested_at = datetime(2026, 3, 13, 9, 30, tzinfo=timezone.utc)
        filled_at = datetime(2026, 3, 13, 9, 31, tzinfo=timezone.utc)
        rows = [
            {
                "client_order_id": "paper-1",
                "account_scope": "paper",
                "broker_name": "internal-paper",
                "ticker": "005930",
                "name": "삼성전자",
                "side": "BUY",
                "order_type": "MARKET",
                "requested_quantity": 2,
                "requested_price": 71_000,
                "filled_quantity": 2,
                "avg_fill_price": 71_000,
                "status": "FILLED",
                "signal_source": "A",
                "agent_id": "portfolio_manager_agent",
                "broker_order_id": "paper-1",
                "rejection_reason": None,
                "requested_at": requested_at,
                "filled_at": filled_at,
            }
        ]

        with (
            patch("src.api.routers.portfolio._resolve_mode_account_scope", new=AsyncMock(return_value="paper")),
            patch("src.api.routers.portfolio.build_broker_order_activity", new=AsyncMock(return_value=rows)),
        ):
            response = await get_broker_orders({"sub": "tester"}, mode="current", limit=20)

        self.assertEqual(response.account_scope, "paper")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0].status, "FILLED")
        self.assertEqual(response.data[0].filled_at, filled_at)

    async def test_get_account_snapshots_returns_series(self) -> None:
        snapshot_at = datetime(2026, 3, 13, 15, 0, tzinfo=timezone.utc)
        rows = [
            {
                "account_scope": "paper",
                "cash_balance": 9_800_000,
                "buying_power": 9_780_000,
                "position_market_value": 330_000,
                "total_equity": 10_130_000,
                "realized_pnl": 20_000,
                "unrealized_pnl": 110_000,
                "position_count": 2,
                "snapshot_source": "broker",
                "snapshot_at": snapshot_at,
            }
        ]

        with (
            patch("src.api.routers.portfolio._resolve_mode_account_scope", new=AsyncMock(return_value="paper")),
            patch("src.api.routers.portfolio.build_account_snapshot_series", new=AsyncMock(return_value=rows)),
        ):
            response = await get_account_snapshots({"sub": "tester"}, mode="current", limit=30)

        self.assertEqual(response.account_scope, "paper")
        self.assertEqual(len(response.points), 1)
        self.assertEqual(response.points[0].snapshot_source, "broker")
        self.assertEqual(response.points[0].snapshot_at, snapshot_at)


if __name__ == "__main__":
    unittest.main()
