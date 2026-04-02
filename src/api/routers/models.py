"""
src/api/routers/models.py — 모델/페르소나 관리 라우터
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.deps import get_admin_user
from src.services.model_config import (
    SUPPORTED_MODEL_OPTIONS,
    ensure_model_role_configs,
    provider_status,
    update_model_role_configs,
)

router = APIRouter()


class SupportedModelItem(BaseModel):
    model: str
    provider: str
    label: str
    description: str


class ProviderStatusItem(BaseModel):
    provider: str
    mode: str
    default_model: str
    configured: bool


class ModelRoleItem(BaseModel):
    config_key: str
    strategy_code: str
    role: str
    role_label: str
    agent_id: str
    llm_model: str
    persona: str
    execution_order: int
    is_enabled: bool = True
    updated_at: Optional[str] = None


class ModelConfigResponse(BaseModel):
    rule_based_fallback_allowed: bool
    supported_models: list[SupportedModelItem]
    provider_status: list[ProviderStatusItem]
    strategy_a: list[ModelRoleItem]
    strategy_b: list[ModelRoleItem]


class ModelRoleUpdateItem(BaseModel):
    config_key: str
    llm_model: str
    persona: str = Field(..., min_length=1, max_length=300)
    is_enabled: bool = True


class ModelConfigUpdateRequest(BaseModel):
    items: list[ModelRoleUpdateItem]


async def _build_response() -> ModelConfigResponse:
    from src.services.model_config import get_strategy_a_profiles, get_strategy_b_roles

    a_rows = await get_strategy_a_profiles(enabled_only=False)
    b_rows = await get_strategy_b_roles(enabled_only=False)
    return ModelConfigResponse(
        rule_based_fallback_allowed=False,
        supported_models=[SupportedModelItem(**item) for item in SUPPORTED_MODEL_OPTIONS],
        provider_status=[ProviderStatusItem(**item) for item in provider_status()],
        strategy_a=[ModelRoleItem(**row) for row in a_rows],
        strategy_b=[ModelRoleItem(**row) for row in b_rows],
    )


@router.get("/config", response_model=ModelConfigResponse)
async def get_model_config(
    _: Annotated[dict, Depends(get_admin_user)],
) -> ModelConfigResponse:
    return await _build_response()


@router.put("/config", response_model=ModelConfigResponse)
async def update_model_config(
    body: ModelConfigUpdateRequest,
    _: Annotated[dict, Depends(get_admin_user)],
) -> ModelConfigResponse:
    try:
        await update_model_role_configs([item.model_dump() for item in body.items])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return await _build_response()


@router.get("/debug-providers")
async def debug_providers(
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """Provider 연결 상태 디버그 정보 — 문제 진단용."""
    import os
    import shutil

    from src.llm.cli_bridge import _claude_known_paths, build_cli_command, is_cli_available
    from src.llm.gemini_client import load_gemini_oauth_credentials
    from src.llm.gpt_client import GPTClient, load_codex_auth_status
    from src.utils.config import get_settings
    from src.utils.secret_validation import is_placeholder_secret

    settings = get_settings()

    # Claude 진단
    cli_template = settings.anthropic_cli_command
    cli_command = build_cli_command(cli_template, model="claude-3-5-sonnet-latest")
    claude_which = shutil.which("claude") if cli_command else None
    claude_known_paths = {
        p: os.path.isfile(p)
        for p in _claude_known_paths()
    }

    # Gemini 진단
    gcloud_cred_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    adc_paths = {
        p: os.path.isfile(p)
        for p in [
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
            "/root/.config/gcloud/application_default_credentials.json",
        ]
    }
    gemini_creds, gemini_project = load_gemini_oauth_credentials()
    gpt = GPTClient(model="gpt-4o-mini")
    codex_auth = load_codex_auth_status()

    return {
        "claude": {
            "env_ANTHROPIC_CLI_COMMAND": cli_template,
            "built_command": cli_command,
            "shutil_which_claude": claude_which,
            "is_cli_available": is_cli_available(cli_command),
            "known_paths": claude_known_paths,
            "api_key_set": bool(settings.anthropic_api_key and settings.anthropic_api_key != "sk-ant-..."),
        },
        "gemini": {
            "env_GOOGLE_APPLICATION_CREDENTIALS": gcloud_cred_env,
            "adc_file_paths": adc_paths,
            "oauth_credentials_loaded": gemini_creds is not None,
            "oauth_project_id": gemini_project,
        },
        "gpt": {
            "env_OPENAI_API_KEY": not is_placeholder_secret(settings.openai_api_key),
            "codex_auth_file_exists": codex_auth["exists"],
            "codex_auth_mode": codex_auth["auth_mode"],
            "codex_has_access_token": codex_auth["has_access_token"],
            "codex_has_refresh_token": codex_auth["has_refresh_token"],
            "codex_has_stored_api_key": codex_auth["has_api_key"],
            "configured": gpt.is_configured,
            "auth_mode": gpt.auth_mode,
            "effective_model": gpt.effective_model,
        },
    }
