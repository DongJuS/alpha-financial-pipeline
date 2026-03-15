"""
src/llm/gpt_client.py — OpenAI GPT 호출 래퍼
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.secret_validation import is_placeholder_secret

logger = get_logger(__name__)


class GPTClient:
    _global_quota_exhausted = False

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self._client: Optional[Any] = None
        self._quota_exhausted = self.__class__._global_quota_exhausted

        if is_placeholder_secret(self.api_key):
            return

        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key)
        except Exception as e:
            logger.warning("OpenAI SDK 초기화 실패: %s", e)
            self._client = None

    @property
    def is_configured(self) -> bool:
        return self._client is not None and not self.__class__._global_quota_exhausted

    def _is_quota_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return "insufficient_quota" in text or "exceeded your current quota" in text

    async def ask(self, prompt: str, temperature: float = 0.2) -> str:
        if not self._client:
            raise RuntimeError("GPT client is not configured.")
        if self.__class__._global_quota_exhausted:
            raise RuntimeError("GPT quota exhausted.")

        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            if self._is_quota_error(e):
                self._quota_exhausted = True
                self.__class__._global_quota_exhausted = True
                logger.warning("OpenAI quota exhausted: GPT 호출을 세션 동안 비활성화합니다.")
            raise

    async def ask_json(self, prompt: str, temperature: float = 0.4) -> dict:
        text = await self.ask(prompt + "\n\nJSON 객체 하나만 출력하세요.", temperature=temperature)
        return _extract_json(text)


def _extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출합니다."""
    import re

    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        return json.loads(md_match.group(1).strip())
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))
    return json.loads(text)
