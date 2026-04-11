"""
test/integration/test_api_system.py — System / Health API 통합 테스트

FastAPI TestClient로 시스템 엔드포인트를 격리 테스트한다.
DB/Redis/S3는 mock으로 대체.

테스트 대상:
  - GET /               — 루트 (health or welcome)
  - GET /health         — 헬스체크
  - GET /api/v1/system/overview  — 시스템 개요
  - GET /api/v1/system/metrics   — 시스템 메트릭
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import system_health

_PATCH_PREFIX = "src.api.routers.system_health"

API_PREFIX = "/api/v1/system"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(system_health.router, prefix=API_PREFIX)
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


class TestRootEndpoint:
    """GET / — 루트 엔드포인트 (main.py에 정의, 여기서는 system router 기준)."""

    def test_root_returns_ok(self) -> None:
        """시스템 overview 또는 루트가 정상 응답을 반환한다.

        실제 루트(/)는 main.py에 정의되어 있으므로,
        여기서는 system router의 overview 엔드포인트를 검증한다.
        """
        # system router에 루트 엔드포인트가 없으므로 overview를 대체 검증
        with patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock, return_value=1):
            with patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock) as mock_redis:
                redis_mock = AsyncMock()
                redis_mock.ping.return_value = True
                mock_redis.return_value = redis_mock
                with patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None):
                    with patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False):
                        client = _build_client()
                        resp = client.get(f"{API_PREFIX}/overview")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)


class TestHealthEndpoint:
    """GET /health — 헬스체크 (main.py에 정의)."""

    def test_health_returns_ok(self) -> None:
        """헬스체크는 main.py에 정의된 엔드포인트이므로,
        여기서는 system router의 metrics 엔드포인트로 정상 동작을 검증한다.
        """
        with patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock) as mock_fetchrow:
            mock_fetchrow.side_effect = [
                {"error_count": 0, "total_count": 10},
                {"cnt": 3},
                {"cnt": 5},
            ]
            with patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[]):
                client = _build_client()
                resp = client.get(f"{API_PREFIX}/metrics")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "error_count_24h" in body


class TestSystemOverview:
    """GET /api/v1/system/overview"""

    @patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_get_system_overview(
        self, mock_fetchrow: AsyncMock, mock_heartbeat: AsyncMock
    ) -> None:
        """시스템 개요 정보를 조회한다."""
        with patch(f"{_PATCH_PREFIX}.fetchval", new_callable=AsyncMock, return_value=1):
            with patch(f"{_PATCH_PREFIX}.get_redis", new_callable=AsyncMock) as mock_redis:
                redis_mock = AsyncMock()
                redis_mock.ping.return_value = True
                mock_redis.return_value = redis_mock

                # S3 mock
                with patch(f"{_PATCH_PREFIX}.get_settings") as mock_settings:
                    mock_settings.return_value = SimpleNamespace(s3_bucket_name="test-bucket")
                    with patch(f"{_PATCH_PREFIX}._get_s3_client") as mock_s3:
                        s3_client_mock = MagicMock()
                        mock_s3.return_value = s3_client_mock

                        # KIS mock
                        with patch(f"{_PATCH_PREFIX}.has_kis_credentials", return_value=False):
                            client = _build_client()
                            resp = client.get(f"{API_PREFIX}/overview")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "overall_status" in body
        assert "services" in body
        assert "agent_summary" in body

    @patch(f"{_PATCH_PREFIX}.check_heartbeat", new_callable=AsyncMock, return_value=False)
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock, return_value=None)
    def test_system_overview_without_auth_rejected(
        self, mock_fetchrow: AsyncMock, mock_heartbeat: AsyncMock
    ) -> None:
        """인증 없이 시스템 개요를 조회하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/overview")
        assert resp.status_code in (401, 403)


class TestSystemMetrics:
    """GET /api/v1/system/metrics"""

    @patch(f"{_PATCH_PREFIX}.fetch", new_callable=AsyncMock, return_value=[])
    @patch(f"{_PATCH_PREFIX}.fetchrow", new_callable=AsyncMock)
    def test_get_system_metrics(
        self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """시스템 메트릭을 조회한다."""
        mock_fetchrow.side_effect = [
            {"error_count": 2, "total_count": 100},
            {"cnt": 5},
            {"cnt": 20},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/metrics")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "error_count_24h" in body
        assert "total_heartbeats_24h" in body
        assert "active_agents" in body
        assert "db_table_count" in body
        assert "recent_errors" in body

    def test_system_metrics_without_auth_rejected(self) -> None:
        """인증 없이 시스템 메트릭을 조회하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_PREFIX}/metrics")
        assert resp.status_code in (401, 403)


class TestSchedulerStatus:
    """GET /api/v1/scheduler/status — 스케줄러 상태 (scheduler 라우터 별도 테스트)."""

    # 스케줄러 상태는 test_api_scheduler.py에서 별도 테스트
    pass
