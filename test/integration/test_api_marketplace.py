"""
test/integration/test_api_marketplace.py — Marketplace API 통합 테스트

FastAPI TestClient로 마켓플레이스 라우터를 격리 테스트한다.
DB/Redis는 mock으로 대체.

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

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import marketplace as mp_module
from src.api.routers.marketplace import router as mp_router

API_PREFIX = "/api/v1/marketplace"

_PATCH_PREFIX = "src.api.routers.marketplace"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(mp_router, prefix=API_PREFIX)
    if authenticated:
        async def mock_user():
            return {
                "sub": str(uuid4()),
                "email": "test@test.com",
                "name": "Tester",
                "is_admin": True,
            }
        app.dependency_overrides[get_current_user] = mock_user
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret"
    )
    return TestClient(app, raise_server_exceptions=False)


# ── GET /stocks ─────────────────────────────────────────────────────────────


class TestMarketplaceStocks:
    """GET /api/v1/marketplace/stocks"""

    @patch(f"{_PATCH_PREFIX}.count_krx_stock_master", new_callable=AsyncMock, return_value=2)
    @patch(f"{_PATCH_PREFIX}.list_krx_stock_master", new_callable=AsyncMock)
    def test_get_stocks(
        self, mock_list: AsyncMock, mock_count: AsyncMock
    ) -> None:
        """종목 마스터 목록을 조회한다."""
        mock_list.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
            {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI"},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/stocks")
        assert resp.status_code == 200

        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)
        assert body["meta"]["page"] == 1
        assert body["meta"]["per_page"] == 50
        assert body["meta"]["total"] == 2

    def test_get_stocks_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/stocks")
        assert resp.status_code in (401, 403)


# ── GET /sectors ────────────────────────────────────────────────────────────


class TestMarketplaceSectors:
    """GET /api/v1/marketplace/sectors"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_sectors", new_callable=AsyncMock)
    def test_get_sectors(
        self, mock_get_sectors: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """섹터 목록을 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        mock_get_sectors.return_value = [
            {"sector": "전기전자", "stock_count": 50, "total_market_cap": 1000000},
            {"sector": "화학", "stock_count": 30, "total_market_cap": 500000},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/sectors")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2


# ── GET /sectors/heatmap ────────────────────────────────────────────────────


class TestMarketplaceSectorsHeatmap:
    """GET /api/v1/marketplace/sectors/heatmap"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    def test_get_sector_heatmap(self, mock_redis: AsyncMock) -> None:
        """섹터별 히트맵 데이터를 조회한다 (캐시 hit)."""
        cached_data = [
            {"sector": "전기전자", "stock_count": 50, "avg_change_pct": 1.2, "total_market_cap": 1000000, "total_volume": 5000000},
            {"sector": "화학", "stock_count": 30, "avg_change_pct": -0.5, "total_market_cap": 500000, "total_volume": 2000000},
        ]
        redis_mock = AsyncMock()
        redis_mock.get.return_value = json.dumps(cached_data)
        mock_redis.return_value = redis_mock

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/sectors/heatmap")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    def test_heatmap_items_have_required_fields(self, mock_redis: AsyncMock) -> None:
        """히트맵 항목에는 필수 필드가 포함되어야 한다."""
        cached_data = [
            {"sector": "전기전자", "stock_count": 50, "avg_change_pct": 1.2, "total_market_cap": 1000000, "total_volume": 5000000},
        ]
        redis_mock = AsyncMock()
        redis_mock.get.return_value = json.dumps(cached_data)
        mock_redis.return_value = redis_mock

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/sectors/heatmap")
        assert resp.status_code == 200
        body = resp.json()
        for item in body:
            assert "sector" in item
            assert "stock_count" in item
            assert "avg_change_pct" in item


# ── GET /themes ─────────────────────────────────────────────────────────────


class TestMarketplaceThemes:
    """GET /api/v1/marketplace/themes"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_themes", new_callable=AsyncMock)
    def test_get_themes(
        self, mock_get_themes: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """테마 목록을 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        mock_get_themes.return_value = [
            {"theme_slug": "ai", "theme_name": "AI/인공지능", "stock_count": 20, "leader_count": 5},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/themes")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)


# ── GET /macro ──────────────────────────────────────────────────────────────


class TestMarketplaceMacro:
    """GET /api/v1/marketplace/macro"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_macro_indicators", new_callable=AsyncMock)
    def test_get_macro(
        self, mock_macro: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """매크로 지표를 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        mock_macro.return_value = [{"symbol": "US500", "value": 5100.0}]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/macro")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_macro_indicators", new_callable=AsyncMock)
    def test_macro_has_category_keys(
        self, mock_macro: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """매크로 지표 응답에는 카테고리별 키가 포함되어야 한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        mock_macro.return_value = []

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/macro")
        assert resp.status_code == 200
        body = resp.json()
        expected_categories = {"index", "currency", "commodity", "rate"}
        assert expected_categories.issubset(set(body.keys()))


# ── GET /etf ────────────────────────────────────────────────────────────────


class TestMarketplaceETF:
    """GET /api/v1/marketplace/etf"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.count_krx_stock_master", new_callable=AsyncMock, return_value=1)
    @patch(f"{_PATCH_PREFIX}.list_krx_stock_master", new_callable=AsyncMock)
    def test_get_etf(
        self, mock_list: AsyncMock, mock_count: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """ETF 목록을 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        mock_list.return_value = [
            {"ticker": "069500", "name": "KODEX 200", "market": "KOSPI", "is_etf": True},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/etf")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert isinstance(body["data"], list)


# ── GET /search ─────────────────────────────────────────────────────────────


class TestMarketplaceSearch:
    """GET /api/v1/marketplace/search"""

    @patch(f"{_PATCH_PREFIX}.search_stocks", new_callable=AsyncMock)
    def test_search_stocks(self, mock_search: AsyncMock) -> None:
        """종목 검색이 정상 동작한다."""
        mock_search.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/search", params={"q": "삼성"})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @patch(f"{_PATCH_PREFIX}.search_stocks", new_callable=AsyncMock)
    def test_search_returns_results(self, mock_search: AsyncMock) -> None:
        """'삼성' 검색 시 결과가 존재해야 한다."""
        mock_search.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
            {"ticker": "005935", "name": "삼성전자우", "market": "KOSPI"},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/search", params={"q": "삼성"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) > 0


# ── GET /watchlist ──────────────────────────────────────────────────────────


class TestMarketplaceWatchlist:
    """GET /api/v1/marketplace/watchlist"""

    @patch(f"{_PATCH_PREFIX}.get_watchlist", new_callable=AsyncMock, return_value=[])
    def test_get_watchlist(self, mock_watchlist: AsyncMock) -> None:
        """관심 종목 목록을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/watchlist")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_watchlist_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/watchlist")
        assert resp.status_code in (401, 403)


# ── GET /rankings/volume ───────────────────────────────────────────────────


class TestMarketplaceRankingsVolume:
    """GET /api/v1/marketplace/rankings/volume"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_daily_rankings", new_callable=AsyncMock)
    def test_get_volume_rankings(
        self, mock_rankings: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """거래량 랭킹을 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        mock_rankings.return_value = [
            {"rank": 1, "ticker": "005930", "name": "삼성전자", "value": 5000000},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/rankings/volume")
        assert resp.status_code == 200
        body = resp.json()
        assert "ranking_type" in body
        assert body["ranking_type"] == "volume"
        assert "data" in body
        assert isinstance(body["data"], list)
