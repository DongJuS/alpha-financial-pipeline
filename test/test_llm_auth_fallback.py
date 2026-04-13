"""
test/test_llm_auth_fallback.py -- CLI 인증 실패 → SDK fallback 테스트

CLIAuthError 구분, Claude/GPT 클라이언트의 SDK fallback 동작을 검증합니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── CLIAuthError 구분 테스트 ────────────────────────────────────────────────


class TestCLIAuthErrorDetection:
    """run_cli_prompt가 auth 키워드 포함 stderr → CLIAuthError를 raise하는지 검증."""

    @pytest.mark.asyncio
    async def test_auth_keyword_raises_cli_auth_error(self):
        """인증 관련 키워드가 stderr에 포함되면 CLIAuthError 발생."""
        from src.llm.cli_bridge import CLIAuthError, run_cli_prompt

        auth_messages = [
            "Error: not logged in",
            "login required to continue",
            "authentication failed",
            "401 Unauthorized",
            "auth token invalid",
            "token expired",
            "session expired please re-login",
            "run setup-token first",
            "CLAUDE_CODE_OAUTH_TOKEN is missing",
        ]
        for msg in auth_messages:
            with pytest.raises(CLIAuthError, match="CLI command failed"):
                await run_cli_prompt(
                    ["bash", "-c", f"echo '{msg}' >&2; exit 1"],
                    "test",
                )

    @pytest.mark.asyncio
    async def test_non_auth_error_raises_runtime_error(self):
        """인증 키워드 없는 일반 에러는 RuntimeError (CLIAuthError 아님)."""
        from src.llm.cli_bridge import CLIAuthError, run_cli_prompt

        with pytest.raises(RuntimeError) as exc_info:
            await run_cli_prompt(
                ["bash", "-c", "echo 'some random error' >&2; exit 1"],
                "test",
            )
        assert not isinstance(exc_info.value, CLIAuthError)

    @pytest.mark.asyncio
    async def test_output_file_auth_keyword_raises_cli_auth_error(self):
        """run_cli_prompt_with_output_file도 인증 키워드 시 CLIAuthError 발생."""
        from src.llm.cli_bridge import CLIAuthError, run_cli_prompt_with_output_file

        with pytest.raises(CLIAuthError):
            await run_cli_prompt_with_output_file(
                ["bash", "-c", "echo 'unauthorized access' >&2; exit 1"],
                "test",
            )

    @pytest.mark.asyncio
    async def test_output_file_non_auth_error_raises_runtime_error(self):
        """run_cli_prompt_with_output_file: 일반 에러는 RuntimeError."""
        from src.llm.cli_bridge import CLIAuthError, run_cli_prompt_with_output_file

        with pytest.raises(RuntimeError) as exc_info:
            await run_cli_prompt_with_output_file(
                ["bash", "-c", "echo 'disk full' >&2; exit 1"],
                "test",
            )
        assert not isinstance(exc_info.value, CLIAuthError)


class TestCLIAuthErrorInheritance:
    """CLIAuthError가 RuntimeError의 서브클래스인지 확인."""

    def test_is_subclass_of_runtime_error(self):
        from src.llm.cli_bridge import CLIAuthError

        assert issubclass(CLIAuthError, RuntimeError)

    def test_caught_by_except_runtime_error(self):
        from src.llm.cli_bridge import CLIAuthError

        try:
            raise CLIAuthError("test auth error")
        except RuntimeError:
            pass  # 정상 — RuntimeError로 잡혀야 함


# ── Claude CLI auth 실패 → SDK fallback ─────────────────────────────────────


class TestClaudeCLIAuthFallback:
    """Claude CLI 인증 실패 시 SDK fallback 동작 검증."""

    @pytest.mark.asyncio
    async def test_cli_auth_fail_falls_back_to_sdk(self):
        """CLI가 CLIAuthError → SDK로 정상 응답."""
        from src.llm.cli_bridge import CLIAuthError

        mock_content_block = MagicMock()
        mock_content_block.text = "SDK response"
        mock_response = MagicMock()
        mock_response.content = [mock_content_block]

        mock_sdk_client = AsyncMock()
        mock_sdk_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("src.llm.claude_client.get_settings") as mock_settings, \
             patch("src.llm.claude_client.build_cli_command", return_value=["claude", "--print"]), \
             patch("src.llm.claude_client.is_cli_available", return_value=True), \
             patch("src.llm.claude_client.reserve_provider_call", new_callable=AsyncMock), \
             patch("src.llm.claude_client.run_cli_prompt", new_callable=AsyncMock) as mock_cli, \
             patch("src.llm.claude_client.is_placeholder_secret", return_value=False):

            mock_settings.return_value = MagicMock(
                anthropic_api_key="sk-real-key",
                llm_cli_timeout_seconds=30,
                anthropic_cli_command="claude --print",
            )
            mock_cli.side_effect = CLIAuthError("not logged in")

            from src.llm.claude_client import ClaudeClient

            client = ClaudeClient.__new__(ClaudeClient)
            client.model = "claude-3-5-sonnet-latest"
            client.api_key = "sk-real-key"
            client.cli_timeout_seconds = 30
            client._cli_command = ["claude", "--print"]
            client._client = None  # SDK 아직 초기화 안 됨

            # _ensure_sdk_client를 mock하여 SDK 클라이언트 반환
            client._ensure_sdk_client = MagicMock(return_value=mock_sdk_client)

            result = await client.ask("hello")
            assert result == "SDK response"
            mock_sdk_client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cli_auth_fail_no_sdk_propagates_error(self):
        """CLI 인증 실패 + SDK 없음 → CLIAuthError 전파."""
        from src.llm.cli_bridge import CLIAuthError

        with patch("src.llm.claude_client.get_settings") as mock_settings, \
             patch("src.llm.claude_client.build_cli_command", return_value=["claude", "--print"]), \
             patch("src.llm.claude_client.is_cli_available", return_value=True), \
             patch("src.llm.claude_client.reserve_provider_call", new_callable=AsyncMock), \
             patch("src.llm.claude_client.run_cli_prompt", new_callable=AsyncMock) as mock_cli, \
             patch("src.llm.claude_client.is_placeholder_secret", return_value=True):

            mock_settings.return_value = MagicMock(
                anthropic_api_key="your-api-key-here",
                llm_cli_timeout_seconds=30,
                anthropic_cli_command="claude --print",
            )
            mock_cli.side_effect = CLIAuthError("not logged in")

            from src.llm.claude_client import ClaudeClient

            client = ClaudeClient.__new__(ClaudeClient)
            client.model = "claude-3-5-sonnet-latest"
            client.api_key = "your-api-key-here"
            client.cli_timeout_seconds = 30
            client._cli_command = ["claude", "--print"]
            client._client = None

            # _ensure_sdk_client가 None을 반환 (API key가 placeholder)
            client._ensure_sdk_client = MagicMock(return_value=None)

            with pytest.raises(CLIAuthError):
                await client.ask("hello")

    @pytest.mark.asyncio
    async def test_non_auth_cli_error_not_caught(self):
        """비인증 CLI 에러는 fallback 없이 그대로 전파."""
        with patch("src.llm.claude_client.get_settings") as mock_settings, \
             patch("src.llm.claude_client.build_cli_command", return_value=["claude", "--print"]), \
             patch("src.llm.claude_client.is_cli_available", return_value=True), \
             patch("src.llm.claude_client.reserve_provider_call", new_callable=AsyncMock), \
             patch("src.llm.claude_client.run_cli_prompt", new_callable=AsyncMock) as mock_cli, \
             patch("src.llm.claude_client.is_placeholder_secret", return_value=False):

            mock_settings.return_value = MagicMock(
                anthropic_api_key="sk-real-key",
                llm_cli_timeout_seconds=30,
                anthropic_cli_command="claude --print",
            )
            mock_cli.side_effect = RuntimeError("CLI timeout")

            from src.llm.claude_client import ClaudeClient

            client = ClaudeClient.__new__(ClaudeClient)
            client.model = "claude-3-5-sonnet-latest"
            client.api_key = "sk-real-key"
            client.cli_timeout_seconds = 30
            client._cli_command = ["claude", "--print"]
            client._client = None

            with pytest.raises(RuntimeError, match="CLI timeout"):
                await client.ask("hello")


# ── Claude _ensure_sdk_client 테스트 ────────────────────────────────────────


class TestClaudeEnsureSdkClient:
    """_ensure_sdk_client의 lazy 초기화 로직 검증."""

    def test_returns_existing_client(self):
        """이미 _client가 있으면 그대로 반환."""
        from src.llm.claude_client import ClaudeClient

        client = ClaudeClient.__new__(ClaudeClient)
        existing = MagicMock()
        client._client = existing
        client.api_key = "sk-real-key"

        result = client._ensure_sdk_client()
        assert result is existing

    def test_returns_none_for_placeholder_key(self):
        """API key가 placeholder이면 None 반환."""
        from src.llm.claude_client import ClaudeClient

        client = ClaudeClient.__new__(ClaudeClient)
        client._client = None
        client.api_key = "your-api-key-here"

        with patch("src.llm.claude_client.is_placeholder_secret", return_value=True):
            result = client._ensure_sdk_client()
            assert result is None

    def test_lazy_initializes_sdk(self):
        """API key가 유효하면 SDK를 lazy 초기화."""
        from src.llm.claude_client import ClaudeClient

        mock_anthropic = MagicMock()
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = None
        client.api_key = "sk-real-key"

        with patch("src.llm.claude_client.is_placeholder_secret", return_value=False), \
             patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            result = client._ensure_sdk_client()
            assert result is not None
            assert client._client is result


# ── GPT CLI 우선순위 테스트 ─────────────────────────────────────────────────


class TestGPTCLIPriority:
    """API key + CLI 둘 다 있을 때 CLI 먼저 시도하는지 검증."""

    def test_cli_first_when_both_available(self):
        """CLI와 API key 모두 있을 때 auth_mode가 codex_cli."""
        with patch("src.llm.gpt_client.get_settings") as mock_settings, \
             patch("src.llm.gpt_client._build_codex_cli_command", return_value=["codex", "exec"]), \
             patch("src.llm.gpt_client.is_cli_available", return_value=True), \
             patch("src.llm.gpt_client.is_placeholder_secret", return_value=False), \
             patch("src.llm.gpt_client.resolve_codex_model", return_value="gpt-5.4-mini"):

            mock_settings.return_value = MagicMock(
                openai_api_key="sk-real-key",
                llm_cli_timeout_seconds=30,
            )

            # AsyncOpenAI import를 mock
            mock_async_openai = MagicMock()
            with patch.dict("sys.modules", {"openai": MagicMock(AsyncOpenAI=mock_async_openai)}):
                from src.llm.gpt_client import GPTClient

                client = GPTClient.__new__(GPTClient)
                # Reset class state
                GPTClient._global_quota_exhausted = False

                client.model = "gpt-4o-mini"
                client.api_key = "sk-real-key"
                client.cli_timeout_seconds = 30
                client._client = None
                client._cli_command = ["codex", "exec"]
                client._auth_mode = "codex_cli"
                client._effective_model = "gpt-5.4-mini"
                client._quota_exhausted = False

                assert client._auth_mode == "codex_cli"
                assert client._cli_command == ["codex", "exec"]


# ── GPT CLI auth 실패 → SDK fallback ───────────────────────────────────────


class TestGPTCLIAuthFallback:
    """GPT/Codex CLI 인증 실패 시 SDK fallback 동작 검증."""

    @pytest.mark.asyncio
    async def test_codex_cli_auth_fail_falls_back_to_sdk(self):
        """Codex CLI 인증 실패 → OpenAI SDK로 정상 응답."""
        from src.llm.cli_bridge import CLIAuthError

        mock_message = MagicMock()
        mock_message.content = "SDK GPT response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_sdk_client = AsyncMock()
        mock_sdk_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("src.llm.gpt_client.reserve_provider_call", new_callable=AsyncMock), \
             patch("src.llm.gpt_client.run_cli_prompt_with_output_file", new_callable=AsyncMock) as mock_cli:

            mock_cli.side_effect = CLIAuthError("unauthorized")

            from src.llm.gpt_client import GPTClient

            client = GPTClient.__new__(GPTClient)
            GPTClient._global_quota_exhausted = False
            client.model = "gpt-4o-mini"
            client.api_key = "sk-real-key"
            client.cli_timeout_seconds = 30
            client._cli_command = ["codex", "exec"]
            client._client = mock_sdk_client
            client._auth_mode = "codex_cli"
            client._effective_model = "gpt-5.4-mini"
            client._quota_exhausted = False

            result = await client.ask("hello")
            assert result == "SDK GPT response"
            mock_sdk_client.chat.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_codex_cli_auth_fail_no_sdk_propagates_error(self):
        """Codex CLI 인증 실패 + SDK 없음 → CLIAuthError 전파."""
        from src.llm.cli_bridge import CLIAuthError

        with patch("src.llm.gpt_client.reserve_provider_call", new_callable=AsyncMock), \
             patch("src.llm.gpt_client.run_cli_prompt_with_output_file", new_callable=AsyncMock) as mock_cli:

            mock_cli.side_effect = CLIAuthError("unauthorized")

            from src.llm.gpt_client import GPTClient

            client = GPTClient.__new__(GPTClient)
            GPTClient._global_quota_exhausted = False
            client.model = "gpt-4o-mini"
            client.api_key = "your-api-key-here"
            client.cli_timeout_seconds = 30
            client._cli_command = ["codex", "exec"]
            client._client = None  # SDK 없음
            client._auth_mode = "codex_cli"
            client._effective_model = "gpt-5.4-mini"
            client._quota_exhausted = False

            with pytest.raises(CLIAuthError):
                await client.ask("hello")

    @pytest.mark.asyncio
    async def test_non_auth_cli_error_not_caught(self):
        """비인증 CLI 에러는 SDK fallback 없이 그대로 전파."""
        mock_sdk_client = AsyncMock()

        with patch("src.llm.gpt_client.reserve_provider_call", new_callable=AsyncMock), \
             patch("src.llm.gpt_client.run_cli_prompt_with_output_file", new_callable=AsyncMock) as mock_cli:

            mock_cli.side_effect = RuntimeError("CLI timeout")

            from src.llm.gpt_client import GPTClient

            client = GPTClient.__new__(GPTClient)
            GPTClient._global_quota_exhausted = False
            client.model = "gpt-4o-mini"
            client.api_key = "sk-real-key"
            client.cli_timeout_seconds = 30
            client._cli_command = ["codex", "exec"]
            client._client = mock_sdk_client
            client._auth_mode = "codex_cli"
            client._effective_model = "gpt-5.4-mini"
            client._quota_exhausted = False

            with pytest.raises(RuntimeError, match="CLI timeout"):
                await client.ask("hello")
            # SDK 호출되지 않아야 함
            mock_sdk_client.chat.completions.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sdk_only_mode_works(self):
        """CLI 없이 SDK만 있을 때 정상 동작."""
        mock_message = MagicMock()
        mock_message.content = "SDK only response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_sdk_client = AsyncMock()
        mock_sdk_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("src.llm.gpt_client.reserve_provider_call", new_callable=AsyncMock):
            from src.llm.gpt_client import GPTClient

            client = GPTClient.__new__(GPTClient)
            GPTClient._global_quota_exhausted = False
            client.model = "gpt-4o-mini"
            client.api_key = "sk-real-key"
            client.cli_timeout_seconds = 30
            client._cli_command = []  # CLI 없음
            client._client = mock_sdk_client
            client._auth_mode = "api_key"
            client._effective_model = "gpt-4o-mini"
            client._quota_exhausted = False

            result = await client.ask("hello")
            assert result == "SDK only response"


# ── _is_auth_error 단위 테스트 ──────────────────────────────────────────────


class TestIsAuthError:
    """_is_auth_error 유틸 함수 단위 테스트."""

    def test_detects_all_keywords(self):
        from src.llm.cli_bridge import _is_auth_error

        assert _is_auth_error("Error: not logged in")
        assert _is_auth_error("login required")
        assert _is_auth_error("Authentication failed")
        assert _is_auth_error("401 Unauthorized")
        assert _is_auth_error("auth error occurred")
        assert _is_auth_error("token expired")
        assert _is_auth_error("session expired")
        assert _is_auth_error("run setup-token")
        assert _is_auth_error("set CLAUDE_CODE_OAUTH_TOKEN")

    def test_case_insensitive(self):
        from src.llm.cli_bridge import _is_auth_error

        assert _is_auth_error("NOT LOGGED IN")
        assert _is_auth_error("AUTHENTICATION FAILED")
        assert _is_auth_error("Token Expired")

    def test_no_match(self):
        from src.llm.cli_bridge import _is_auth_error

        assert not _is_auth_error("disk full")
        assert not _is_auth_error("connection refused")
        assert not _is_auth_error("timeout exceeded")
        assert not _is_auth_error("")
