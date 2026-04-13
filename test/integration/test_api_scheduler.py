"""
test/integration/test_api_scheduler.py — Scheduler API 통합 테스트

FastAPI TestClient로 scheduler 라우터를 격리 테스트한다.
스케줄러/Redis 없이 mock으로 동작.

테스트 대상:
  - GET /api/v1/scheduler/status — 스케줄러 상태 조회
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers.scheduler import router as scheduler_router

API_PREFIX = "/api/v1/scheduler"
_PATCH_PREFIX = "src.api.routers.scheduler"


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(scheduler_router, prefix=API_PREFIX)
    return TestClient(app, raise_server_exceptions=False)


# ── GET /status ─────────────────────────────────────────────────────────


class TestSchedulerStatusEndpoint:
    """GET /api/v1/scheduler/status"""

    @patch(f"{_PATCH_PREFIX}.get_scheduler_status")
    def test_status_scheduler_not_running(self, mock_status: MagicMock) -> None:
        """스케줄러가 실행 중이 아니면 running=False를 반환한다."""
        mock_status.return_value = {"running": False, "jobs": []}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200

        body = resp.json()
        assert body["running"] is False
        assert body["job_count"] == 0
        assert body["jobs"] == []

    @patch(f"{_PATCH_PREFIX}._get_job_history", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_scheduler_status")
    def test_status_scheduler_running_with_jobs(
        self, mock_status: MagicMock, mock_history: AsyncMock
    ) -> None:
        """스케줄러가 실행 중이면 잡 목록과 이력을 반환한다."""
        mock_status.return_value = {
            "running": True,
            "job_count": 2,
            "jobs": [
                {
                    "id": "collector_daily",
                    "name": "CollectorAgent",
                    "next_run": "2025-07-01T08:30:00+09:00",
                    "trigger": "cron[hour='8', minute='30']",
                },
                {
                    "id": "rl_retrain",
                    "name": "RL Retrain",
                    "next_run": "2025-07-01T16:00:00+09:00",
                    "trigger": "cron[hour='16', minute='0']",
                },
            ],
        }
        mock_history.return_value = [
            {"started_at": "2025-06-30T08:30:00Z", "status": "success", "duration": 45.2},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200

        body = resp.json()
        assert body["running"] is True
        assert body["job_count"] == 2
        assert len(body["jobs"]) == 2
        assert body["jobs"][0]["id"] == "collector_daily"
        assert body["jobs"][0]["name"] == "CollectorAgent"
        assert body["jobs"][0]["next_run"] is not None
        assert body["jobs"][0]["trigger"] != ""

    @patch(f"{_PATCH_PREFIX}._get_job_history", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_scheduler_status")
    def test_status_jobs_have_recent_history(
        self, mock_status: MagicMock, mock_history: AsyncMock
    ) -> None:
        """각 잡에 recent_history 배열이 포함된다."""
        mock_status.return_value = {
            "running": True,
            "job_count": 1,
            "jobs": [
                {
                    "id": "test_job",
                    "name": "Test Job",
                    "next_run": None,
                    "trigger": "interval[0:00:30]",
                },
            ],
        }
        mock_history.return_value = [
            {"started_at": "2025-06-30T10:00:00Z", "status": "success"},
            {"started_at": "2025-06-30T10:00:30Z", "status": "failed"},
        ]

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["jobs"][0]["recent_history"]) == 2

    @patch(f"{_PATCH_PREFIX}._get_job_history", new_callable=AsyncMock)
    @patch(f"{_PATCH_PREFIX}.get_scheduler_status")
    def test_status_job_history_failure_is_graceful(
        self, mock_status: MagicMock, mock_history: AsyncMock
    ) -> None:
        """Redis 이력 조회 실패 시에도 빈 배열로 응답한다."""
        mock_status.return_value = {
            "running": True,
            "job_count": 1,
            "jobs": [
                {
                    "id": "test_job",
                    "name": "Test Job",
                    "next_run": None,
                    "trigger": "interval",
                },
            ],
        }
        mock_history.return_value = []  # 실패 시 빈 배열

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200

        body = resp.json()
        assert body["jobs"][0]["recent_history"] == []

    @patch(f"{_PATCH_PREFIX}.get_scheduler_status")
    def test_status_response_model_structure(self, mock_status: MagicMock) -> None:
        """응답이 SchedulerStatusResponse 모델 구조를 따른다."""
        mock_status.return_value = {"running": False, "jobs": []}

        client = _build_client()
        resp = client.get(f"{API_PREFIX}/status")
        assert resp.status_code == 200

        body = resp.json()
        assert "running" in body
        assert "job_count" in body
        assert "jobs" in body
        assert isinstance(body["running"], bool)
        assert isinstance(body["job_count"], int)
        assert isinstance(body["jobs"], list)
