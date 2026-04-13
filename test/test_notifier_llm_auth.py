"""LLM 인증 알림 테스트."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from src.agents.notifier import NotifierAgent


class TestSendLlmAuthAlert(unittest.IsolatedAsyncioTestCase):
    """NotifierAgent.send_llm_auth_alert() 단위 테스트."""

    def _make_agent(self) -> NotifierAgent:
        return NotifierAgent()

    # ── 1. 정상 호출 ──────────────────────────────────────────────
    async def test_send_llm_auth_alert_calls_send(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            result = await agent.send_llm_auth_alert(
                provider="claude", status="api_key_only",
            )
        self.assertTrue(result)
        mock_send.assert_awaited_once()
        _, kwargs = mock_send.await_args
        self.assertEqual(kwargs["event_type"], "llm_auth_alert")
        self.assertIn("claude", kwargs["message"])
        self.assertIn("api_key_only", kwargs["message"])

    # ── 2. 이모지 매핑 ────────────────────────────────────────────
    async def test_emoji_mapping_cli_ok(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="claude", status="cli_ok")
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\u2705"))  # ✅

    async def test_emoji_mapping_oauth_ok(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="gemini", status="oauth_ok")
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\u2705"))  # ✅

    async def test_emoji_mapping_oauth_token_ok(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="claude", status="oauth_token_ok")
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\u2705"))  # ✅

    async def test_emoji_mapping_api_key_only(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="codex", status="api_key_only")
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\u26a0\ufe0f"))  # ⚠️

    async def test_emoji_mapping_unavailable(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="codex", status="unavailable")
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\U0001f534"))  # 🔴

    async def test_emoji_mapping_unknown_status(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="gemini", status="something_new")
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\u2753"))  # ❓

    # ── 3. detail 포함 ───────────────────────────────────────────
    async def test_detail_included_in_message(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(
                provider="claude",
                status="api_key_only",
                detail="CLI token expired, falling back to API key",
            )
        msg = mock_send.await_args[1]["message"]
        self.assertIn("CLI token expired, falling back to API key", msg)
        self.assertIn("상세:", msg)

    async def test_no_detail_omits_detail_line(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(provider="claude", status="cli_ok")
        msg = mock_send.await_args[1]["message"]
        self.assertNotIn("상세:", msg)

    # ── 4. error status → 🔴 ─────────────────────────────────────
    async def test_error_status_gets_red_emoji(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(
                provider="claude", status="error:timeout",
            )
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\U0001f534"))  # 🔴

    async def test_error_connection_status_gets_red_emoji(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)) as mock_send:
            await agent.send_llm_auth_alert(
                provider="gemini", status="error:connection_refused",
            )
        msg = mock_send.await_args[1]["message"]
        self.assertTrue(msg.startswith("\U0001f534"))  # 🔴

    # ── 5. 반환값 전파 ───────────────────────────────────────────
    async def test_returns_true_on_send_success(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=True)):
            self.assertTrue(await agent.send_llm_auth_alert("claude", "cli_ok"))

    async def test_returns_false_on_send_failure(self) -> None:
        agent = self._make_agent()
        with patch.object(agent, "send", new=AsyncMock(return_value=False)):
            self.assertFalse(await agent.send_llm_auth_alert("claude", "unavailable"))


if __name__ == "__main__":
    unittest.main()
