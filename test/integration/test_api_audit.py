"""
test/integration/test_api_audit.py — Audit API 통합 테스트

FastAPI TestClient로 audit 라우터를 격리 테스트한다.
DB는 mock으로 대체.

테스트 대상:
  - GET /api/v1/audit/trail   — 감사 추적 로그 조회
  - GET /api/v1/audit/summary — 감사 요약 통계
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers.audit import router as audit_router

API_PREFIX = "/api/v1/audit"

_PATCH_PREFIX = "src.api.routers.audit"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(audit_router, prefix=API_PREFIX)
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


# ── GET /trail ──────────────────────────────────────────────────────────


class TestAuditTrailEndpoint:
    """GET /api/v1/audit/trail"""

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_trail_empty(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """빈 데이터 → data 빈 배열, total 0."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail")
        assert resp.status_code == 200

        body = resp.json()
        assert body["data"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["limit"] == 30

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_trail_with_data(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """데이터가 있으면 AuditTrailItem 목록을 반환한다."""
        mock_fetch.return_value = [
            {
                "event_type": "trade",
                "event_time": "2025-01-01T10:00:00Z",
                "agent_id": "strategy_a",
                "description": "BUY Samsung x10 @ 65000",
                "result": "executed",
            },
        ]
        mock_fetchrow.return_value = {"cnt": 1}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["event_type"] == "trade"
        assert body["data"][0]["result"] == "executed"
        assert body["total"] == 1

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_trail_pagination(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """page, limit 파라미터가 올바르게 전달된다."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 50}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail?page=2&limit=10")
        assert resp.status_code == 200

        body = resp.json()
        assert body["page"] == 2
        assert body["limit"] == 10
        assert body["total"] == 50

        # LIMIT, OFFSET 검증 (params 끝 2개)
        fetch_args = mock_fetch.call_args[0]
        assert fetch_args[-2] == 10  # limit
        assert fetch_args[-1] == 10  # offset = (2-1)*10

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_trail_event_type_filter(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """event_type 필터가 쿼리에 반영된다."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail?event_type=trade")
        assert resp.status_code == 200

        # fetch에 event_type 파라미터가 전달됨
        fetch_sql = mock_fetch.call_args[0][0]
        assert "event_type = $1" in fetch_sql

    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    def test_trail_date_filters(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """date_from, date_to 필터가 쿼리에 반영된다."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail?date_from=2025-01-01&date_to=2025-06-30")
        assert resp.status_code == 200

        fetch_sql = mock_fetch.call_args[0][0]
        assert "event_time >=" in fetch_sql
        assert "event_time <=" in fetch_sql

    def test_trail_page_min_validation(self) -> None:
        """page < 1 이면 422를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail?page=0")
        assert resp.status_code == 422

    def test_trail_limit_max_validation(self) -> None:
        """limit > 100 이면 422를 반환한다."""
        client = _build_client()
        resp = client.get(f"{API_PREFIX}/trail?limit=200")
        assert resp.status_code == 422

    def test_trail_requires_authentication(self) -> None:
        """인증 없이 호출하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/trail")
        assert resp.status_code in (401, 403)


# ── GET /summary ────────────────────────────────────────────────────────


class TestAuditSummaryEndpoint:
    """GET /api/v1/audit/summary"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_summary_returns_stats(self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock) -> None:
        """감사 요약이 총 이벤트, 통과율, 유형별 분류를 반환한다."""
        mock_fetchrow.return_value = {"total_events": 100, "pass_rate": 0.95}
        mock_fetch.return_value = [
            {"event_type": "trade", "cnt": 50},
            {"event_type": "operational_audit", "cnt": 30},
            {"event_type": "notification", "cnt": 20},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/summary")
        assert resp.status_code == 200

        body = resp.json()
        assert body["total_events"] == 100
        assert body["pass_rate"] == 0.95
        assert body["by_type"]["trade"] == 50
        assert body["by_type"]["operational_audit"] == 30
        assert body["by_type"]["notification"] == 20

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_summary_empty_data(self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock) -> None:
        """데이터가 없으면 total_events 0을 반환한다."""
        mock_fetchrow.return_value = {"total_events": 0, "pass_rate": None}
        mock_fetch.return_value = []

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/summary")
        assert resp.status_code == 200

        body = resp.json()
        assert body["total_events"] == 0
        assert body["pass_rate"] is None
        assert body["by_type"] == {}

    def test_summary_requires_authentication(self) -> None:
        """인증 없이 호출하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/summary")
        assert resp.status_code in (401, 403)
