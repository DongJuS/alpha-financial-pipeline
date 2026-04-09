"""
test/test_empty_signal_events.py — empty_signal event logging 검증

PR #1: observability: structured empty_signal events for Strategy B/RL
- rl_runner.py 의 6가지 skip reason 이 log_event("rl_skip", {...})로 기록되는지
- strategy_b_runner.py 의 exception path 가 log_event("b_empty", {...})로 기록되는지
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRLRunnerSkipEvents(unittest.IsolatedAsyncioTestCase):
    """RLRunner 의 빈 시그널 이벤트가 event_logs 에 기록되는지 검증."""

    def _make_runner(self):
        from src.agents.rl_runner import RLRunner
        store = MagicMock()
        trainer = MagicMock()
        return RLRunner(policy_store=store, trainer=trainer)

    @patch("src.utils.db_logger.log_event", new_callable=AsyncMock)
    async def test_registry_load_failed(self, mock_log: AsyncMock):
        runner = self._make_runner()
        runner._store.load_registry.side_effect = RuntimeError("broken")

        result = await runner.run(["005930"])

        self.assertEqual(result, [])
        mock_log.assert_called_once_with("rl_skip", {
            "reason": "registry_load_failed",
            "ticker_count": 1,
            "exc_type": "RuntimeError",
            "exc_msg": "broken",
        })

    @patch("src.utils.db_logger.log_event", new_callable=AsyncMock)
    async def test_no_active_policy(self, mock_log: AsyncMock):
        runner = self._make_runner()
        registry = MagicMock()
        registry.list_active_policies.return_value = {}
        runner._store.load_registry.return_value = registry

        result = await runner.run(["005930", "035720"])

        self.assertEqual(result, [])
        mock_log.assert_called_once_with("rl_skip", {
            "reason": "no_active_policy",
            "ticker_count": 2,
        })

    @patch("src.utils.db_logger.log_event", new_callable=AsyncMock)
    async def test_no_ticker_policy(self, mock_log: AsyncMock):
        runner = self._make_runner()
        registry = MagicMock()
        registry.list_active_policies.return_value = {"999999.KS": "policy_A"}
        runner._store.load_registry.return_value = registry

        result = await runner.run(["005930"])

        self.assertEqual(result, [])
        mock_log.assert_called_once_with("rl_skip", {
            "reason": "no_ticker_policy",
            "ticker_count": 1,
            "ticker": "005930",
        })


class TestStrategyBRunnerEmptyEvent(unittest.IsolatedAsyncioTestCase):
    """StrategyBRunner 의 exception path 가 b_empty 이벤트를 기록하는지 검증."""

    @patch("src.utils.db_logger.log_event", new_callable=AsyncMock)
    async def test_debate_exception_logs_b_empty(self, mock_log: AsyncMock):
        from src.agents.strategy_b_runner import StrategyBRunner

        runner = StrategyBRunner.__new__(StrategyBRunner)
        runner._consensus = AsyncMock()
        runner._consensus.run.side_effect = RuntimeError("LLM limit reached")

        result = await runner.run(["005930", "035720", "000660"])

        self.assertEqual(result, [])
        mock_log.assert_called_once()
        call_args = mock_log.call_args
        self.assertEqual(call_args[0][0], "b_empty")
        data = call_args[0][1]
        self.assertEqual(data["reason"], "exception")
        self.assertEqual(data["exc_type"], "RuntimeError")
        self.assertIn("LLM limit", data["exc_msg"])
        self.assertEqual(data["ticker_count"], 3)
