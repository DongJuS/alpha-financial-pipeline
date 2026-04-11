"""
test/integration/test_api_auth.py — Auth API 통합 테스트

FastAPI TestClient로 인증 라우터를 격리 테스트한다.
DB는 mock으로 대체.

테스트 대상:
  - POST /api/v1/auth/login — 로그인 성공, 토큰 반환
  - GET  /api/v1/users/me  — 토큰으로 내 정보 조회
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import auth as auth_module
from src.api.routers.auth import router as auth_router
from src.utils.auth import hash_password

_PATCH_PREFIX = "src.api.routers.auth"

API_PREFIX = "/api/v1"

_TEST_USER_ID = str(uuid4())
_TEST_EMAIL = "admin@alpha-trading.com"
_TEST_PASSWORD = "admin123"


def _build_client(*, authenticated: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix=API_PREFIX)
    if authenticated:
        async def mock_user():
            return {
                "sub": _TEST_USER_ID,
                "email": _TEST_EMAIL,
                "name": "Admin",
                "is_admin": True,
            }
        app.dependency_overrides[get_current_user] = mock_user
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret"
    )
    return TestClient(app, raise_server_exceptions=False)


class TestAuthLogin:
    """POST /api/v1/auth/login"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_login_success_returns_token(self, mock_fetchrow: AsyncMock) -> None:
        """올바른 자격 증명으로 로그인하면 200과 토큰을 반환한다."""
        mock_fetchrow.return_value = {
            "id": _TEST_USER_ID,
            "email": _TEST_EMAIL,
            "name": "Admin",
            "password_hash": hash_password(_TEST_PASSWORD),
            "is_admin": True,
        }

        client = _build_client(authenticated=False)
        resp = client.post(
            f"{API_PREFIX}/auth/login",
            json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert isinstance(body["token"], str)
        assert len(body["token"]) > 0


class TestUsersMe:
    """GET /api/v1/users/me"""

    def test_get_current_user_with_valid_token(self) -> None:
        """유효한 토큰으로 현재 사용자 정보를 조회한다."""
        client = _build_client(authenticated=True)
        resp = client.get(f"{API_PREFIX}/users/me")
        assert resp.status_code == 200
        body = resp.json()
        assert "email" in body
        assert body["email"] == _TEST_EMAIL
        assert "id" in body
