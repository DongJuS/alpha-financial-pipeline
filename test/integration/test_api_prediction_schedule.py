"""
test/integration/test_api_prediction_schedule.py — prediction_schedule API 통합 테스트

FastAPI TestClient 로 prediction_schedule 엔드포인트를 격리 테스트한다.
DB 쿼리를 mock 하여 실제 DB 없이 동작.

테스트 대상:
  - GET  /api/v1/scheduler/prediction-schedule — 스케줄 목록 조회
  - PUT  /api/v1/scheduler/prediction-schedule — 스케줄 수정
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user

try:
    from src.api.routers.scheduler import router as scheduler_router
except ImportError:
    pytest.skip("scheduler 라우터를 import 할 수 없습니다", allow_module_level=True)

API_PREFIX = "/api/v1/scheduler"


def _build_client(*, authenticated: bool = True) -> TestClient:
    """테스트용 FastAPI 앱을 생성하고 TestClient 를 반환한다."""
    app = FastAPI()
    app.include_router(scheduler_router, prefix=API_PREFIX)
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
    )
    return TestClient(app, raise_server_exceptions=False)


# ── 테스트 픽스처 데이터 ──────────────────────────────────────────────────────

_SAMPLE_SCHEDULES = [
    {
        "strategy_code": "A",
        "interval_minutes": 30,
        "is_enabled": True,
        "last_run_at": None,
        "updated_at": datetime(2026, 4, 12, 0, 0, 0, tzinfo=timezone.utc),
    },
    {
        "strategy_code": "B",
        "interval_minutes": 60,
        "is_enabled": True,
        "last_run_at": datetime(2026, 4, 12, 8, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 4, 12, 0, 0, 0, tzinfo=timezone.utc),
    },
    {
        "strategy_code": "RL",
        "interval_minutes": 30,
        "is_enabled": False,
        "last_run_at": None,
        "updated_at": datetime(2026, 4, 12, 0, 0, 0, tzinfo=timezone.utc),
    },
]


# ── GET /prediction-schedule ─────────────────────────────────────────────────


class TestGetPredictionSchedule:
    """GET /api/v1/scheduler/prediction-schedule"""

    @patch("src.db.queries.fetch_prediction_schedules", new_callable=AsyncMock)
    def test_get_prediction_schedule(self, mock_fetch: AsyncMock) -> None:
        """스케줄 목록을 정상 조회한다."""
        mock_fetch.return_value = _SAMPLE_SCHEDULES

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/prediction-schedule")
        assert resp.status_code == 200

        body = resp.json()
        items = body.get("schedules", [])
        assert len(items) == 3

        codes = {item["strategy_code"] for item in items}
        assert codes == {"A", "B", "RL"}

    @patch("src.db.queries.fetch_prediction_schedules", new_callable=AsyncMock)
    def test_get_prediction_schedule_empty(self, mock_fetch: AsyncMock) -> None:
        """스케줄이 없으면 빈 목록을 반환한다."""
        mock_fetch.return_value = []

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/prediction-schedule")
        assert resp.status_code == 200

        body = resp.json()
        items = body.get("schedules", [])
        assert len(items) == 0


# ── PUT /prediction-schedule ─────────────────────────────────────────────────


class TestPutPredictionSchedule:
    """PUT /api/v1/scheduler/prediction-schedule"""

    @patch("src.db.queries.upsert_prediction_schedule", new_callable=AsyncMock)
    def test_put_prediction_schedule(self, mock_upsert: AsyncMock) -> None:
        """스케줄을 정상 수정한다."""
        mock_upsert.return_value = {
            "strategy_code": "A",
            "interval_minutes": 60,
            "is_enabled": True,
            "last_run_at": None,
            "updated_at": datetime(2026, 4, 12, 9, 0, 0, tzinfo=timezone.utc).isoformat(),
        }

        client = _build_client()
        resp = client.put(
            f"{API_PREFIX}/prediction-schedule",
            json={
                "strategy_code": "A",
                "interval_minutes": 60,
                "is_enabled": True,
            },
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["strategy_code"] == "A"
        assert body["interval_minutes"] == 60
        mock_upsert.assert_awaited_once()

    def test_put_prediction_schedule_invalid_interval(self) -> None:
        """interval_minutes < 1 이면 422 Validation Error 를 반환한다."""
        client = _build_client()
        resp = client.put(
            f"{API_PREFIX}/prediction-schedule",
            json={
                "strategy_code": "A",
                "interval_minutes": 0,
                "is_enabled": True,
            },
        )
        assert resp.status_code == 422

    def test_put_prediction_schedule_negative_interval(self) -> None:
        """interval_minutes 가 음수이면 422 를 반환한다."""
        client = _build_client()
        resp = client.put(
            f"{API_PREFIX}/prediction-schedule",
            json={
                "strategy_code": "B",
                "interval_minutes": -10,
                "is_enabled": True,
            },
        )
        assert resp.status_code == 422
