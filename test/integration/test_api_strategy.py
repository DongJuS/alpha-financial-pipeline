"""
test/integration/test_api_strategy.py — Strategy API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 전략 엔드포인트를 검증합니다.

테스트 대상:
  - GET /api/v1/strategy/a/signals
  - GET /api/v1/strategy/a/tournament
  - GET /api/v1/strategy/b/signals
  - GET /api/v1/strategy/b/debates
  - GET /api/v1/strategy/combined
  - GET /api/v1/strategy/promotion-status
  - GET /api/v1/strategy/{strategy_id}/promotion-readiness
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
class TestStrategyASignals(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/a/signals"""

    async def test_get_strategy_a_signals(self) -> None:
        """Strategy A 시그널을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/a/signals",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestStrategyATournament(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/a/tournament"""

    async def test_get_strategy_a_tournament(self) -> None:
        """Strategy A 토너먼트 결과를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/a/tournament",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestStrategyBSignals(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/b/signals"""

    async def test_get_strategy_b_signals(self) -> None:
        """Strategy B 시그널을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/b/signals",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestStrategyBDebates(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/b/debates"""

    async def test_get_strategy_b_debates(self) -> None:
        """Strategy B 토론 기록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/b/debates",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestStrategyCombined(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/combined"""

    async def test_get_combined_strategy(self) -> None:
        """통합 전략 시그널을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/combined",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestStrategyPromotionStatus(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/promotion-status"""

    async def test_get_promotion_status(self) -> None:
        """전략 프로모션 상태를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/promotion-status",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestStrategyPromotionReadiness(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/strategy/{strategy_id}/promotion-readiness"""

    async def test_get_promotion_readiness_for_strategy_a(self) -> None:
        """Strategy A의 프로모션 준비 상태를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/strategy/A/promotion-readiness",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)
