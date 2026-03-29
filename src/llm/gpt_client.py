"""
src/llm/gpt_client.py — OpenAI GPT 호출 래퍼
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Optional

from src.llm.cli_bridge import is_cli_available, run_cli_prompt_with_output_file
from src.services.llm_usage_limiter import reserve_provider_call
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.secret_validation import is_placeholder_secret

logger = get_logger(__name__)

CODEX_MODEL_MAP = {
    "gpt-4o": "gpt-5.4",
    "gpt-4o-mini": "gpt-5.4-mini",
    "gpt-4-turbo": "gpt-5.4",
}


def resolve_codex_model(model: str) -> str:
    return CODEX_MODEL_MAP.get(model, model)


def load_codex_auth_status() -> dict[str, object]:
    auth_path = os.path.expanduser("~/.codex/auth.json")
    status = {
        "exists": os.path.isfile(auth_path),
        "auth_mode": None,
        "has_access_token": False,
        "has_refresh_token": False,
        "has_api_key": False,
    }
    if not status["exists"]:
        return status

    try:
        with open(auth_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return status

    tokens = payload.get("tokens") or {}
    status["auth_mode"] = payload.get("auth_mode")
    status["has_access_token"] = bool(tokens.get("access_token"))
    status["has_refresh_token"] = bool(tokens.get("refresh_token"))
    status["has_api_key"] = bool(payload.get("OPENAI_API_KEY"))
    return status


def _build_codex_cli_command(model: str) -> list[str]:
    if shutil.which("codex") is None:
        return []

    auth_status = load_codex_auth_status()
    has_chatgpt_login = bool(auth_status["has_access_token"] and auth_status["has_refresh_token"])
    if not auth_status["has_api_key"] and not has_chatgpt_login:
        return []

    return [
        "codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-m",
        resolve_codex_model(model),
    ]


class GPTClient:
    _global_quota_exhausted = False

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self.cli_timeout_seconds = settings.llm_cli_timeout_seconds
        self._client: Optional[Any] = None
        self._cli_command: list[str] = []
        self._auth_mode: Optional[str] = None
        self._effective_model = model
        self._quota_exhausted = self.__class__._global_quota_exhausted
        if not is_placeholder_secret(self.api_key):
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=self.api_key)
                self._auth_mode = "api_key"
                return
            except Exception as e:
                logger.warning("OpenAI SDK 초기화 실패: %s", e)
                self._client = None

        self._cli_command = _build_codex_cli_command(self.model)
        if self._cli_command and is_cli_available(self._cli_command):
            self._auth_mode = "codex_cli"
            self._effective_model = resolve_codex_model(self.model)
            logger.info(
                "OpenAI Codex CLI 모드 활성화: requested=%s actual=%s",
                self.model,
                self._effective_model,
            )

    @property
    def is_configured(self) -> bool:
        cli_command = getattr(self, "_cli_command", [])
        client = getattr(self, "_client", None)
        return (bool(cli_command) or client is not None) and not self.__class__._global_quota_exhausted

    @property
    def auth_mode(self) -> Optional[str]:
        return getattr(self, "_auth_mode", None)

    @property
    def effective_model(self) -> str:
        return getattr(self, "_effective_model", self.model)

    def _is_quota_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return "insufficient_quota" in text or "exceeded your current quota" in text

    async def ask(self, prompt: str, temperature: float = 0.2) -> str:
        if self.__class__._global_quota_exhausted:
            raise RuntimeError("GPT quota exhausted.")
        cli_command = getattr(self, "_cli_command", [])
        if not (cli_command or self._client):
            raise RuntimeError("GPT client is not configured.")

        provider_name = "codex" if cli_command else "gpt"
        await reserve_provider_call(provider_name)

        if cli_command:
            try:
                return await run_cli_prompt_with_output_file(
                    command=cli_command,
                    prompt=prompt,
                    timeout_seconds=self.cli_timeout_seconds,
                )
            except Exception as e:
                if self._is_quota_error(e):
                    self._quota_exhausted = True
                    self.__class__._global_quota_exhausted = True
                    logger.warning("OpenAI quota exhausted.")
                raise
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
                logger.warning("OpenAI quota exhausted.")
            raise

    async def ask_json(self, prompt: str, temperature: float = 0.4) -> dict:
        text = await self.ask(prompt + "\n\nJSON 객체 하나만 출력하세요.", temperature=temperature)
        return _extract_json(text)


def _extract_json(text: str) -> dict:
    import re
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        return json.loads(md_match.group(1).strip())
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))
    return json.loads(text)
