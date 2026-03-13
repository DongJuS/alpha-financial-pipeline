import unittest
from unittest.mock import AsyncMock, patch

from src.brokers.paper import PaperBroker
from src.db.models import PaperOrderRequest


class PaperBrokerTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_order_fills_buy_when_buying_power_is_available(self) -> None:
        broker = PaperBroker()
        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            quantity=1,
            price=70_000,
            signal_source="A",
            agent_id="portfolio_manager_agent",
            account_scope="paper",
        )

        with (
            patch.object(broker, "_ensure_account", new=AsyncMock()),
            patch.object(
                broker,
                "sync_account_state",
                new=AsyncMock(
                    side_effect=[
                        {"buying_power": 1_000_000, "cash_balance": 1_000_000, "total_equity": 1_000_000},
                        {"buying_power": 930_000, "cash_balance": 930_000, "total_equity": 1_000_000},
                    ]
                ),
            ),
            patch("src.brokers.paper.insert_broker_order", new=AsyncMock()) as insert_order_mock,
            patch("src.brokers.paper.get_position", new=AsyncMock(return_value=None)),
            patch("src.brokers.paper.save_position", new=AsyncMock()) as save_position_mock,
            patch("src.brokers.paper.insert_trade", new=AsyncMock()) as insert_trade_mock,
            patch("src.brokers.paper.update_broker_order_status", new=AsyncMock()) as update_order_mock,
        ):
            result = await broker.execute_order(order)

        self.assertEqual(result.status, "FILLED")
        self.assertEqual(result.cash_balance, 930_000)
        insert_order_mock.assert_awaited_once()
        save_position_mock.assert_awaited_once()
        insert_trade_mock.assert_awaited_once_with(order)
        update_order_mock.assert_awaited()

    async def test_execute_order_rejects_buy_when_cash_is_insufficient(self) -> None:
        broker = PaperBroker()
        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            quantity=1,
            price=70_000,
            signal_source="A",
            agent_id="portfolio_manager_agent",
            account_scope="paper",
        )

        with (
            patch.object(broker, "_ensure_account", new=AsyncMock()),
            patch.object(
                broker,
                "sync_account_state",
                new=AsyncMock(return_value={"buying_power": 10_000, "cash_balance": 10_000, "total_equity": 10_000}),
            ),
            patch("src.brokers.paper.insert_broker_order", new=AsyncMock()),
            patch("src.brokers.paper.get_position", new=AsyncMock(return_value=None)),
            patch("src.brokers.paper.save_position", new=AsyncMock()) as save_position_mock,
            patch("src.brokers.paper.insert_trade", new=AsyncMock()) as insert_trade_mock,
            patch("src.brokers.paper.update_broker_order_status", new=AsyncMock()) as update_order_mock,
        ):
            result = await broker.execute_order(order)

        self.assertEqual(result.status, "REJECTED")
        self.assertIsNotNone(result.rejection_reason)
        save_position_mock.assert_not_awaited()
        insert_trade_mock.assert_not_awaited()
        update_order_mock.assert_awaited()

    async def test_sync_account_state_recomputes_cash_and_equity(self) -> None:
        broker = PaperBroker()

        with (
            patch.object(broker, "_ensure_account", new=AsyncMock()),
            patch(
                "src.brokers.paper.get_trading_account",
                new=AsyncMock(
                    return_value={
                        "broker_name": "한국투자증권 KIS",
                        "account_label": "KIS 모의투자 계좌",
                        "base_currency": "KRW",
                        "seed_capital": 10_000_000,
                        "is_active": True,
                    }
                ),
            ),
            patch("src.brokers.paper.trade_cash_totals", new=AsyncMock(return_value={"buy_total": 250_000, "sell_total": 50_000})),
            patch(
                "src.brokers.paper.portfolio_position_stats",
                new=AsyncMock(return_value={"market_value": 9_800_000, "unrealized_pnl": 120_000, "position_count": 3}),
            ),
            patch("src.brokers.paper.fetch_all_trade_rows", new=AsyncMock(return_value=[])),
            patch("src.brokers.paper.compute_trade_performance", return_value={"realized_pnl": 40_000}),
            patch("src.brokers.paper.upsert_trading_account", new=AsyncMock()) as upsert_account_mock,
            patch("src.brokers.paper.record_account_snapshot", new=AsyncMock()) as snapshot_mock,
        ):
            state = await broker.sync_account_state("paper")

        self.assertEqual(state["cash_balance"], 9_800_000)
        self.assertEqual(state["total_equity"], 19_600_000)
        self.assertEqual(state["realized_pnl"], 40_000)
        upsert_account_mock.assert_awaited_once()
        snapshot_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
