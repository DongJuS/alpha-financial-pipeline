"""
src/llm/gemini_client.py — Gemini 호출 래퍼
"""

from __future__ import annotations

from functools import lru_cache
import json
from typing import Any, Optional

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.secret_validation import is_placeholder_secret

logger = get_logger(__name__)
GEMINI_OAUTH_SCOPES = ("https://www.googleapis.com/auth/generative-language",)


@lru_cache(maxsize=1)
def load_gemini_oauth_credentials() -> tuple[Any | None, str | None]:
    try:
        import google.auth

        return google.auth.default(scopes=list(GEMINI_OAUTH_SCOPES))
    except Exception as exc:
        logger.info("Gemini OAuth credentials unavailable: %s", exc)
        return None, None


def gemini_oauth_available() -> bool:
    credentials, _ = load_gemini_oauth_credentials()
    return credentials is not None


class GeminiClient:
    _global_quota_exhausted = False

    def __init__(self, model: str = "gemini-1.5-pro") -> None:
        self.model = model
        settings = get_settings()
        self.api_key = settings.gemini_api_key
        self._model: Optional[Any] = None
        self._auth_mode: Optional[str] = None
        self._quota_exhausted = self.__class__._global_quota_exhausted

        if self._configure_oauth():
            return
        self._configure_api_key()

    def _configure_oauth(self) -> bool:
        credentials, project_id = load_gemini_oauth_credentials()
        if credentials is None:
            return False

        try:
            import google.generativeai as genai

            genai.configure(credentials=credentials)
            self._model = genai.GenerativeModel(self.model)
            self._auth_mode = "oauth"
            suffix = f" (project={project_id})" if project_id else ""
            logger.info("Gemini OAuth 모드 활성화%s", suffix)
            return True
        except Exception as exc:
            logger.warning("Gemini OAuth 초기화 실패: %s", exc)
            self._model = None
            return False

    def _configure_api_key(self) -> bool:
        if is_placeholder_secret(self.api_key):
            return False

        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model)
            self._auth_mode = "api_key"
            logger.info("Gemini API key 모드 활성화")
            return True
        except Exception as exc:
            logger.warning("Gemini SDK 초기화 실패: %s", exc)
            self._model = None
            return False

    @property
    def is_configured(self) -> bool:
        return self._model is not None and not self.__class__._global_quota_exhausted

    @property
    def auth_mode(self) -> Optional[str]:
        return self._auth_mode

    def _is_quota_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return any(
            token in text
            for token in (
                "quota",
                "resource_exhausted",
                "resource exhausted",
                "429",
                "rate limit",
                "too many requests",
            )
        )

    async def ask(self, prompt: str) -> str:
        if self.__class__._global_quota_exhausted:
            raise RuntimeError("Gemini quota exhausted.")
        if not self._model:
            raise RuntimeError("Gemini client is not configured.")

        # Gemini SDK는 동기 호출이므로 스레드 오프로 실행
        import asyncio

        def _run() -> str:
            resp = self._model.generate_content(prompt)
            return getattr(resp, "text", "") or ""

        try:
            return (await asyncio.to_thread(_run)).strip()
        except Exception as e:
            if self._is_quota_error(e):
                self._quota_exhausted = True
                self.__class__._global_quota_exhausted = True
                logger.warning("Gemini quota exhausted: Gemini 호출을 세션 동안 비활성화합니다.")
            raise

    async def ask_json(self, prompt: str) -> dict:
        text = await self.ask(prompt + "\n\nJSON 객체 하나만 출력하세요.")
        return json.loads(text)
