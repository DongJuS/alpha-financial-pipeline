from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.db.init_db import seed_default_admin
from src.api import deps as auth_deps
from src.api.deps import get_current_settings
from src.api.routers import auth
from src.utils.auth import hash_password


def build_auth_client() -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(jwt_secret="test-secret")
    return TestClient(app)


def test_login_and_users_me_revalidate_against_db(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()

    async def mock_login_fetchrow(query: str, *args: object) -> dict:
        assert "FROM users WHERE email = $1" in query
        assert args == ("admin@example.com",)
        return {
            "id": user_id,
            "email": "admin@example.com",
            "name": "Admin",
            "password_hash": hash_password("admin1234"),
            "is_admin": True,
        }

    async def mock_user_fetchrow(query: str, *args: object) -> dict:
        assert "FROM users WHERE id = $1::uuid" in query
        assert args == (user_id,)
        return {
            "id": user_id,
            "email": "admin@example.com",
            "name": "Admin",
            "is_admin": True,
        }

    monkeypatch.setattr(auth, "fetchrow", mock_login_fetchrow)
    monkeypatch.setattr(auth_deps, "fetchrow", mock_user_fetchrow)

    with build_auth_client() as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin1234"},
        )

        assert login_response.status_code == 200
        token = login_response.json()["token"]

        me_response = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert me_response.status_code == 200
    assert me_response.json() == {
        "id": str(user_id),
        "email": "admin@example.com",
        "name": "Admin",
        "is_admin": True,
    }


def test_users_me_rejects_token_for_deleted_user(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_user_fetchrow(query: str, *args: object) -> None:
        assert "FROM users WHERE id = $1::uuid" in query
        return None

    monkeypatch.setattr(auth_deps, "fetchrow", mock_user_fetchrow)

    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "email": "admin@example.com",
            "name": "Admin",
            "is_admin": True,
            "exp": int(time.time()) + 60,
        },
        "test-secret",
        algorithm="HS256",
    )

    with build_auth_client() as client:
        response = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "존재하지 않는 사용자입니다."


def test_seed_default_admin_creates_missing_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_ADMIN_SEED_ENABLED", "true")
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "seed-admin@example.com")
    monkeypatch.setenv("DEFAULT_ADMIN_NAME", "Seed Admin")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "seed-password")

    conn = AsyncMock()
    conn.fetchval.return_value = False

    created = asyncio.run(seed_default_admin(conn))

    assert created is True
    conn.fetchval.assert_awaited_once_with(
        "SELECT EXISTS (SELECT 1 FROM users WHERE email = $1)",
        "seed-admin@example.com",
    )
    conn.execute.assert_awaited_once()
    execute_args = conn.execute.await_args.args
    assert "INSERT INTO users" in execute_args[0]
    assert execute_args[1:] == (
        "seed-admin@example.com",
        "Seed Admin",
        hash_password("seed-password"),
    )
