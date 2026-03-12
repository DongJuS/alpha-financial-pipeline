from datetime import date
import json
import unittest
from unittest.mock import AsyncMock, patch

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.db.models import PredictionSignal


class PortfolioManagerRiskGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_name_and_price_prefers_realtime_cache(self) -> None:
        agent = PortfolioManagerAgent()
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(
            return_value=json.dumps(
                {"name": "삼성전자", "current_price": 123456},
                ensure_ascii=False,
            )
        )

        with (
            patch("src.agents.portfolio_manager.get_redis", new=AsyncMock(return_value=fake_redis)),
            patch("src.agents.portfolio_manager.fetch_recent_ohlcv", new=AsyncMock()) as ohlcv_mock,
        ):
            name, price = await agent._resolve_name_and_price("005930", None)

        self.assertEqual(name, "삼성전자")
        self.assertEqual(price, 123456)
        ohlcv_mock.assert_not_called()

    async def test_process_signal_skips_buy_when_max_position_exceeded(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.7,
            trading_date=date.today(),
        )

        with (
            patch.object(
                agent,
                "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 1_000)),
            ),
            patch(
                "src.agents.portfolio_manager.get_position",
                new=AsyncMock(return_value={"quantity": 5, "current_price": 1_000, "avg_price": 1_000}),
            ),
            patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=6_000)),
            patch("src.agents.portfolio_manager.save_position", new=AsyncMock()) as save_mock,
            patch("src.agents.portfolio_manager.insert_trade", new=AsyncMock()) as trade_mock,
        ):
            result = await agent.process_signal(
                signal,
                risk_config={"max_position_pct": 50, "is_paper_trading": True},
            )

        self.assertIsNone(result)
        save_mock.assert_not_called()
        trade_mock.assert_not_called()

    async def test_process_predictions_stops_on_daily_loss_limit(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.7,
            trading_date=date.today(),
        )

        with (
            patch(
                "src.agents.portfolio_manager.get_portfolio_config",
                new=AsyncMock(return_value={"daily_loss_limit_pct": 3, "max_position_pct": 20}),
            ),
            patch(
                "src.agents.portfolio_manager.today_trade_totals",
                new=AsyncMock(return_value={"buy_total": 10_000, "sell_total": 9_200}),
            ),
            patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()) as publish_mock,
            patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()) as heartbeat_mock,
            patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()) as insert_heartbeat_mock,
            patch.object(agent, "process_signal", new=AsyncMock()) as process_signal_mock,
        ):
            orders = await agent.process_predictions([signal])

        self.assertEqual(orders, [])
        process_signal_mock.assert_not_called()
        publish_mock.assert_awaited()
        heartbeat_mock.assert_awaited_once()
        insert_heartbeat_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
