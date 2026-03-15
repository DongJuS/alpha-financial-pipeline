"""
src/services/kis_session.py — KIS OAuth 토큰 저장/발급 헬퍼
"""

from __future__ import annotations

import json

import httpx

from src.utils.config import (
    Settings,
    get_settings,
    kis_account_number_for_scope,
    kis_app_key_for_scope,
    kis_app_secret_for_scope,
)
from src.utils.account_scope import AccountScope, normalize_account_scope
from src.utils.redis_client import TTL_KIS_TOKEN, get_redis, kis_oauth_token_key


async def issue_kis_token(
    settings: Settings | None = None,
    account_scope: AccountScope = "paper",
) -> dict:
    active_settings = settings or get_settings()
    scope = normalize_account_scope(account_scope)
    app_key = kis_app_key_for_scope(active_settings, scope)
    app_secret = kis_app_secret_for_scope(active_settings, scope)

    if not app_key or not app_secret:
        raise RuntimeError("KIS_APP_KEY 또는 KIS_APP_SECRET 이 설정되지 않았습니다.")

    url = f"{active_settings.kis_base_url_for_scope(scope)}/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    async with httpx.AsyncClient(timeout=active_settings.kis_request_timeout_seconds) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    if data.get("rt_cd") not in {None, "0"}:
        raise RuntimeError(f"KIS 토큰 발급 오류: {data.get('msg1', '알 수 없는 오류')}")

    token_info = {
        "access_token": data["access_token"],
        "token_type": data.get("token_type", "Bearer"),
        "expires_in": data.get("expires_in", 86400),
        "is_paper": scope == "paper",
        "account_scope": scope,
    }

    redis = await get_redis()
    await redis.set(kis_oauth_token_key(scope), json.dumps(token_info), ex=TTL_KIS_TOKEN)
    return token_info


async def get_stored_kis_token(account_scope: AccountScope = "paper") -> str | None:
    redis = await get_redis()
    raw = await redis.get(kis_oauth_token_key(account_scope))
    if not raw:
        return None

    token_info = json.loads(raw)
    return token_info.get("access_token")


async def ensure_kis_token(
    settings: Settings | None = None,
    account_scope: AccountScope = "paper",
) -> str:
    scope = normalize_account_scope(account_scope)
    token = await get_stored_kis_token(scope)
    if token:
        return token
    token_info = await issue_kis_token(settings=settings, account_scope=scope)
    return str(token_info["access_token"])


async def revoke_kis_token(
    settings: Settings | None = None,
    account_scope: AccountScope = "paper",
) -> None:
    active_settings = settings or get_settings()
    scope = normalize_account_scope(account_scope)
    redis = await get_redis()
    token_key = kis_oauth_token_key(scope)
    raw = await redis.get(token_key)
    if not raw:
        return

    token_info = json.loads(raw)
    url = f"{active_settings.kis_base_url_for_scope(scope)}/oauth2/revokeP"
    app_key = kis_app_key_for_scope(active_settings, scope)
    app_secret = kis_app_secret_for_scope(active_settings, scope)
    payload = {
        "appkey": app_key,
        "appsecret": app_secret,
        "token": token_info["access_token"],
    }

    async with httpx.AsyncClient(timeout=active_settings.kis_request_timeout_seconds) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError:
            pass

    await redis.delete(token_key)
