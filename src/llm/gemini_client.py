"""
src/llm/gemini_client.py — Gemini 호출 래퍼
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.services.llm_usage_limiter import reserve_provider_call
from src.utils.logging import get_logger

logger = get_logger(__name__)
# cloud-platform 스코프만 사용 (generative-language는 ADC에서 invalid_scope 에러 발생)
GEMINI_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
)

import re

_cached_credentials: tuple[Any | None, str | None] | None = None


def _clear_gemini_oauth_credentials_cache() -> None:
    global _cached_credentials
    _cached_credentials = None


def _extract_json(text: str) -> dict:
    """마크다운 코드 블록 포함 JSON 추출."""
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        return json.loads(md_match.group(1).strip())
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))
    return json.loads(text)


def _is_running_in_container() -> bool:
    """Docker/K8s 컨테이너 내부에서 실행 중인지 감지합니다."""
    import os

    if os.path.isfile("/.dockerenv"):
        return True
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read() or "kubepods" in f.read()
    except (FileNotFoundError, PermissionError):
        return False


def load_gemini_oauth_credentials() -> tuple[Any | None, str | None]:
    global _cached_credentials
    if _cached_credentials is not None and _cached_credentials[0] is not None:
        return _cached_credentials
    import os

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if cred_path and os.path.isfile(cred_path):
        logger.info("GOOGLE_APPLICATION_CREDENTIALS 파일 발견: %s", cred_path)

    # ADC 탐색 경로: 로컬 + Docker/K8s 마운트 경로
    adc_paths = [
        os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
        "/root/.config/gcloud/application_default_credentials.json",
        "/var/secrets/google/credentials.json",       # K8s secret mount
        "/etc/google/auth/application_default_credentials.json",  # GKE workload identity
    ]
    for adc_path in adc_paths:
        if not cred_path and os.path.isfile(adc_path):
            logger.info("gcloud ADC 파일 발견: %s", adc_path)
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


load_gemini_oauth_credentials.cache_clear = _clear_gemini_oauth_credentials_cache  # type: ignore[attr-defined]


def gemini_oauth_available() -> bool:
    credentials, _ = load_gemini_oauth_credentials()
    return credentials is not None


class GeminiClient:
    _global_quota_exhausted = False
    _global_disabled_reason: str | None = None

    def __init__(self, model: str = "gemini-1.5-pro") -> None:
        self.model = model
        self._model: Optional[Any] = None
        self._auth_mode: Optional[str] = None
        self._quota_exhausted = self.__class__._global_quota_exhausted
        self._configure_oauth()

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

    @property
    def is_configured(self) -> bool:
        return (
            self._model is not None
            and not self.__class__._global_quota_exhausted
            and self.__class__._global_disabled_reason is None
        )

    @property
    def auth_mode(self) -> Optional[str]:
        return self._auth_mode

    @classmethod
    def reset_global_state(cls) -> None:
        cls._global_quota_exhausted = False
        cls._global_disabled_reason = None

    @classmethod
    def disabled_reason(cls) -> str | None:
        return cls._global_disabled_reason

    def _is_quota_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return any(token in text for token in ("quota", "resource_exhausted", "resource exhausted", "429", "rate limit", "too many requests"))

    def _is_auth_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return any(
            token in text
            for token in (
                "permission denied",
                "insufficient authentication scopes",
                "access_token_scope_insufficient",
                "invalid_scope",
                "authentication",
                "unauthorized",
                "credentials",
            )
        )

    @classmethod
    def _disable_globally(cls, reason: str) -> None:
        if cls._global_disabled_reason is None:
            logger.warning(reason)
        cls._global_disabled_reason = reason

    async def ask(self, prompt: str, temperature: float = 0.4) -> str:
        if self.__class__._global_quota_exhausted:
            raise RuntimeError("Gemini quota exhausted.")
        if self.__class__._global_disabled_reason is not None:
            raise RuntimeError(self.__class__._global_disabled_reason)
        if not self._model:
            raise RuntimeError("Gemini client is not configured.")

        await reserve_provider_call("gemini")

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
                logger.warning("Gemini quota exhausted.")
            elif self._is_auth_error(e):
                reason = f"Gemini 인증이 불가해 비활성화합니다: {e}"
                self._disable_globally(reason)
                raise RuntimeError(reason) from e
            raise

    async def ask_json(self, prompt: str, temperature: float = 0.4) -> dict:
        text = await self.ask(prompt + "\n\nJSON 객체 하나만 출력하세요.", temperature=temperature)
        return _extract_json(text)
