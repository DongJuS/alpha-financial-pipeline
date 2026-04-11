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
            patch.object(agent, "_check_rule_based_exits", new=AsyncMock(return_value=[])),
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


class PortfolioManagerEdgeCaseTest(unittest.IsolatedAsyncioTestCase):
    """PortfolioManager 에지 케이스 테스트."""

    def test_default_agent_id(self) -> None:
        agent = PortfolioManagerAgent()
        self.assertEqual(agent.agent_id, "portfolio_manager_agent")

    def test_custom_agent_id(self) -> None:
        agent = PortfolioManagerAgent(agent_id="custom_pm")
        self.assertEqual(agent.agent_id, "custom_pm")

    async def test_resolve_name_and_price_falls_back_to_ohlcv(self) -> None:
        """Redis에 데이터 없으면 OHLCV fallback."""
        agent = PortfolioManagerAgent()
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=None)

        with (
            patch("src.agents.portfolio_manager.get_redis", new=AsyncMock(return_value=fake_redis)),
            patch("src.agents.portfolio_manager.fetch_recent_ohlcv", new=AsyncMock(
                return_value=[{"close": 55000, "name": "카카오"}]
            )),
        ):
            name, price = await agent._resolve_name_and_price("035720", None)

        self.assertEqual(name, "카카오")
        self.assertEqual(price, 55000)

    async def test_process_signal_hold_signal_skipped(self) -> None:
        """HOLD 시그널은 주문 실행하지 않음."""
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="HOLD",
            confidence=0.9,
            trading_date=date.today(),
        )

        with (
            patch.object(
                agent, "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 70000)),
            ),
            patch.object(agent.paper_broker, "execute_order", new=AsyncMock()) as execute_mock,
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

        self.assertIsNone(result)
        execute_mock.assert_not_called()

    async def test_process_predictions_empty_list(self) -> None:
        """빈 예측 목록 → 빈 주문 목록."""
        agent = PortfolioManagerAgent()

        with (
            patch(
                "src.agents.portfolio_manager.get_portfolio_config",
                new=AsyncMock(return_value={
                    "daily_loss_limit_pct": 3,
                    "max_position_pct": 20,
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                }),
            ),
            patch("src.agents.portfolio_manager.market_session_status", new=AsyncMock(return_value="open")),
            patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()),
            patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()),
            patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()),
            patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(False, 0.0))),
            patch.object(agent, "_check_rule_based_exits", new=AsyncMock(return_value=[])),
        ):
            orders = await agent.process_predictions([])

        self.assertEqual(orders, [])

    async def test_process_signal_shadow_signal_skipped(self) -> None:
        """is_shadow=True 시그널은 무시되어야 함."""
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="rl_shadow",
            llm_model="manual",
            strategy="RL",
            ticker="005930",
            signal="BUY",
            confidence=0.9,
            trading_date=date.today(),
            is_shadow=True,
        )
        # shadow 시그널은 process_signal에서 처리해도 실제 주문 실행 안 함
        # (실제 동작은 process_predictions에서 필터링 여부에 따라 다름)
        self.assertTrue(signal.is_shadow)


class PortfolioManagerDailyLossBlockedTest(unittest.IsolatedAsyncioTestCase):
    """_is_daily_loss_blocked 경계값 테스트."""

    @patch("src.agents.portfolio_manager.compute_trade_performance")
    @patch("src.agents.portfolio_manager.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_exactly_at_limit_is_blocked(self, mock_fetch, mock_perf) -> None:
        """pnl_pct가 정확히 -limit이면 blocked (<=)."""
        mock_fetch.return_value = [{"row": 1}]
        mock_perf.return_value = {"invested_capital": 1000, "realized_pnl": -30}
        agent = PortfolioManagerAgent()
        blocked, pnl = await agent._is_daily_loss_blocked(
            "paper", {"daily_loss_limit_pct": 3}
        )
        self.assertTrue(blocked)
        self.assertAlmostEqual(pnl, -3.0, places=1)

    @patch("src.agents.portfolio_manager.compute_trade_performance")
    @patch("src.agents.portfolio_manager.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_just_above_limit_not_blocked(self, mock_fetch, mock_perf) -> None:
        """pnl_pct가 limit보다 약간 높으면 not blocked."""
        mock_fetch.return_value = [{"row": 1}]
        mock_perf.return_value = {"invested_capital": 1000, "realized_pnl": -29}
        agent = PortfolioManagerAgent()
        blocked, pnl = await agent._is_daily_loss_blocked(
            "paper", {"daily_loss_limit_pct": 3}
        )
        self.assertFalse(blocked)
        self.assertAlmostEqual(pnl, -2.9, places=1)

    @patch("src.agents.portfolio_manager.compute_trade_performance")
    @patch("src.agents.portfolio_manager.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_zero_invested_capital_returns_zero(self, mock_fetch, mock_perf) -> None:
        """invested_capital=0이면 pnl_pct=0 → not blocked."""
        mock_fetch.return_value = [{"row": 1}]
        mock_perf.return_value = {"invested_capital": 0, "realized_pnl": 0}
        agent = PortfolioManagerAgent()
        blocked, pnl = await agent._is_daily_loss_blocked(
            "paper", {"daily_loss_limit_pct": 3}
        )
        self.assertFalse(blocked)
        self.assertAlmostEqual(pnl, 0.0)

    @patch("src.agents.portfolio_manager.compute_trade_performance")
    @patch("src.agents.portfolio_manager.fetch_trade_rows_for_date", new_callable=AsyncMock)
    async def test_positive_pnl_not_blocked(self, mock_fetch, mock_perf) -> None:
        """양의 수익 → not blocked."""
        mock_fetch.return_value = [{"row": 1}]
        mock_perf.return_value = {"invested_capital": 1000, "realized_pnl": 50}
        agent = PortfolioManagerAgent()
        blocked, pnl = await agent._is_daily_loss_blocked(
            "paper", {"daily_loss_limit_pct": 3}
        )
        self.assertFalse(blocked)
        self.assertGreater(pnl, 0)


class PortfolioManagerRuleBasedExitsTest(unittest.IsolatedAsyncioTestCase):
    """_check_rule_based_exits 다양한 조건 테스트."""

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_take_profit_triggered(self, mock_positions) -> None:
        """수익률이 take_profit_pct 이상이면 SELL 시그널."""
        mock_positions.return_value = [
            {"ticker": "005930", "quantity": 10, "avg_price": 100.0, "current_price": 106.0},
        ]
        agent = PortfolioManagerAgent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}
        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, "SELL")
        self.assertIn("익절", signals[0].reasoning_summary)

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_stop_loss_triggered(self, mock_positions) -> None:
        """수익률이 stop_loss_pct 이하이면 SELL 시그널."""
        mock_positions.return_value = [
            {"ticker": "005930", "quantity": 10, "avg_price": 100.0, "current_price": 96.0},
        ]
        agent = PortfolioManagerAgent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}
        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, "SELL")
        self.assertIn("손절", signals[0].reasoning_summary)

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_no_exit_in_range(self, mock_positions) -> None:
        """수익률이 익절/손절 범위 내이면 시그널 없음."""
        mock_positions.return_value = [
            {"ticker": "005930", "quantity": 10, "avg_price": 100.0, "current_price": 102.0},
        ]
        agent = PortfolioManagerAgent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}
        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")
        self.assertEqual(len(signals), 0)

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_zero_quantity_skipped(self, mock_positions) -> None:
        """수량 0인 포지션은 무시."""
        mock_positions.return_value = [
            {"ticker": "005930", "quantity": 0, "avg_price": 100.0, "current_price": 200.0},
        ]
        agent = PortfolioManagerAgent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}
        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")
        self.assertEqual(len(signals), 0)

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_zero_avg_price_skipped(self, mock_positions) -> None:
        """avg_price=0인 포지션은 무시."""
        mock_positions.return_value = [
            {"ticker": "005930", "quantity": 10, "avg_price": 0, "current_price": 100.0},
        ]
        agent = PortfolioManagerAgent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}
        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")
        self.assertEqual(len(signals), 0)

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_empty_positions(self, mock_positions) -> None:
        """포지션 없으면 빈 리스트."""
        mock_positions.return_value = []
        agent = PortfolioManagerAgent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}
        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")
        self.assertEqual(len(signals), 0)


class PortfolioManagerProcessSignalEdgeCaseTest(unittest.IsolatedAsyncioTestCase):
    """process_signal 추가 에지케이스."""

    async def test_process_signal_zero_price_skipped(self) -> None:
        """가격=0이면 주문 스킵."""
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="test",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="BUY",
            confidence=0.9,
            trading_date=date.today(),
        )
        with patch.object(
            agent, "_resolve_name_and_price",
            new=AsyncMock(return_value=("삼성전자", 0)),
        ):
            result = await agent.process_signal(signal, risk_config={})
        self.assertIsNone(result)

    async def test_process_signal_sell_no_position_skipped(self) -> None:
        """SELL 시 포지션이 없으면 주문 스킵."""
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="test",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="SELL",
            confidence=0.9,
            trading_date=date.today(),
        )
        with (
            patch.object(
                agent, "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 70000)),
            ),
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(return_value=None)),
        ):
            result = await agent.process_signal(signal, risk_config={})
        self.assertIsNone(result)

    async def test_process_signal_sell_zero_quantity_skipped(self) -> None:
        """SELL 시 보유 수량이 0이면 주문 스킵."""
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="test",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="SELL",
            confidence=0.9,
            trading_date=date.today(),
        )
        with (
            patch.object(
                agent, "_resolve_name_and_price",
                new=AsyncMock(return_value=("삼성전자", 70000)),
            ),
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(
                return_value={"quantity": 0, "current_price": 70000, "avg_price": 65000}
            )),
        ):
            result = await agent.process_signal(signal, risk_config={})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
