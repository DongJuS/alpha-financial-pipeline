"""
test/integration/test_api_market.py — Market API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 시장 데이터 엔드포인트를 검증합니다.

테스트 대상:
  - GET  /api/v1/market/tickers
  - GET  /api/v1/market/ohlcv/005930
  - GET  /api/v1/market/opensource/ohlcv/005930
  - GET  /api/v1/market/quote/005930
  - GET  /api/v1/market/realtime/005930
  - GET  /api/v1/market/index
  - POST /api/v1/market/collect
"""

from __future__ import annotations

import os
import unittest

import httpx
import pytest

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:18000")
LOGIN_EMAIL = "admin@alpha-trading.com"
LOGIN_PASSWORD = "admin123"

TEST_TICKER = "005930"


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
class TestMarketTickers(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/market/tickers"""

    async def test_get_tickers(self) -> None:
        """종목 티커 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/market/tickers",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestMarketOhlcv(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/market/ohlcv/{ticker}"""

    async def test_get_ohlcv(self) -> None:
        """특정 종목의 OHLCV 데이터를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                f"/api/v1/market/ohlcv/{TEST_TICKER}",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestMarketOpensourceOhlcv(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/market/opensource/ohlcv/{ticker}"""

    async def test_get_opensource_ohlcv(self) -> None:
        """오픈소스 소스를 통한 OHLCV 데이터를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.get(
                f"/api/v1/market/opensource/ohlcv/{TEST_TICKER}",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 202, 503))
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestMarketQuote(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/market/quote/{ticker}"""

    async def test_get_quote(self) -> None:
        """특정 종목의 실시간 호가를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                f"/api/v1/market/quote/{TEST_TICKER}",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 503))
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestMarketRealtime(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/market/realtime/{ticker}"""

    async def test_get_realtime(self) -> None:
        """특정 종목의 실시간 시세를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                f"/api/v1/market/realtime/{TEST_TICKER}",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 503))
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, dict)


@pytest.mark.integration
class TestMarketIndex(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/market/index"""

    async def test_get_market_index(self) -> None:
        """시장 지수 데이터를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/market/index",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 503))
        if resp.status_code == 200:
            body = resp.json()
            self.assertIsInstance(body, (list, dict))


@pytest.mark.integration
class TestMarketCollect(unittest.IsolatedAsyncioTestCase):
    """POST /api/v1/market/collect"""

    async def test_trigger_market_collect(self) -> None:
        """시장 데이터 수집을 트리거한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            resp = await client.post(
                "/api/v1/market/collect",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertIn(resp.status_code, (200, 202, 409, 422))  # 422 = body required
        if resp.status_code in (200, 202):
            body = resp.json()
            self.assertIsInstance(body, dict)
