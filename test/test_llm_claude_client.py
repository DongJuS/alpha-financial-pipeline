"""
test/test_llm_claude_client.py -- src/llm/claude_client.py 단위 테스트
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── _extract_json ───────────────────────────────────────────────────────────


class TestExtractJson:
    def test_valid_json(self):
        from src.llm.claude_client import _extract_json

        result = _extract_json('{"signal": "BUY"}')
        assert result == {"signal": "BUY"}

    def test_json_with_surrounding_text(self):
        from src.llm.claude_client import _extract_json

        text = 'Here is the analysis: {"signal": "SELL", "confidence": 0.8} end'
        result = _extract_json(text)
        assert result["signal"] == "SELL"
        assert result["confidence"] == 0.8

    def test_no_json_raises(self):
        from src.llm.claude_client import _extract_json

        with pytest.raises(json.JSONDecodeError):
            _extract_json("no json here")

    def test_nested_json(self):
        from src.llm.claude_client import _extract_json

        text = '{"signal": "BUY", "meta": {"source": "A"}}'
        result = _extract_json(text)
        assert result["meta"]["source"] == "A"

    def test_json_with_markdown_code_block(self):
        from src.llm.claude_client import _extract_json

        text = '```json\n{"signal": "HOLD"}\n```'
        result = _extract_json(text)
        assert result["signal"] == "HOLD"


# ── ClaudeClient 초기화 ────────────────────────────────────────────────────


class TestClaudeClientInit:
    def test_cli_mode_when_available(self):
        """CLI 바이너리가 있으면 CLI 모드로 초기화."""
        from src.llm.claude_client import ClaudeClient

        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        mock_settings.anthropic_cli_command = "echo"
        mock_settings.llm_cli_timeout_seconds = 90

        with (
            patch("src.llm.claude_client.get_settings", return_value=mock_settings),
            patch("src.llm.claude_client.build_cli_command", return_value=["echo"]),
            patch("src.llm.claude_client.is_cli_available", return_value=True),
        ):
            client = ClaudeClient()
            assert client.is_configured is True
            assert client._cli_command == ["echo"]

    def test_not_configured_when_no_key_no_cli(self):
        """API 키도 CLI도 없으면 미설정 상태."""
        from src.llm.claude_client import ClaudeClient

        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        mock_settings.anthropic_cli_command = ""
        mock_settings.llm_cli_timeout_seconds = 90

        with (
            patch("src.llm.claude_client.get_settings", return_value=mock_settings),
            patch("src.llm.claude_client.build_cli_command", return_value=[]),
            patch("src.llm.claude_client.is_placeholder_secret", return_value=True),
        ):
            client = ClaudeClient()
            assert client.is_configured is False


# ── ClaudeClient.ask ────────────────────────────────────────────────────────


class TestClaudeClientAsk:
    @pytest.mark.asyncio
    async def test_ask_raises_when_not_configured(self):
        """미설정 상태에서 ask() 호출 시 RuntimeError."""
        from src.llm.claude_client import ClaudeClient

        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        mock_settings.anthropic_cli_command = ""
        mock_settings.llm_cli_timeout_seconds = 90

        with (
            patch("src.llm.claude_client.get_settings", return_value=mock_settings),
            patch("src.llm.claude_client.build_cli_command", return_value=[]),
            patch("src.llm.claude_client.is_placeholder_secret", return_value=True),
        ):
            client = ClaudeClient()

        with pytest.raises(RuntimeError, match="not configured"):
            await client.ask("test prompt")

    @pytest.mark.asyncio
    async def test_ask_cli_mode(self):
        """CLI 모드에서 run_cli_prompt가 호출되는지 확인."""
        from src.llm.claude_client import ClaudeClient

        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        mock_settings.anthropic_cli_command = "echo"
        mock_settings.llm_cli_timeout_seconds = 90

        with (
            patch("src.llm.claude_client.get_settings", return_value=mock_settings),
            patch("src.llm.claude_client.build_cli_command", return_value=["echo"]),
            patch("src.llm.claude_client.is_cli_available", return_value=True),
        ):
            client = ClaudeClient()

        with (
            patch("src.llm.claude_client.run_cli_prompt", new_callable=AsyncMock, return_value="CLI response"),
            patch("src.llm.claude_client.reserve_provider_call", new_callable=AsyncMock),
        ):
            result = await client.ask("test prompt")

        assert result == "CLI response"


# ── ClaudeClient.ask_json ──────────────────────────────────────────────────


class TestClaudeClientAskJson:
    @pytest.mark.asyncio
    async def test_ask_json_parses_response(self):
        """ask_json이 JSON 응답을 올바르게 파싱."""
        from src.llm.claude_client import ClaudeClient

        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        mock_settings.anthropic_cli_command = "echo"
        mock_settings.llm_cli_timeout_seconds = 90

        with (
            patch("src.llm.claude_client.get_settings", return_value=mock_settings),
            patch("src.llm.claude_client.build_cli_command", return_value=["echo"]),
            patch("src.llm.claude_client.is_cli_available", return_value=True),
        ):
            client = ClaudeClient()

        mock_response = '{"signal": "BUY", "confidence": 0.85}'
        with (
            patch("src.llm.claude_client.run_cli_prompt", new_callable=AsyncMock, return_value=mock_response),
            patch("src.llm.claude_client.reserve_provider_call", new_callable=AsyncMock),
        ):
            result = await client.ask_json("분석해주세요")

        assert result["signal"] == "BUY"
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_ask_json_appends_json_instruction(self):
        """ask_json이 프롬프트에 JSON 출력 지시문을 추가."""
        from src.llm.claude_client import ClaudeClient

        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        mock_settings.anthropic_cli_command = "echo"
        mock_settings.llm_cli_timeout_seconds = 90

        with (
            patch("src.llm.claude_client.get_settings", return_value=mock_settings),
            patch("src.llm.claude_client.build_cli_command", return_value=["echo"]),
            patch("src.llm.claude_client.is_cli_available", return_value=True),
        ):
            client = ClaudeClient()

        captured_prompt = None

        async def _capture_cli(command, prompt, timeout_seconds=90):
            nonlocal captured_prompt
            captured_prompt = prompt
            return '{"result": "ok"}'

        with (
            patch("src.llm.claude_client.run_cli_prompt", side_effect=_capture_cli),
            patch("src.llm.claude_client.reserve_provider_call", new_callable=AsyncMock),
        ):
            await client.ask_json("원본 프롬프트")

        assert captured_prompt is not None
        assert "JSON" in captured_prompt
        assert "원본 프롬프트" in captured_prompt
