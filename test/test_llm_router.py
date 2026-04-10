"""
test/test_llm_router.py — LLMRouter unit tests
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestProviderForModel(unittest.TestCase):
    """provider_for_model staticmethod: model name → provider string."""

    def _call(self, model_name: str) -> str:
        from src.llm.router import LLMRouter
        return LLMRouter.provider_for_model(model_name)

    def test_claude_model(self) -> None:
        self.assertEqual(self._call("claude-3-5-sonnet-latest"), "claude")

    def test_gpt_model(self) -> None:
        self.assertEqual(self._call("gpt-4o"), "gpt")

    def test_gemini_model(self) -> None:
        self.assertEqual(self._call("gemini-1.5-pro"), "gemini")

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._call("llama-3-70b")


class TestProviderOrder(unittest.TestCase):
    """provider_order: primary provider first, then fallbacks."""

    def _router(self):
        from src.llm.router import LLMRouter
        return LLMRouter()

    def test_claude_primary(self) -> None:
        router = self._router()
        order = router.provider_order("claude-3-5-sonnet-latest")
        self.assertEqual(order[0], "claude")
        self.assertEqual(len(order), 3)
        self.assertIn("gpt", order)
        self.assertIn("gemini", order)

    def test_gpt_primary(self) -> None:
        router = self._router()
        order = router.provider_order("gpt-4o")
        self.assertEqual(order[0], "gpt")
        self.assertEqual(len(order), 3)

    def test_gemini_primary(self) -> None:
        router = self._router()
        order = router.provider_order("gemini-1.5-pro")
        self.assertEqual(order[0], "gemini")
        self.assertEqual(len(order), 3)


class TestGetClientCaching(unittest.TestCase):
    """_get_client returns the same instance for the same provider."""

    def test_same_provider_returns_same_instance(self) -> None:
        from src.llm.router import LLMRouter

        router = LLMRouter()
        with patch("src.llm.claude_client.ClaudeClient", autospec=False) as MockClaude:
            mock_instance = MagicMock()
            MockClaude.return_value = mock_instance
            first = router._get_client("claude")

        second = router._get_client("claude")
        self.assertIs(first, second)


def _build_router(claude_cfg=True, gpt_cfg=True, gemini_cfg=True):
    """Build a router with mocked clients injected directly."""
    from src.llm.router import LLMRouter

    mock_claude = MagicMock()
    mock_claude.is_configured = claude_cfg
    mock_claude.ask_json = AsyncMock(return_value={"answer": "claude"})
    mock_claude.ask = AsyncMock(return_value="claude text")

    mock_gpt = MagicMock()
    mock_gpt.is_configured = gpt_cfg
    mock_gpt.ask_json = AsyncMock(return_value={"answer": "gpt"})
    mock_gpt.ask = AsyncMock(return_value="gpt text")

    mock_gemini = MagicMock()
    mock_gemini.is_configured = gemini_cfg
    mock_gemini.ask_json = AsyncMock(return_value={"answer": "gemini"})
    mock_gemini.ask = AsyncMock(return_value="gemini text")

    router = LLMRouter()
    router._clients = {
        "claude": mock_claude,
        "gpt": mock_gpt,
        "gemini": mock_gemini,
    }
    return router, mock_claude, mock_gpt, mock_gemini


class TestAskJson(unittest.IsolatedAsyncioTestCase):
    """ask_json: success, fallback, all-fail, temperature passthrough."""

    async def test_primary_success(self) -> None:
        router, mock_claude, mock_gpt, _gemini = _build_router()
        result = await router.ask_json("claude-3-5-sonnet-latest", "test prompt")
        self.assertEqual(result, {"answer": "claude"})
        mock_claude.ask_json.assert_awaited_once()
        mock_gpt.ask_json.assert_not_awaited()

    async def test_fallback_on_primary_failure(self) -> None:
        router, mock_claude, mock_gpt, _gemini = _build_router()
        mock_claude.ask_json = AsyncMock(side_effect=RuntimeError("primary fail"))

        result = await router.ask_json("claude-3-5-sonnet-latest", "test prompt")
        self.assertEqual(result, {"answer": "gpt"})
        mock_gpt.ask_json.assert_awaited_once()

    async def test_all_providers_fail_raises_runtime_error(self) -> None:
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_claude.ask_json = AsyncMock(side_effect=RuntimeError("claude fail"))
        mock_gpt.ask_json = AsyncMock(side_effect=RuntimeError("gpt fail"))
        mock_gemini.ask_json = AsyncMock(side_effect=RuntimeError("gemini fail"))

        with self.assertRaises(RuntimeError):
            await router.ask_json("claude-3-5-sonnet-latest", "test prompt")

    async def test_temperature_passed_through(self) -> None:
        router, mock_claude, _gpt, _gemini = _build_router()
        await router.ask_json("claude-3-5-sonnet-latest", "prompt", temperature=0.9)
        call_kwargs = mock_claude.ask_json.call_args
        self.assertEqual(call_kwargs.kwargs.get("temperature"), 0.9)

    async def test_unconfigured_provider_skipped(self) -> None:
        router, mock_claude, mock_gpt, _gemini = _build_router(claude_cfg=False)
        result = await router.ask_json("claude-3-5-sonnet-latest", "prompt")
        self.assertEqual(result, {"answer": "gpt"})
        mock_claude.ask_json.assert_not_awaited()
        mock_gpt.ask_json.assert_awaited_once()


class TestAskText(unittest.IsolatedAsyncioTestCase):
    """ask_text: success and fallback paths."""

    async def test_text_primary_success(self) -> None:
        router, mock_claude, mock_gpt, _gemini = _build_router()
        result = await router.ask_text("gpt-4o", "hello")
        self.assertEqual(result, "gpt text")
        mock_gpt.ask.assert_awaited_once()
        mock_claude.ask.assert_not_awaited()

    async def test_text_fallback_on_failure(self) -> None:
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_gpt.ask = AsyncMock(side_effect=RuntimeError("gpt fail"))

        result = await router.ask_text("gpt-4o", "hello")
        self.assertIn(result, ("claude text", "gemini text"))
        fallback_called = mock_claude.ask.await_count + mock_gemini.ask.await_count
        self.assertGreaterEqual(fallback_called, 1)

    async def test_text_all_fail_raises_runtime_error(self) -> None:
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_claude.ask = AsyncMock(side_effect=RuntimeError("fail"))
        mock_gpt.ask = AsyncMock(side_effect=RuntimeError("fail"))
        mock_gemini.ask = AsyncMock(side_effect=RuntimeError("fail"))

        with self.assertRaises(RuntimeError):
            await router.ask_text("gemini-1.5-pro", "hello")


if __name__ == "__main__":
    unittest.main()
