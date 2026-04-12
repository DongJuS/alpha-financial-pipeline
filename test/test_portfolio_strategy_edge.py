"""
test/test_portfolio_strategy_edge.py — Portfolio Manager & Strategy Runner edge-case tests

QA Round 2: PortfolioManagerAgent, StrategyARunner, StrategyBRunner 에지케이스 8건.
"""

from datetime import date
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models import PredictionSignal


# ---------------------------------------------------------------------------
# Portfolio Manager Tests (4)
# ---------------------------------------------------------------------------


class PortfolioManagerProcessSignalEdgeTest(unittest.IsolatedAsyncioTestCase):
    """process_signal 에지케이스."""

    def _make_agent(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent

        return PortfolioManagerAgent()

    async def test_process_signal_hold_returns_none(self) -> None:
        """HOLD 시그널 → None 반환, 주문 없음."""
        agent = self._make_agent()
        signal = PredictionSignal(
            agent_id="predictor_1",
            llm_model="manual",
            strategy="A",
            ticker="005930",
            signal="HOLD",
            confidence=0.5,
            trading_date=date.today(),
        )

        result = await agent.process_signal(signal)

        self.assertIsNone(result)

    async def test_process_signal_zero_price_skips(self) -> None:
        """price=0 → None 반환 + 경고 로그."""
        agent = self._make_agent()
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
                new=AsyncMock(return_value=("삼성전자", 0)),
            ),
            patch(
                "src.agents.portfolio_manager.logger",
            ) as mock_logger,
        ):
            result = await agent.process_signal(signal, risk_config={})

        self.assertIsNone(result)
        mock_logger.warning.assert_called_once()
        log_msg = mock_logger.warning.call_args[0][0]
        self.assertIn("가격 정보 없음으로 주문 스킵", log_msg)


class PortfolioManagerRuleBasedExitEdgeTest(unittest.IsolatedAsyncioTestCase):
    """_check_rule_based_exits 에지케이스."""

    def _make_agent(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent

        return PortfolioManagerAgent()

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_rule_based_exit_avg_price_zero_skips(self, mock_positions) -> None:
        """avg_price=0 포지션 → SELL 시그널 없음 (continue)."""
        mock_positions.return_value = [
            {
                "ticker": "005930",
                "quantity": 10,
                "avg_price": 0,
                "current_price": 70000,
            },
        ]
        agent = self._make_agent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}

        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")

        self.assertEqual(len(signals), 0)

    @patch("src.db.queries.get_positions_for_scope", new_callable=AsyncMock)
    async def test_rule_based_exit_take_profit_trigger(self, mock_positions) -> None:
        """P&L >= take_profit_pct → SELL 시그널 생성, agent_id='rule_based_exit'."""
        mock_positions.return_value = [
            {
                "ticker": "005930",
                "quantity": 10,
                "avg_price": 100000,
                "current_price": 106000,
            },
        ]
        agent = self._make_agent()
        cfg = {"take_profit_pct": 5.0, "stop_loss_pct": -3.0}

        signals = await agent._check_rule_based_exits(["005930"], cfg, "paper")

        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig.signal, "SELL")
        self.assertEqual(sig.agent_id, "rule_based_exit")
        self.assertEqual(sig.ticker, "005930")
        self.assertIn("익절", sig.reasoning_summary)


# ---------------------------------------------------------------------------
# Strategy A Runner Tests (2)
# ---------------------------------------------------------------------------


class StrategyARunnerEdgeTest(unittest.IsolatedAsyncioTestCase):
    """StrategyARunner 에지케이스."""

    def _make_runner(self) -> "StrategyARunner":
        from src.agents.strategy_a_runner import StrategyARunner

        runner = StrategyARunner.__new__(StrategyARunner)
        runner.name = "A"
        runner._tournament = MagicMock()
        return runner

    async def test_strategy_a_empty_tickers_returns_empty(self) -> None:
        """빈 티커 리스트 → 빈 결과, 토너먼트 호출 없음."""
        runner = self._make_runner()

        result = await runner.run([])

        self.assertEqual(result, [])
        runner._tournament.run_daily_tournament.assert_not_called()

    async def test_strategy_a_exception_returns_empty(self) -> None:
        """토너먼트 예외 → 빈 리스트 반환, 에러 로그 기록."""
        runner = self._make_runner()
        runner._tournament.run_daily_tournament = AsyncMock(
            side_effect=RuntimeError("LLM error"),
        )

        with patch("src.agents.strategy_a_runner.logger") as mock_logger:
            result = await runner.run(["005930"])

        self.assertEqual(result, [])
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][1]
        self.assertIsInstance(error_msg, RuntimeError)


# ---------------------------------------------------------------------------
# Strategy B Runner Tests (2)
# ---------------------------------------------------------------------------


class StrategyBRunnerEdgeTest(unittest.IsolatedAsyncioTestCase):
    """StrategyBRunner 에지케이스."""

    def _make_runner(self) -> "StrategyBRunner":
        from src.agents.strategy_b_runner import StrategyBRunner

        runner = StrategyBRunner.__new__(StrategyBRunner)
        runner.name = "B"
        runner._consensus = MagicMock()
        return runner

    async def test_strategy_b_empty_tickers_returns_empty(self) -> None:
        """빈 티커 리스트 → 빈 결과."""
        runner = self._make_runner()

        result = await runner.run([])

        self.assertEqual(result, [])

    async def test_strategy_b_exception_logs_to_db(self) -> None:
        """합의 예외 → 빈 리스트 + log_event(event_type='b_empty') 호출."""
        runner = self._make_runner()
        runner._consensus.run = AsyncMock(
            side_effect=RuntimeError("timeout"),
        )

        with patch("src.utils.db_logger.log_event", new_callable=AsyncMock) as mock_log_event:
            result = await runner.run(["005930"])

        self.assertEqual(result, [])
        mock_log_event.assert_awaited_once()
        call_args = mock_log_event.call_args
        self.assertEqual(call_args[0][0], "b_empty")
        event_data = call_args[0][1]
        self.assertEqual(event_data["reason"], "exception")
        self.assertEqual(event_data["exc_type"], "RuntimeError")
        self.assertIn("timeout", event_data["exc_msg"])


if __name__ == "__main__":
    unittest.main()
