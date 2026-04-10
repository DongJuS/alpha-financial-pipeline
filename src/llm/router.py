"""
src/llm/router.py — LLM 호출 통합 라우터

여러 LLM 프로바이더(Claude/GPT/Gemini)에 대해 단일 인터페이스를 제공하고,
프로바이더별 폴백 체인을 자동 처리한다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PROVIDER_KEYWORDS: dict[str, list[str]] = {
    "claude": ["claude", "anthropic", "sonnet", "opus", "haiku"],
    "gpt": ["gpt", "openai", "o1", "o3", "o4"],
    "gemini": ["gemini", "google"],
}

_FALLBACK_ORDER: dict[str, list[str]] = {
    "claude": ["claude", "gpt", "gemini"],
    "gpt": ["gpt", "claude", "gemini"],
    "gemini": ["gemini", "claude", "gpt"],
}


class LLMRouter:
    """LLM 프로바이더 폴백 체인을 관리하는 통합 라우터."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    @staticmethod
    def provider_for_model(model: str) -> str:
        """모델 이름 문자열로부터 프로바이더를 판별한다."""
        model_lower = model.lower()
        for provider, keywords in _PROVIDER_KEYWORDS.items():
            if any(kw in model_lower for kw in keywords):
                return provider
        raise ValueError(f"Unknown model: {model!r} — cannot determine provider")

    def provider_order(self, model: str) -> list[str]:
        """주어진 모델에 대해 [primary, fallback1, fallback2] 순서를 반환한다."""
        primary = self.provider_for_model(model)
        return list(_FALLBACK_ORDER[primary])

    def _get_client(self, provider: str) -> Any:
        """프로바이더별 클라이언트를 지연 생성하고 캐시한다."""
        if provider in self._clients:
            return self._clients[provider]

        if provider == "claude":
            from src.llm.claude_client import ClaudeClient

            client = ClaudeClient()
        elif provider == "gpt":
            from src.llm.gpt_client import GPTClient

            client = GPTClient()
        elif provider == "gemini":
            from src.llm.gemini_client import GeminiClient

            client = GeminiClient()
        else:
            raise ValueError(f"Unknown provider: {provider!r}")

        self._clients[provider] = client
        return client

    async def ask_json(
        self,
        model: str,
        prompt: str,
        *,
        temperature: float = 0.5,
    ) -> dict:
        """프로바이더 폴백 체인으로 JSON 응답을 요청한다."""
        order = self.provider_order(model)
        errors: list[str] = []

        for idx, provider in enumerate(order):
            try:
                client = self._get_client(provider)
                if not client.is_configured:
                    reason = f"{provider} client is not configured"
                    logger.debug(reason)
                    errors.append(reason)
                    continue

                result = await client.ask_json(prompt, temperature=temperature)

                if idx > 0:
                    logger.info(
                        "LLMRouter fallback 사용: %s → %s (model=%s)",
                        order[0],
                        provider,
                        model,
                    )
                return result
            except Exception as exc:
                msg = f"{provider}: {type(exc).__name__}: {exc}"
                logger.warning("LLMRouter %s 실패: %s", provider, exc)
                errors.append(msg)

        raise RuntimeError(
            f"All LLM providers failed for model={model!r}. "
            f"Errors: {'; '.join(errors)}"
        )

    async def ask_text(
        self,
        model: str,
        prompt: str,
        *,
        temperature: float = 0.5,
    ) -> str:
        """프로바이더 폴백 체인으로 텍스트 응답을 요청한다."""
        order = self.provider_order(model)
        errors: list[str] = []

        for idx, provider in enumerate(order):
            try:
                client = self._get_client(provider)
                if not client.is_configured:
                    reason = f"{provider} client is not configured"
                    logger.debug(reason)
                    errors.append(reason)
                    continue

                result = await client.ask(prompt, temperature=temperature)

                if idx > 0:
                    logger.info(
                        "LLMRouter fallback 사용: %s → %s (model=%s)",
                        order[0],
                        provider,
                        model,
                    )
                return result
            except Exception as exc:
                msg = f"{provider}: {type(exc).__name__}: {exc}"
                logger.warning("LLMRouter %s 실패: %s", provider, exc)
                errors.append(msg)

        raise RuntimeError(
            f"All LLM providers failed for model={model!r}. "
            f"Errors: {'; '.join(errors)}"
        )
