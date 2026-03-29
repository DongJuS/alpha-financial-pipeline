from datetime import date
import json
import unittest
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.brokers.paper import PaperBrokerExecution
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
            patch.object(agent.paper_broker, "execute_order", new=AsyncMock()) as execute_order_mock,
        ):
            result = await agent.process_signal(
                signal,
                risk_config={
                    "max_position_pct": 50,
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                    "paper_seed_capital": 10_000,
                },
            )

        self.assertIsNone(result)
        execute_order_mock.assert_not_called()

    async def test_process_signal_allows_first_buy_with_seed_capital(self) -> None:
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
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(return_value=None)),
            patch("src.agents.portfolio_manager.get_trading_account", new=AsyncMock(return_value=None)),
            patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=0)),
            patch.object(
                agent.paper_broker,
                "execute_order",
                new=AsyncMock(
                    return_value=PaperBrokerExecution(
                        client_order_id="paper-test",
                        account_scope="paper",
                        status="FILLED",
                        ticker="005930",
                        side="BUY",
                        quantity=1,
                        price=1_000,
                        cash_balance=9_999_000,
                        total_equity=10_000_000,
                    )
                ),
            ) as execute_order_mock,
        ):
            result = await agent.process_signal(
                signal,
                risk_config={
                    "max_position_pct": 20,
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                    "paper_seed_capital": 10_000_000,
                },
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "BUY")
        execute_order_mock.assert_awaited_once()

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
                new=AsyncMock(
                    return_value={
                        "daily_loss_limit_pct": 3,
                        "max_position_pct": 20,
                        "enable_paper_trading": True,
                        "enable_real_trading": False,
                        "primary_account_scope": "paper",
                    }
                ),
            ),
            patch("src.agents.portfolio_manager.market_session_status", new=AsyncMock(return_value="open")),
            patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()) as publish_mock,
            patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()) as heartbeat_mock,
            patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()) as insert_heartbeat_mock,
            patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(True, -3.2))),
            patch.object(agent, "process_signal", new=AsyncMock()) as process_signal_mock,
        ):
            orders = await agent.process_predictions([signal])

        self.assertEqual(orders, [])
        process_signal_mock.assert_not_called()
        publish_mock.assert_awaited()
        heartbeat_mock.assert_awaited_once()
        insert_heartbeat_mock.assert_awaited_once()

    @pytest.mark.integration
    async def test_process_predictions_executes_both_paper_and_real_when_enabled(self) -> None:
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

        paper_result = {"ticker": "005930", "side": "BUY", "quantity": 1, "price": 70000, "account_scope": "paper"}
        real_result = {"ticker": "005930", "side": "BUY", "quantity": 1, "price": 70000, "account_scope": "real"}

        with (
            patch(
                "src.agents.portfolio_manager.get_portfolio_config",
                new=AsyncMock(
                    return_value={
                        "daily_loss_limit_pct": 3,
                        "max_position_pct": 20,
                        "enable_paper_trading": True,
                        "enable_real_trading": True,
                        "primary_account_scope": "paper",
                    }
                ),
            ),
            patch("src.agents.portfolio_manager.market_session_status", new=AsyncMock(return_value="open")),
            patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(False, 0.0))),
            patch.object(agent, "process_signal", new=AsyncMock(side_effect=[paper_result, real_result])) as process_signal_mock,
            patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()),
            patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()),
            patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()),
        ):
            orders = await agent.process_predictions([signal])

        self.assertEqual(orders, [paper_result, real_result])
        self.assertEqual(process_signal_mock.await_count, 2)
        self.assertEqual(process_signal_mock.await_args_list[0].kwargs["account_scope_override"], "paper")
        self.assertEqual(process_signal_mock.await_args_list[1].kwargs["account_scope_override"], "real")

    async def test_process_predictions_skips_orders_when_market_closed_for_all_scopes(self) -> None:
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.7,
            trading_date=date.today(),
        )
        cases = [
            (
                "paper-only",
                {
                    "daily_loss_limit_pct": 3,
                    "max_position_pct": 20,
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                },
                ["paper"],
            ),
            (
                "real-only",
                {
                    "daily_loss_limit_pct": 3,
                    "max_position_pct": 20,
                    "enable_paper_trading": False,
                    "enable_real_trading": True,
                    "primary_account_scope": "real",
                },
                ["real"],
            ),
            (
                "dual",
                {
                    "daily_loss_limit_pct": 3,
                    "max_position_pct": 20,
                    "enable_paper_trading": True,
                    "enable_real_trading": True,
                    "primary_account_scope": "paper",
                },
                ["paper", "real"],
            ),
        ]

        for label, config, expected_scopes in cases:
            agent = PortfolioManagerAgent()
            with self.subTest(label=label):
                with (
                    patch("src.agents.portfolio_manager.get_portfolio_config", new=AsyncMock(return_value=config)),
                    patch("src.agents.portfolio_manager.market_session_status", new=AsyncMock(return_value="after_hours")),
                    patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()) as publish_mock,
                    patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()) as heartbeat_mock,
                    patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()) as insert_heartbeat_mock,
                    patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock()) as daily_loss_mock,
                    patch.object(agent, "process_signal", new=AsyncMock()) as process_signal_mock,
                ):
                    orders = await agent.process_predictions([signal])

                self.assertEqual(orders, [])
                process_signal_mock.assert_not_called()
                daily_loss_mock.assert_not_called()
                heartbeat_mock.assert_awaited_once()
                insert_heartbeat_mock.assert_awaited_once()

                payload = json.loads(publish_mock.await_args.args[1])
                self.assertEqual(payload["count"], 0)
                self.assertEqual(payload["enabled_scopes"], expected_scopes)
                self.assertEqual(payload["market_status"], "after_hours")
                self.assertEqual(payload["skip_reason"], "market_closed")

                heartbeat = insert_heartbeat_mock.await_args.args[0]
                self.assertEqual(heartbeat.status, "healthy")
                self.assertIn("장 마감/휴장으로 주문 생략", heartbeat.last_action)
                self.assertEqual(heartbeat.metrics["market_status"], "after_hours")
                self.assertEqual(heartbeat.metrics["skip_reason"], "market_closed")


if __name__ == "__main__":
    unittest.main()
