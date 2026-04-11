"""
test/test_api_edge_cases.py — API 에지 케이스 테스트

잘못된 입력, 인증 실패, 404, 경계값 시나리오를 검증한다.
모든 테스트는 외부 서비스 없이 mock으로 동작.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import auth, audit, backtest, feedback, scheduler
from src.api.routers import strategy


# ── 공통 헬퍼 ───────────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    """모든 라우터를 포함한 테스트용 앱을 빌드한다."""
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(feedback.router, prefix="/api/v1/feedback")
    app.include_router(audit.router, prefix="/api/v1/audit")
    app.include_router(backtest.router, prefix="/api/v1/backtest")
    app.include_router(scheduler.router, prefix="/api/v1/scheduler")
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret"
    )
    return app


def _build_authed_app() -> FastAPI:
    """인증이 주입된 테스트용 앱을 빌드한다."""
    app = _build_app()

    async def mock_user():
        return {
            "sub": str(uuid4()),
            "email": "test@test.com",
            "name": "Tester",
            "is_admin": True,
        }

    app.dependency_overrides[get_current_user] = mock_user
    return app


def _make_token(secret: str = "test-secret", expired: bool = False, invalid_sub: bool = False) -> str:
    """테스트용 JWT 토큰을 생성한다."""
    exp = int(time.time()) - 3600 if expired else int(time.time()) + 3600
    payload = {
        "sub": "not-a-uuid" if invalid_sub else str(uuid4()),
        "email": "test@test.com",
        "name": "Tester",
        "is_admin": True,
        "exp": exp,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ── 인증 실패 시나리오 ──────────────────────────────────────────────────


class TestAuthenticationEdgeCases:
    """인증 관련 에지 케이스"""

    def test_no_auth_header_returns_403(self) -> None:
        """Authorization 헤더 없이 보호된 엔드포인트 호출 시 401/403을 반환한다."""
        app = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/audit/trail")
        assert resp.status_code in (401, 403)

    def test_invalid_bearer_format_returns_401(self) -> None:
        """잘못된 Bearer 형식은 401/403을 반환한다."""
        app = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": "InvalidFormat xyz"},
        )
        assert resp.status_code in (401, 403)

    def test_expired_token_returns_401(self) -> None:
        """만료된 토큰은 401을 반환한다."""
        app = _build_app()
        token = _make_token(expired=True)

        # fetchrow mock (DB 조회 방지)
        with patch("src.api.deps.fetchrow", new_callable=AsyncMock):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/audit/trail",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert "만료" in resp.json()["detail"]

    def test_wrong_secret_token_returns_401(self) -> None:
        """잘못된 secret으로 생성된 토큰은 401을 반환한다."""
        app = _build_app()
        token = _make_token(secret="wrong-secret")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_invalid_sub_in_token_returns_401(self) -> None:
        """토큰의 sub 필드가 유효한 UUID가 아니면 401을 반환한다."""
        app = _build_app()
        token = _make_token(invalid_sub=True)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_empty_bearer_token_returns_401(self) -> None:
        """빈 Bearer 토큰은 401/403을 반환한다."""
        app = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code in (401, 403, 422)


# ── 잘못된 입력 시나리오 ────────────────────────────────────────────────


class TestInvalidInputEdgeCases:
    """잘못된 입력에 대한 에지 케이스"""

    def test_feedback_backtest_empty_body_returns_422(self) -> None:
        """빈 JSON 본문으로 backtest 호출 시 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/feedback/backtest", json={})
        assert resp.status_code == 422

    def test_feedback_backtest_negative_capital_returns_422(self) -> None:
        """음수 initial_capital로 backtest 호출 시 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_a", "initial_capital": -1},
        )
        assert resp.status_code == 422

    def test_feedback_backtest_zero_capital_returns_422(self) -> None:
        """0 initial_capital로 backtest 호출 시 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_a", "initial_capital": 0},
        )
        assert resp.status_code == 422

    def test_feedback_accuracy_invalid_days_type(self) -> None:
        """days 파라미터에 문자열을 보내면 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/feedback/accuracy?days=abc")
        assert resp.status_code == 422

    @patch("src.api.routers.backtest.fetchval", new_callable=AsyncMock)
    @patch("src.api.routers.backtest.fetch", new_callable=AsyncMock)
    def test_backtest_runs_invalid_strategy_pattern(
        self, mock_fetch: AsyncMock, mock_fetchval: AsyncMock
    ) -> None:
        """backtest/runs에 잘못된 strategy 패턴을 보내면 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/backtest/runs?strategy=invalid_xyz")
        assert resp.status_code == 422

    @patch("src.api.routers.backtest.fetchrow", new_callable=AsyncMock)
    def test_backtest_runs_invalid_run_id_type(self, mock_fetchrow: AsyncMock) -> None:
        """run_id에 문자열을 보내면 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/backtest/runs/not-a-number")
        assert resp.status_code == 422

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_limit_zero_returns_422(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """limit=0 은 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/audit/trail?limit=0")
        assert resp.status_code == 422


# ── 404 시나리오 ────────────────────────────────────────────────────────


class TestNotFoundEdgeCases:
    """존재하지 않는 리소스에 대한 에지 케이스"""

    @patch("src.api.routers.backtest.fetchrow", new_callable=AsyncMock)
    def test_backtest_nonexistent_run_returns_404(self, mock_fetchrow: AsyncMock) -> None:
        """존재하지 않는 backtest run은 404를 반환한다."""
        mock_fetchrow.return_value = None

        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/backtest/runs/99999")
        assert resp.status_code == 404

    @patch("src.api.routers.backtest.fetchrow", new_callable=AsyncMock)
    def test_backtest_daily_nonexistent_run_returns_404(self, mock_fetchrow: AsyncMock) -> None:
        """존재하지 않는 run의 daily endpoint도 404를 반환한다."""
        mock_fetchrow.return_value = None

        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/backtest/runs/99999/daily")
        assert resp.status_code == 404

    def test_nonexistent_route_returns_404(self) -> None:
        """등록되지 않은 경로는 404를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code == 404


# ── HTTP 메서드 에지 케이스 ─────────────────────────────────────────────


class TestHTTPMethodEdgeCases:
    """잘못된 HTTP 메서드 사용에 대한 에지 케이스"""

    def test_get_on_post_endpoint_returns_405(self) -> None:
        """POST 전용 엔드포인트에 GET 요청 시 405를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/feedback/backtest")
        assert resp.status_code == 405

    def test_post_on_get_endpoint_returns_405(self) -> None:
        """GET 전용 엔드포인트에 POST 요청 시 405를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/feedback/accuracy")
        assert resp.status_code == 405

    def test_delete_not_supported(self) -> None:
        """DELETE 메서드는 지원하지 않는다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/v1/feedback/accuracy")
        assert resp.status_code == 405


# ── Content-Type 에지 케이스 ────────────────────────────────────────────


class TestContentTypeEdgeCases:
    """Content-Type 관련 에지 케이스"""

    def test_post_with_invalid_json_returns_422(self) -> None:
        """유효하지 않은 JSON 본문은 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_post_with_extra_fields_still_works(self) -> None:
        """알 수 없는 추가 필드가 있어도 정상 동작한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={
                "strategy": "strategy_a",
                "unknown_field": "should_be_ignored",
            },
        )
        assert resp.status_code == 200


# ── 경계값 테스트 ──────────────────────────────────────────────────────


class TestBoundaryEdgeCases:
    """경계값에 대한 에지 케이스"""

    def test_accuracy_days_exactly_1(self) -> None:
        """days=1 은 유효하다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/feedback/accuracy?days=1")
        assert resp.status_code == 200

    def test_accuracy_days_exactly_365(self) -> None:
        """days=365 는 유효하다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/feedback/accuracy?days=365")
        assert resp.status_code == 200

    def test_backtest_very_large_capital(self) -> None:
        """아주 큰 initial_capital 도 허용된다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_a", "initial_capital": 999_999_999_999},
        )
        assert resp.status_code == 200
        assert resp.json()["initial_capital"] == 999_999_999_999


# ── 추가 에지 케이스 (Agent 3 보강) ───────────────────────────────────────


class TestPaginationEdgeCases:
    """페이지네이션 관련 에지 케이스"""

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_page_zero_returns_422(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """page=0 은 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/audit/trail?page=0")
        assert resp.status_code == 422

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_negative_page_returns_422(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """page=-1 은 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/audit/trail?page=-1")
        assert resp.status_code == 422

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_negative_limit_returns_422(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """limit=-5 는 422를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/audit/trail?limit=-5")
        assert resp.status_code == 422


class TestBacktestEdgeCases:
    """백테스트 관련 추가 에지 케이스"""

    def test_backtest_invalid_date_format(self) -> None:
        """잘못된 날짜 형식으로 백테스트 요청 시 422 또는 에러를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={
                "strategy": "strategy_a",
                "start_date": "not-a-date",
                "end_date": "also-not-a-date",
            },
        )
        assert resp.status_code in (200, 422)

    def test_backtest_end_before_start(self) -> None:
        """end_date가 start_date보다 앞서는 경우도 안전하게 처리한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={
                "strategy": "strategy_a",
                "start_date": "2026-06-30",
                "end_date": "2026-01-01",
            },
        )
        # 에러 또는 빈 결과 반환 (둘 다 안전한 동작)
        assert resp.status_code in (200, 422)

    def test_backtest_compare_empty_strategies_returns_empty(self) -> None:
        """빈 전략 목록으로 비교 요청 시 빈 결과를 반환한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest/compare",
            json={"strategies": []},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["strategies"] == []

    def test_backtest_compare_single_strategy_returns_one(self) -> None:
        """단일 전략으로 비교 요청 시 해당 전략만 반환된다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/backtest/compare",
            json={"strategies": ["strategy_a"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["strategies"]) == 1
        assert body["strategies"][0]["strategy"] == "strategy_a"


class TestFeedbackCycleEdgeCases:
    """피드백 사이클 관련 에지 케이스"""

    def test_feedback_cycle_unknown_scope_still_runs(self) -> None:
        """알 수 없는 scope 값으로 사이클을 실행해도 정상 동작한다 (빈 결과)."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "unknown_scope_xyz"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "unknown_scope_xyz"

    def test_feedback_cycle_empty_body(self) -> None:
        """빈 바디로 사이클 실행 시 기본 scope가 적용되어 정상 동작한다."""
        app = _build_authed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/feedback/cycle", json={})
        assert resp.status_code == 200


class TestSchedulerEdgeCases:
    """스케줄러 관련 에지 케이스"""

    @patch("src.api.routers.scheduler.get_scheduler_status")
    def test_scheduler_not_running_returns_false(self, mock_status) -> None:
        """스케줄러가 실행 중이 아닐 때 running=False를 반환한다."""
        mock_status.return_value = {"running": False, "jobs": []}

        app = _build_authed_app()
        app.include_router(scheduler.router, prefix="/api/v1/scheduler")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/scheduler/status")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert body["running"] is False
        assert body["job_count"] == 0

    @patch("src.api.routers.scheduler._get_job_history", new_callable=AsyncMock)
    @patch("src.api.routers.scheduler.get_scheduler_status")
    def test_scheduler_status_with_multiple_jobs(
        self, mock_status, mock_history
    ) -> None:
        """여러 작업이 있는 스케줄러 상태가 올바르게 반환된다."""
        mock_status.return_value = {
            "running": True,
            "job_count": 2,
            "jobs": [
                {"id": "data_collect", "name": "Data Collector", "next_run": "2026-04-12T09:00:00Z", "trigger": "cron"},
                {"id": "strategy_run", "name": "Strategy Runner", "next_run": "2026-04-12T10:00:00Z", "trigger": "cron"},
            ],
        }
        mock_history.return_value = []

        app = _build_authed_app()
        app.include_router(scheduler.router, prefix="/api/v1/scheduler")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/scheduler/status")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["jobs"]) == 2
