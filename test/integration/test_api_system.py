"""
test/integration/test_api_system.py — System / Scheduler / Health API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 시스템 엔드포인트를 검증합니다.

테스트 대상:
  - GET /               — 루트 (health or welcome)
  - GET /health         — 헬스체크
  - GET /api/v1/system/overview  — 시스템 개요
  - GET /api/v1/system/metrics   — 시스템 메트릭
  - GET /api/v1/scheduler/status — 스케줄러 상태
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
        return resp.json()["token"]


@pytest.mark.integration
class TestRootEndpoint(unittest.IsolatedAsyncioTestCase):
    """GET /"""

    async def test_root_returns_ok(self) -> None:
        """루트 엔드포인트가 정상 응답을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestHealthEndpoint(unittest.IsolatedAsyncioTestCase):
    """GET /health"""

    async def test_health_returns_ok(self) -> None:
        """헬스체크 엔드포인트가 정상 응답을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/health")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)
        # 헬스체크 응답에는 상태 필드가 있어야 한다
        self.assertTrue(
            "status" in body or "ok" in body or "healthy" in body,
            f"헬스체크 응답에 상태 필드가 없습니다: {body}",
        )


@pytest.mark.integration
class TestSystemOverview(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/system/overview"""

    async def test_get_system_overview(self) -> None:
        """시스템 개요 정보를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/system/overview",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestSystemMetrics(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/system/metrics"""

    async def test_get_system_metrics(self) -> None:
        """시스템 메트릭을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/system/metrics",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestSchedulerStatus(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/scheduler/status"""

    async def test_get_scheduler_status(self) -> None:
        """스케줄러 상태를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/scheduler/status",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)
