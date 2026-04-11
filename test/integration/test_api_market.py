"""
test/integration/test_api_market.py — Market API 통합 테스트

FastAPI TestClient로 시장 데이터 라우터를 격리 테스트한다.
DB/Redis는 mock으로 대체.

테스트 대상:
  - GET  /api/v1/market/ohlcv/005930
  - GET  /api/v1/market/opensource/ohlcv/005930
  - GET  /api/v1/market/quote/005930
  - GET  /api/v1/market/realtime/005930
  - GET  /api/v1/market/index
  - POST /api/v1/market/collect
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
from src.api.routers import market as market_module
from src.api.routers.market import router as market_router

API_PREFIX = "/api/v1/market"

_PATCH_PREFIX = "src.api.routers.market"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(market_router, prefix=API_PREFIX)
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


class TestMarketOhlcv:
    """GET /api/v1/market/ohlcv/{ticker}"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_get_ohlcv(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """특정 종목의 OHLCV 데이터를 조회한다."""
        # raw_code lookup
        mock_fetchrow.side_effect = [
            {"instrument_id": "005930.KS"},  # instrument lookup
            {"name": "삼성전자"},  # name lookup
        ]
        mock_fetch.return_value = [
            {
                "traded_at": "2026-01-10",
                "open": 72000.0, "high": 73000.0, "low": 71500.0,
                "close": 72500.0, "volume": 1000000, "change_pct": 0.5,
            },
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/ohlcv/005930")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["ticker"] == "005930"
        assert body["name"] == "삼성전자"
        assert isinstance(body["data"], list)


class TestMarketOpensourceOhlcv:
    """GET /api/v1/market/opensource/ohlcv/{ticker}"""

    @patch(f"{_PATCH_PREFIX}._fetch_fdr_ohlcv_sync")
    def test_get_opensource_ohlcv(self, mock_fdr: AsyncMock) -> None:
        """오픈소스 소스를 통한 OHLCV 데이터를 조회한다."""
        mock_fdr.return_value = (
            "삼성전자",
            [
                {
                    "traded_at": "2026-01-10",
                    "open": 72000.0, "high": 73000.0, "low": 71500.0,
                    "close": 72500.0, "volume": 1000000, "change_pct": 0.5,
                },
            ],
        )

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/opensource/ohlcv/005930")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["ticker"] == "005930"


class TestMarketQuote:
    """GET /api/v1/market/quote/{ticker}"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    def test_get_quote(self, mock_redis: AsyncMock) -> None:
        """특정 종목의 실시간 호가를 조회한다 (Redis 캐시 hit)."""
        cached = json.dumps({
            "ticker": "005930",
            "name": "삼성전자",
            "current_price": 72500,
            "change_pct": 0.5,
            "volume": 1000000,
            "updated_at": "2026-01-10",
        })
        redis_mock = AsyncMock()
        redis_mock.get.return_value = cached
        mock_redis.return_value = redis_mock

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/quote/005930")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["ticker"] == "005930"


class TestMarketRealtime:
    """GET /api/v1/market/realtime/{ticker}"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_get_realtime(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """특정 종목의 실시간 시세를 조회한다 (DB fallback)."""
        redis_mock = AsyncMock()
        redis_mock.lrange.return_value = []
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock

        mock_fetchrow.return_value = {"instrument_id": "005930.KS"}
        mock_fetch.return_value = [
            {
                "name": "삼성전자",
                "current_price": 72500.0,
                "volume": 1000000,
                "change_pct": 0.5,
                "ts": "2026-01-10T15:30:00+09:00",
            },
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/realtime/005930")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["ticker"] == "005930"


class TestMarketIndex:
    """GET /api/v1/market/index"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    def test_get_market_index(self, mock_redis: AsyncMock) -> None:
        """시장 지수 데이터를 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/index")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "kospi" in body
        assert "kosdaq" in body


class TestMarketCollect:
    """POST /api/v1/market/collect"""

    @patch("src.services.datalake.store_daily_bars", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.upsert_market_data", new_callable=AsyncMock, return_value=5)
    @patch(f"{_PATCH_PREFIX}._collect_fdr_to_db_sync")
    def test_trigger_market_collect(
        self, mock_collect: AsyncMock, mock_upsert: AsyncMock, mock_s3_store: AsyncMock
    ) -> None:
        """시장 데이터 수집을 트리거한다."""
        mock_collect.return_value = ([], ["005930"], [])

        client = _build_client()
        resp = client.post(
            f"{API_PREFIX}/collect",
            json={"tickers": ["005930"], "days": 30},
        )
        assert resp.status_code in (200, 202)
        body = resp.json()
        assert isinstance(body, dict)
