"""
src/llm/claude_client.py — Claude 호출 래퍼
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.llm.cli_bridge import build_cli_command, is_cli_available, run_cli_prompt
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.secret_validation import is_placeholder_secret

logger = get_logger(__name__)


def _extract_json(text: str) -> dict:
    """문자열에서 첫 JSON 객체를 추출합니다."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class ClaudeClient:
    def __init__(self, model: str = "claude-3-5-sonnet-latest") -> None:
        self.model = model
        settings = get_settings()
        self.api_key = settings.anthropic_api_key
        self.cli_timeout_seconds = settings.llm_cli_timeout_seconds
        self._cli_command = build_cli_command(settings.anthropic_cli_command, model=self.model)
        self._client: Optional[Any] = None

        if self._cli_command:
            if is_cli_available(self._cli_command):
                logger.info("Claude CLI 모드 활성화: %s", self._cli_command[0])
                return
            logger.warning("Claude CLI 명령을 찾을 수 없어 SDK 모드로 폴백: %s", self._cli_command[0])
            self._cli_command = []

        if is_placeholder_secret(self.api_key):
            return

        try:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self.api_key)
        except Exception as e:
            logger.warning("Claude SDK 초기화 실패: %s", e)
            self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self._cli_command) or self._client is not None

    async def ask(self, prompt: str, max_tokens: int = 600, temperature: float = 0.2) -> str:
        if self._cli_command:
            return await run_cli_prompt(
                command=self._cli_command,
                prompt=prompt,
                timeout_seconds=self.cli_timeout_seconds,
            )
        if not self._client:
            raise RuntimeError("Claude client is not configured.")

        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = [getattr(c, "text", "") for c in getattr(resp, "content", [])]
        return "".join(text_parts).strip()

    async def ask_json(self, prompt: str, max_tokens: int = 600, temperature: float = 0.4) -> dict:
        text = await self.ask(
            prompt=prompt + "\n\n반드시 JSON 객체 하나만 추출하세요.",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return _extract_json(text)
