"""
test/integration/test_api_auth.py — Auth API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 인증 관련 엔드포인트를 검증합니다.

테스트 대상:
  - POST /api/v1/auth/login — 로그인 성공, 토큰 반환
  - GET  /api/v1/users/me  — 토큰으로 내 정보 조회
"""

from __future__ import annotations

import os
import unittest

import httpx
import pytest

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:18000")
LOGIN_EMAIL = "admin@alpha-trading.com"
LOGIN_PASSWORD = "admin123"


async def get_token() -> str:
    """로그인하여 JWT 토큰을 획득합니다."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["token"]


@pytest.mark.integration
class TestAuthLogin(unittest.IsolatedAsyncioTestCase):
    """POST /api/v1/auth/login"""

    async def test_login_success_returns_token(self) -> None:
        """올바른 자격 증명으로 로그인하면 200과 토큰을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("token", body)
        self.assertIsInstance(body["token"], str)
        self.assertGreater(len(body["token"]), 0)


@pytest.mark.integration
class TestUsersMe(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/users/me"""

    async def test_get_current_user_with_valid_token(self) -> None:
        """유효한 토큰으로 현재 사용자 정보를 조회한다."""
        token = await get_token()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("email", body)
        self.assertEqual(body["email"], LOGIN_EMAIL)
        self.assertIn("id", body)
