"""provider_status() 함수 단위 테스트.

provider_status()는 Claude/GPT/Gemini 세 프로바이더의 연결 상태를
독립적으로 조회한다.  기존 API 테스트들이 이 함수를 mock으로 대체하므로,
여기서 함수 내부 로직(3개 항목 반환, fallback 처리, 필수 키 존재)을 직접 검증한다.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.services.model_config import provider_status

REQUIRED_KEYS = {"provider", "mode", "default_model", "configured"}


class TestProviderStatus(unittest.TestCase):
    """provider_status() 핵심 동작 검증."""

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _make_claude_mock(**overrides):
        m = MagicMock()
        m._cli_command = overrides.get("_cli_command", [])
        m._client = overrides.get("_client", None)
        m.is_configured = overrides.get("is_configured", False)
        return m

    @staticmethod
    def _make_gpt_mock(**overrides):
        m = MagicMock()
        m.auth_mode = overrides.get("auth_mode", None)
        m.effective_model = overrides.get("effective_model", "gpt-4o-mini")
        m.is_configured = overrides.get("is_configured", False)
        return m

    @staticmethod
    def _make_gemini_mock(**overrides):
        m = MagicMock()
        m.auth_mode = overrides.get("auth_mode", None)
        m.is_configured = overrides.get("is_configured", False)
        return m

    def _patch_all_clients(self, *, claude_rv=None, gpt_rv=None, gemini_rv=None):
        """세 클라이언트를 한번에 mock patch한다."""
        if claude_rv is None:
            claude_rv = self._make_claude_mock()
        if gpt_rv is None:
            gpt_rv = self._make_gpt_mock()
        if gemini_rv is None:
            gemini_rv = self._make_gemini_mock()

        return (
            patch("src.services.model_config.ClaudeClient", return_value=claude_rv),
            patch("src.services.model_config.GPTClient", return_value=gpt_rv),
            patch("src.services.model_config.GeminiClient", return_value=gemini_rv),
        )

    # ── 테스트 케이스 ───────────────────────────────────────────

    def test_provider_status_returns_all_three_providers(self):
        """provider_status() 호출 시 claude, gpt, gemini 3개 항목이 모두 반환되어야 한다."""
        p_claude, p_gpt, p_gemini = self._patch_all_clients()
        with p_claude, p_gpt, p_gemini:
            result = provider_status()

        providers = [item["provider"] for item in result]
        self.assertEqual(len(result), 3)
        self.assertIn("claude", providers)
        self.assertIn("gpt", providers)
        self.assertIn("gemini", providers)

    def test_provider_status_gpt_included_without_api_key(self):
        """OPENAI_API_KEY 미설정 환경에서도 GPT 항목이 반환되고 configured=False여야 한다."""
        gpt_mock = self._make_gpt_mock(auth_mode=None, is_configured=False)
        p_claude, p_gpt, p_gemini = self._patch_all_clients(gpt_rv=gpt_mock)
        with p_claude, p_gpt, p_gemini:
            result = provider_status()

        gpt_items = [item for item in result if item["provider"] == "gpt"]
        self.assertEqual(len(gpt_items), 1)
        self.assertFalse(gpt_items[0]["configured"])
        self.assertEqual(gpt_items[0]["mode"], "미연결")

    def test_provider_status_each_item_has_required_keys(self):
        """각 항목에 provider, mode, default_model, configured 키가 존재해야 한다."""
        claude_mock = self._make_claude_mock(_cli_command=["/usr/bin/claude"], is_configured=True)
        gpt_mock = self._make_gpt_mock(auth_mode="api_key", is_configured=True, effective_model="gpt-4o")
        gemini_mock = self._make_gemini_mock(auth_mode="oauth", is_configured=True)
        p_claude, p_gpt, p_gemini = self._patch_all_clients(
            claude_rv=claude_mock, gpt_rv=gpt_mock, gemini_rv=gemini_mock,
        )
        with p_claude, p_gpt, p_gemini:
            result = provider_status()

        for item in result:
            self.assertTrue(
                REQUIRED_KEYS.issubset(item.keys()),
                f"항목 {item.get('provider', '?')}에 필수 키 누락: "
                f"{REQUIRED_KEYS - item.keys()}",
            )

    def test_provider_status_handles_client_init_failure(self):
        """클라이언트 초기화가 예외를 던져도 해당 프로바이더가 fallback 값으로 반환되어야 한다."""
        with (
            patch("src.services.model_config.ClaudeClient", side_effect=RuntimeError("boom")),
            patch("src.services.model_config.GPTClient", side_effect=RuntimeError("boom")),
            patch("src.services.model_config.GeminiClient", side_effect=RuntimeError("boom")),
        ):
            result = provider_status()

        # 3개 모두 fallback으로 반환
        self.assertEqual(len(result), 3)
        providers = {item["provider"] for item in result}
        self.assertEqual(providers, {"claude", "gpt", "gemini"})

        for item in result:
            self.assertFalse(item["configured"], f"{item['provider']} should be configured=False on init failure")
            self.assertEqual(item["mode"], "미연결", f"{item['provider']} should have mode='미연결' on init failure")
            self.assertTrue(
                REQUIRED_KEYS.issubset(item.keys()),
                f"fallback 항목 {item['provider']}에 필수 키 누락",
            )


if __name__ == "__main__":
    unittest.main()
