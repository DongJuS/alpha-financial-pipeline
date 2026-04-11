"""
test/integration/test_api_strategy.py — Strategy API 통합 테스트

FastAPI TestClient로 전략 라우터를 격리 테스트한다.
DB/Redis는 mock으로 대체.

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

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import strategy as strategy_module
from src.api.routers.strategy import router as strategy_router

API_PREFIX = "/api/v1/strategy"

_PATCH_PREFIX = "src.api.routers.strategy"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(strategy_router, prefix=API_PREFIX)
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
        jwt_secret="test-secret",
        strategy_blend_ratio=0.5,
    )
    return TestClient(app, raise_server_exceptions=False)


class TestStrategyASignals:
    """GET /api/v1/strategy/a/signals"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_strategy_a_signals(self, mock_fetch: AsyncMock) -> None:
        """Strategy A 시그널을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/a/signals")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "signals" in body


class TestStrategyATournament:
    """GET /api/v1/strategy/a/tournament"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_strategy_a_tournament(self, mock_fetch: AsyncMock) -> None:
        """Strategy A 토너먼트 결과를 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/a/tournament")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "rankings" in body


class TestStrategyBSignals:
    """GET /api/v1/strategy/b/signals"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_strategy_b_signals(self, mock_fetch: AsyncMock) -> None:
        """Strategy B 시그널을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/b/signals")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "signals" in body


class TestStrategyBDebates:
    """GET /api/v1/strategy/b/debates"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_strategy_b_debates(self, mock_fetch: AsyncMock) -> None:
        """Strategy B 토론 기록을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/b/debates")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "items" in body


class TestStrategyCombined:
    """GET /api/v1/strategy/combined"""

    @patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_combined_strategy(
        self, mock_fetch: AsyncMock, mock_redis_fn: AsyncMock
    ) -> None:
        """통합 전략 시그널을 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.set.return_value = True
        mock_redis_fn.return_value = redis_mock

        with patch(f"{_PATCH_PREFIX}.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(strategy_blend_ratio=0.5)
            client = _build_client()
            resp = client.get(f"{API_PREFIX}/combined")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "blend_ratio" in body
        assert "signals" in body


class TestStrategyPromotionStatus:
    """GET /api/v1/strategy/promotion-status"""

    @patch(f"{_PATCH_PREFIX}.StrategyPromoter")
    def test_get_promotion_status(self, mock_promoter_cls: MagicMock) -> None:
        """전략 프로모션 상태를 조회한다."""
        mock_instance = MagicMock()
        mock_instance.get_all_strategy_status = AsyncMock(return_value=[
            {
                "strategy_id": "A",
                "active_modes": ["virtual"],
                "promotion_readiness": {"ready": False},
            },
        ])
        mock_promoter_cls.return_value = mock_instance

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/promotion-status")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)


class TestStrategyPromotionReadiness:
    """GET /api/v1/strategy/{strategy_id}/promotion-readiness"""

    @patch(f"{_PATCH_PREFIX}.StrategyPromoter")
    def test_get_promotion_readiness_for_strategy_a(
        self, mock_promoter_cls: MagicMock
    ) -> None:
        """Strategy A의 프로모션 준비 상태를 조회한다."""
        mock_result = SimpleNamespace(
            strategy_id="A",
            from_mode="virtual",
            to_mode="paper",
            ready=False,
            criteria={"min_trades": 50},
            actual={"trades": 10},
            failures=["insufficient_trades"],
            message="조건 미달",
        )
        mock_instance = MagicMock()
        mock_instance.evaluate_promotion_readiness = AsyncMock(return_value=mock_result)
        mock_promoter_cls.return_value = mock_instance

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/A/promotion-readiness")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["strategy_id"] == "A"
