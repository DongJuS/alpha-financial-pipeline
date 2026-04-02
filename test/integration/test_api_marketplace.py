"""
test/integration/test_api_marketplace.py — Marketplace API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내 마켓플레이스 엔드포인트를 검증합니다.

테스트 대상:
  - GET  /api/v1/marketplace/stocks
  - GET  /api/v1/marketplace/sectors
  - GET  /api/v1/marketplace/sectors/heatmap
  - GET  /api/v1/marketplace/themes
  - GET  /api/v1/marketplace/macro
  - GET  /api/v1/marketplace/etf
  - GET  /api/v1/marketplace/search?q=삼성
  - GET  /api/v1/marketplace/watchlist
  - GET  /api/v1/marketplace/rankings/volume
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
class TestMarketplaceStocks(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/stocks"""

    async def test_get_stocks(self) -> None:
        """종목 마스터 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/stocks",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)
        self.assertIn("page", body["meta"])
        self.assertIn("per_page", body["meta"])
        self.assertIn("total", body["meta"])

    async def test_get_stocks_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/marketplace/stocks")

        self.assertEqual(resp.status_code, 401)


@pytest.mark.integration
class TestMarketplaceSectors(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/sectors"""

    async def test_get_sectors(self) -> None:
        """섹터 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/sectors",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)


@pytest.mark.integration
class TestMarketplaceSectorsHeatmap(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/sectors/heatmap"""

    async def test_get_sector_heatmap(self) -> None:
        """섹터별 히트맵 데이터를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/sectors/heatmap",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)

    async def test_heatmap_items_have_required_fields(self) -> None:
        """히트맵 항목에는 필수 필드가 포함되어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/sectors/heatmap",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for item in body:
            self.assertIn("sector", item)
            self.assertIn("stock_count", item)
            self.assertIn("avg_change_pct", item)


@pytest.mark.integration
class TestMarketplaceThemes(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/themes"""

    async def test_get_themes(self) -> None:
        """테마 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/themes",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)


@pytest.mark.integration
class TestMarketplaceMacro(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/macro"""

    async def test_get_macro(self) -> None:
        """매크로 지표를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/macro",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)

    async def test_macro_has_category_keys(self) -> None:
        """매크로 지표 응답에는 카테고리별 키가 포함되어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/macro",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        expected_categories = {"index", "currency", "commodity", "rate"}
        self.assertTrue(expected_categories.issubset(set(body.keys())))


@pytest.mark.integration
class TestMarketplaceETF(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/etf"""

    async def test_get_etf(self) -> None:
        """ETF 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/etf",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["data"], list)


@pytest.mark.integration
class TestMarketplaceSearch(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/search"""

    async def test_search_stocks(self) -> None:
        """종목 검색이 정상 동작한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/search",
                params={"q": "삼성"},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)

    async def test_search_returns_results(self) -> None:
        """'삼성' 검색 시 결과가 존재해야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/search",
                params={"q": "삼성"},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreater(len(body), 0)


@pytest.mark.integration
class TestMarketplaceWatchlist(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/watchlist"""

    async def test_get_watchlist(self) -> None:
        """관심 종목 목록을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/watchlist",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)

    async def test_watchlist_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/marketplace/watchlist")

        self.assertEqual(resp.status_code, 401)


@pytest.mark.integration
class TestMarketplaceRankingsVolume(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/marketplace/rankings/volume"""

    async def test_get_volume_rankings(self) -> None:
        """거래량 랭킹을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/marketplace/rankings/volume",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("ranking_type", body)
        self.assertEqual(body["ranking_type"], "volume")
        self.assertIn("data", body)
        self.assertIsInstance(body["data"], list)
