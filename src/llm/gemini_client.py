"""
src/llm/gemini_client.py — Gemini 호출 래퍼
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.secret_validation import is_placeholder_secret

logger = get_logger(__name__)
GEMINI_OAUTH_SCOPES = ("https://www.googleapis.com/auth/generative-language",)

import re

_cached_credentials: tuple[Any | None, str | None] | None = None


def _extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출합니다 (마크다운 코드 블록 포함 처리)."""
    # ```json ... ``` 또는 ``` ... ``` 내부 추출
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        return json.loads(md_match.group(1).strip())
    # 순수 JSON 추출
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))
    return json.loads(text)


def load_gemini_oauth_credentials() -> tuple[Any | None, str | None]:
    global _cached_credentials

    # 성공했던 캐시가 있으면 재사용
    if _cached_credentials is not None and _cached_credentials[0] is not None:
        return _cached_credentials

    import os

    # 1) GOOGLE_APPLICATION_CREDENTIALS 환경변수 확인
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if cred_path and os.path.isfile(cred_path):
        logger.info("GOOGLE_APPLICATION_CREDENTIALS 파일 발견: %s", cred_path)

    # 2) gcloud ADC 기본 경로 확인 (Docker 마운트 대응)
    adc_paths = [
        os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
        "/root/.config/gcloud/application_default_credentials.json",
    ]
    for adc_path in adc_paths:
        if not cred_path and os.path.isfile(adc_path):
            logger.info("gcloud ADC 파일 발견 → GOOGLE_APPLICATION_CREDENTIALS 자동 설정: %s", adc_path)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = adc_path
            break

    try:
        import google.auth

        credentials, project_id = google.auth.default(scopes=list(GEMINI_OAUTH_SCOPES))
        _cached_credentials = (credentials, project_id)
        return _cached_credentials
    except Exception as exc:
        logger.info("Gemini OAuth credentials unavailable: %s", exc)
        _cached_credentials = (None, None)
        return _cached_credentials


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

    async def ask(self, prompt: str, temperature: float = 0.4) -> str:
        if self.__class__._global_quota_exhausted:
            raise RuntimeError("Gemini quota exhausted.")
        if not self._model:
            raise RuntimeError("Gemini client is not configured.")

        import asyncio
        import google.generativeai as genai

        generation_config = genai.types.GenerationConfig(temperature=temperature)

        def _run() -> str:
            resp = self._model.generate_content(prompt, generation_config=generation_config)
            return getattr(resp, "text", "") or ""

        try:
            return (await asyncio.to_thread(_run)).strip()
        except Exception as e:
            if self._is_quota_error(e):
                self._quota_exhausted = True
                self.__class__._global_quota_exhausted = True
                logger.warning("Gemini quota exhausted: Gemini 호출을 세션 동안 비활성화합니다.")
            raise

    async def ask_json(self, prompt: str, temperature: float = 0.4) -> dict:
        text = await self.ask(prompt + "\n\nJSON 객체 하나만 출력하세요.", temperature=temperature)
        return _extract_json(text)
