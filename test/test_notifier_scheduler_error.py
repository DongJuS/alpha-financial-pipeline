"""스케줄러 잡 실패 Telegram 알림 테스트."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from src.agents.notifier import NotifierAgent


class TestSendSchedulerErrorAlert(unittest.IsolatedAsyncioTestCase):
    """NotifierAgent.send_scheduler_error_alert() 단위 테스트."""

    def _make_agent(self) -> NotifierAgent:
        return NotifierAgent()

    async def test_calls_send_with_expected_payload(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            result = await agent.send_scheduler_error_alert(
                job_id="collector_daily",
                job_name="CollectorAgent daily (08:30 KST)",
                exception="ConnectionError: KIS API timeout",
            )
        self.assertTrue(result)
        mock_send.assert_awaited_once()
        _, kwargs = mock_send.await_args
        self.assertEqual(kwargs["event_type"], "scheduler_job_error")
        msg = kwargs["message"]
        self.assertIn("collector_daily", msg)
        self.assertIn("CollectorAgent daily", msg)
        self.assertIn("ConnectionError", msg)
        self.assertIn("KIS API timeout", msg)

    async def test_prefix_is_red_circle(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_scheduler_error_alert(
                job_id="x", job_name="x", exception="ValueError: boom",
            )
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\U0001f534"))

    async def test_traceback_included_when_provided(self) -> None:
        agent = self._make_agent()
        tb = 'File "foo.py", line 42\n    raise ValueError("boom")\nValueError: boom'
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_scheduler_error_alert(
                job_id="x", job_name="x", exception="ValueError: boom",
                traceback_excerpt=tb,
            )
        msg = mock_send.await_args[1]["message"]
        self.assertIn("스택(요약)", msg)
        self.assertIn("ValueError: boom", msg)

    async def test_traceback_omitted_when_empty(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_scheduler_error_alert(
                job_id="x", job_name="x", exception="ValueError: boom",
            )
        msg = mock_send.await_args[1]["message"]
        self.assertNotIn("스택(요약)", msg)

    async def test_returns_false_on_send_failure(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=False)):
            result = await agent.send_scheduler_error_alert(
                job_id="x", job_name="x", exception="Boom",
            )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
