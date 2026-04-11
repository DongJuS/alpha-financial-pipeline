"""
test/test_llm_router_unit.py -- src/llm/router.py 보강 단위 테스트

기존 test_llm_router.py에 더해 edge case와 fallback 시나리오를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


def _build_router(claude_cfg=True, gpt_cfg=True, gemini_cfg=True):
    """Mock 클라이언트가 주입된 라우터 빌드."""
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


# ── provider_for_model edge cases ──────────────────────────────────────────


class TestProviderForModelEdgeCases:
    def test_opus_model(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("claude-opus-4") == "claude"

    def test_haiku_model(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("claude-3-haiku") == "claude"

    def test_o1_model(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("o1-mini") == "gpt"

    def test_o3_model(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("o3-mini") == "gpt"

    def test_o4_model(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("o4-mini") == "gpt"

    def test_google_keyword(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("google-gemini-pro") == "gemini"

    def test_case_insensitive(self):
        from src.llm.router import LLMRouter

        assert LLMRouter.provider_for_model("Claude-3-5-Sonnet") == "claude"
        assert LLMRouter.provider_for_model("GPT-4o") == "gpt"
        assert LLMRouter.provider_for_model("Gemini-1.5-Pro") == "gemini"


# ── provider_order ──────────────────────────────────────────────────────────


class TestProviderOrderDetailed:
    def test_claude_fallback_order(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        order = router.provider_order("claude-3-5-sonnet")
        assert order == ["claude", "gpt", "gemini"]

    def test_gpt_fallback_order(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        order = router.provider_order("gpt-4o")
        assert order == ["gpt", "claude", "gemini"]

    def test_gemini_fallback_order(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        order = router.provider_order("gemini-1.5-pro")
        assert order == ["gemini", "claude", "gpt"]


# ── ask_json fallback ──────────────────────────────────────────────────────


class TestAskJsonFallbackDetailed:
    @pytest.mark.asyncio
    async def test_falls_through_all_three(self):
        """모든 프로바이더가 순서대로 시도되는지 확인."""
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_claude.ask_json = AsyncMock(side_effect=RuntimeError("claude fail"))
        mock_gpt.ask_json = AsyncMock(side_effect=RuntimeError("gpt fail"))

        result = await router.ask_json("claude-3-5-sonnet", "test")
        assert result == {"answer": "gemini"}
        mock_gemini.ask_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_unconfigured_then_fails(self):
        """모든 프로바이더가 미설정이면 RuntimeError."""
        router, _, _, _ = _build_router(claude_cfg=False, gpt_cfg=False, gemini_cfg=False)

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await router.ask_json("claude-3-5-sonnet", "test")

    @pytest.mark.asyncio
    async def test_error_message_contains_all_failures(self):
        """에러 메시지에 모든 프로바이더 실패 정보가 포함."""
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_claude.ask_json = AsyncMock(side_effect=RuntimeError("claude error"))
        mock_gpt.ask_json = AsyncMock(side_effect=ValueError("gpt error"))
        mock_gemini.ask_json = AsyncMock(side_effect=TimeoutError("gemini timeout"))

        with pytest.raises(RuntimeError) as exc_info:
            await router.ask_json("claude-3-5-sonnet", "test")

        error_msg = str(exc_info.value)
        assert "claude" in error_msg.lower()
        assert "gpt" in error_msg.lower()
        assert "gemini" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_first_unconfigured_second_configured_succeeds(self):
        """primary 미설정 + secondary 설정 시 secondary 사용."""
        router, _, mock_gpt, _ = _build_router(claude_cfg=False)

        result = await router.ask_json("claude-3-5-sonnet", "test")
        assert result == {"answer": "gpt"}


# ── ask_text fallback ──────────────────────────────────────────────────────


class TestAskTextFallbackDetailed:
    @pytest.mark.asyncio
    async def test_gemini_primary_with_fallback(self):
        router, mock_claude, _, mock_gemini = _build_router()
        mock_gemini.ask = AsyncMock(side_effect=RuntimeError("gemini fail"))

        result = await router.ask_text("gemini-1.5-pro", "hello")
        assert result == "claude text"
        mock_claude.ask.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_unconfigured_raises(self):
        router, _, _, _ = _build_router(claude_cfg=False, gpt_cfg=False, gemini_cfg=False)

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await router.ask_text("gpt-4o", "hello")


# ── _get_client ─────────────────────────────────────────────────────────────


class TestGetClient:
    def test_unknown_provider_raises(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        with pytest.raises(ValueError, match="Unknown provider"):
            router._get_client("llama")

    def test_claude_client_created(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        with patch("src.llm.claude_client.ClaudeClient") as MockClaude:
            MockClaude.return_value = MagicMock()
            client = router._get_client("claude")
            assert client is not None

    def test_gpt_client_created(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        with patch("src.llm.gpt_client.GPTClient") as MockGPT:
            MockGPT.return_value = MagicMock()
            client = router._get_client("gpt")
            assert client is not None

    def test_gemini_client_created(self):
        from src.llm.router import LLMRouter

        router = LLMRouter()
        with patch("src.llm.gemini_client.GeminiClient") as MockGemini:
            MockGemini.return_value = MagicMock()
            client = router._get_client("gemini")
            assert client is not None

    def test_client_caching(self):
        """동일 provider에 대해 _get_client가 동일 인스턴스를 반환 (캐시)."""
        from src.llm.router import LLMRouter

        router = LLMRouter()
        mock_instance = MagicMock()
        with patch("src.llm.claude_client.ClaudeClient", return_value=mock_instance):
            first = router._get_client("claude")
            second = router._get_client("claude")
        assert first is second


# ── LLM 라우터 에지케이스 (Agent 4 QA Round 2) ───────────────────────────────


class TestAllProvidersFailSimultaneously:
    """모든 프로바이더가 동시에 다양한 방식으로 실패하는 시나리오."""

    @pytest.mark.asyncio
    async def test_mixed_unconfigured_and_exceptions(self):
        """일부 미설정 + 나머지 예외: 에러 메시지에 모든 실패 사유 포함."""
        router, _, mock_gpt, mock_gemini = _build_router(claude_cfg=False)
        mock_gpt.ask_json = AsyncMock(side_effect=ConnectionError("connection refused"))
        mock_gemini.ask_json = AsyncMock(side_effect=TimeoutError("timed out"))

        with pytest.raises(RuntimeError) as exc_info:
            await router.ask_json("claude-3-5-sonnet", "test")

        error_msg = str(exc_info.value)
        assert "not configured" in error_msg  # claude
        assert "connection refused" in error_msg  # gpt
        assert "timed out" in error_msg  # gemini

    @pytest.mark.asyncio
    async def test_ask_text_mixed_failures(self):
        """ask_text에서도 동일한 패턴의 에러 전파."""
        router, mock_claude, _, mock_gemini = _build_router(gpt_cfg=False)
        mock_claude.ask = AsyncMock(side_effect=RuntimeError("auth expired"))
        mock_gemini.ask = AsyncMock(side_effect=ValueError("invalid response"))

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await router.ask_text("claude-3-5-sonnet", "test")


class TestFallbackChainOrder:
    """폴백 체인이 정확한 순서로 실행되는지 상세 검증."""

    @pytest.mark.asyncio
    async def test_gpt_primary_fallback_to_gemini(self):
        """GPT가 primary이고 Claude도 실패하면 Gemini로 폴백."""
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_gpt.ask_json = AsyncMock(side_effect=RuntimeError("gpt down"))
        mock_claude.ask_json = AsyncMock(side_effect=RuntimeError("claude down"))

        result = await router.ask_json("gpt-4o", "test")
        assert result == {"answer": "gemini"}
        mock_gemini.ask_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_gemini_primary_fallback_order(self):
        """Gemini가 primary일 때 Claude → GPT 순서로 폴백."""
        router, mock_claude, mock_gpt, mock_gemini = _build_router()
        mock_gemini.ask_json = AsyncMock(side_effect=RuntimeError("gemini fail"))

        result = await router.ask_json("gemini-1.5-pro", "test")
        # fallback order: gemini → claude → gpt
        assert result == {"answer": "claude"}
        mock_claude.ask_json.assert_awaited_once()
        mock_gpt.ask_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_temperature_propagated_to_fallback(self):
        """폴백 프로바이더에도 temperature가 전달."""
        router, mock_claude, mock_gpt, _ = _build_router()
        mock_claude.ask_json = AsyncMock(side_effect=RuntimeError("fail"))

        await router.ask_json("claude-3-5-sonnet", "prompt", temperature=0.1)
        call_kwargs = mock_gpt.ask_json.call_args
        assert call_kwargs.kwargs.get("temperature") == 0.1


class TestProviderForModelEdgeCasesExtended:
    """provider_for_model: 특수한 모델 이름 패턴."""

    def test_anthropic_keyword(self):
        from src.llm.router import LLMRouter
        assert LLMRouter.provider_for_model("anthropic-custom-model") == "claude"

    def test_openai_keyword(self):
        from src.llm.router import LLMRouter
        assert LLMRouter.provider_for_model("openai-gpt4-custom") == "gpt"

    def test_empty_model_raises(self):
        from src.llm.router import LLMRouter
        with pytest.raises(ValueError, match="Unknown model"):
            LLMRouter.provider_for_model("")

    def test_numeric_only_model_raises(self):
        from src.llm.router import LLMRouter
        with pytest.raises(ValueError, match="Unknown model"):
            LLMRouter.provider_for_model("12345")
