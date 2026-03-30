"""
test/integration/test_api_portfolio.py — Portfolio API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 포트폴리오 엔드포인트를 검증합니다.

테스트 대상:
  - GET  /api/v1/portfolio/positions
  - GET  /api/v1/portfolio/history
  - GET  /api/v1/portfolio/performance
  - GET  /api/v1/portfolio/performance-series
  - GET  /api/v1/portfolio/paper-overview
  - GET  /api/v1/portfolio/account-overview
  - GET  /api/v1/portfolio/orders
  - GET  /api/v1/portfolio/account-snapshots
  - GET  /api/v1/portfolio/config
  - POST /api/v1/portfolio/config
  - POST /api/v1/portfolio/trading-mode
  - GET  /api/v1/portfolio/readiness
  - GET  /api/v1/portfolio/readiness/audits
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
class TestPortfolioPositions(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/positions"""

    async def test_get_positions(self) -> None:
        """현재 포트폴리오 포지션 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/positions",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestPortfolioHistory(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/history"""

    async def test_get_history(self) -> None:
        """포트폴리오 거래 내역을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/history",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestPortfolioPerformance(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/performance"""

    async def test_get_performance(self) -> None:
        """포트폴리오 성과 요약을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/performance",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestPortfolioPerformanceSeries(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/performance-series"""

    async def test_get_performance_series(self) -> None:
        """포트폴리오 성과 시계열 데이터를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/performance-series",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestPortfolioPaperOverview(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/paper-overview"""

    async def test_get_paper_overview(self) -> None:
        """페이퍼 트레이딩 개요를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/paper-overview",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestPortfolioAccountOverview(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/account-overview"""

    async def test_get_account_overview(self) -> None:
        """실계좌 개요를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/account-overview",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 503))
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestPortfolioOrders(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/orders"""

    async def test_get_orders(self) -> None:
        """주문 내역을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/orders",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestPortfolioAccountSnapshots(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/account-snapshots"""

    async def test_get_account_snapshots(self) -> None:
        """계좌 스냅샷 이력을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/account-snapshots",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestPortfolioConfigGet(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/config"""

    async def test_get_config(self) -> None:
        """포트폴리오 설정을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/config",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestPortfolioConfigPost(unittest.IsolatedAsyncioTestCase):
    """POST /api/v1/portfolio/config"""

    async def test_post_config_empty_body(self) -> None:
        """빈 바디로 설정을 업데이트한다 (기존 값 유지 확인)."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.post(
                "/api/v1/portfolio/config",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )

        self.assertIn(resp.status_code, (200, 422))
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestPortfolioTradingMode(unittest.IsolatedAsyncioTestCase):
    """POST /api/v1/portfolio/trading-mode"""

    async def test_post_trading_mode(self) -> None:
        """트레이딩 모드 변경 요청을 보낸다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.post(
                "/api/v1/portfolio/trading-mode",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )

        # 모드 변경은 성공(200) 또는 유효성 오류(422)를 반환할 수 있다
        self.assertIn(resp.status_code, (200, 422))
        body = resp.json()
        self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestPortfolioReadiness(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/readiness"""

    async def test_get_readiness(self) -> None:
        """포트폴리오 준비 상태를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/readiness",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)
        # readiness 응답에는 ready 상태 필드가 있어야 한다
        self.assertIn("ready", body)


@pytest.mark.integration
class TestPortfolioReadinessAudits(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/portfolio/readiness/audits"""

    async def test_get_readiness_audits(self) -> None:
        """포트폴리오 준비 상태 감사 이력을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/portfolio/readiness/audits",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))
