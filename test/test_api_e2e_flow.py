"""
test/test_api_e2e_flow.py — E2E 시나리오 테스트

로그인 -> 시그널 조회 -> 포트폴리오 확인 -> 설정 변경 등 실제 사용자 흐름을 시뮬레이션.
모든 외부 의존성은 mock으로 대체.
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

from src.api.deps import get_current_settings
from src.api.routers import auth, feedback, scheduler
from src.api.routers import audit as audit_router_module
from src.api.routers import backtest as backtest_router_module
import src.api.deps as auth_deps
import src.api.routers.feedback as feedback_module
from src.agents.rl_continuous_improver import RetrainOutcome
from src.utils.auth import hash_password


def _build_e2e_app() -> FastAPI:
    """E2E 테스트용 앱을 빌드한다 (인증 흐름 포함)."""
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(feedback.router, prefix="/api/v1/feedback")
    app.include_router(audit_router_module.router, prefix="/api/v1/audit")
    app.include_router(backtest_router_module.router, prefix="/api/v1/backtest")
    app.include_router(scheduler.router, prefix="/api/v1/scheduler")
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="e2e-test-secret"
    )
    return app


USER_ID = uuid4()
USER_EMAIL = "e2e@alpha-trading.com"
USER_PASSWORD = "e2e-test-pass"
USER_ROW = {
    "id": USER_ID,
    "email": USER_EMAIL,
    "name": "E2E Tester",
    "password_hash": hash_password(USER_PASSWORD),
    "is_admin": True,
}
USER_INFO_ROW = {
    "id": USER_ID,
    "email": USER_EMAIL,
    "name": "E2E Tester",
    "is_admin": True,
}


class TestLoginThenFeedbackFlow:
    """E2E: 로그인 -> 피드백 API 조회 흐름"""

    def _login(self, client: TestClient) -> str:
        """로그인하여 토큰을 획득한다."""
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert resp.status_code == 200, f"Login failed: {resp.json()}"
        token = resp.json()["token"]
        assert isinstance(token, str)
        assert len(token) > 0
        return token

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_login_then_accuracy_check(self, mock_login_fetchrow: AsyncMock) -> None:
        """로그인 후 정확도 통계를 조회할 수 있다."""
        mock_login_fetchrow.return_value = USER_ROW

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 로그인
        token = self._login(client)

        # Step 2: 정확도 조회 (DB 없이 빈 데이터 반환 기대)
        resp = client.get("/api/v1/feedback/accuracy")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_login_then_llm_context_check(self, mock_login_fetchrow: AsyncMock) -> None:
        """로그인 후 LLM 피드백 컨텍스트를 조회할 수 있다."""
        mock_login_fetchrow.return_value = USER_ROW

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 로그인
        token = self._login(client)

        # Step 2: LLM 컨텍스트 조회
        resp = client.get("/api/v1/feedback/llm-context/strategy_a")
        assert resp.status_code == 200
        body = resp.json()
        assert body["strategy"] == "strategy_a"
        assert "feedback_text" in body

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_login_then_backtest_then_compare(self, mock_login_fetchrow: AsyncMock) -> None:
        """로그인 후 백테스트 실행 + 비교를 수행할 수 있다."""
        mock_login_fetchrow.return_value = USER_ROW

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 로그인
        token = self._login(client)

        # Step 2: 백테스트 실행
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_a", "initial_capital": 5_000_000},
        )
        assert resp.status_code == 200
        backtest_result = resp.json()
        assert backtest_result["strategy"] == "strategy_a"
        assert backtest_result["initial_capital"] == 5_000_000

        # Step 3: 전략 비교
        resp = client.post(
            "/api/v1/feedback/backtest/compare",
            json={"strategies": ["strategy_a", "strategy_b"]},
        )
        assert resp.status_code == 200
        compare_result = resp.json()
        assert len(compare_result["strategies"]) == 2
        assert compare_result["best_strategy"] is not None


class TestLoginThenAuditFlow:
    """E2E: 로그인 -> 감사 추적 조회 흐름"""

    @patch.object(auth_deps, "fetchrow", new_callable=AsyncMock)
    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    @patch.object(audit_router_module, "fetchrow", new_callable=AsyncMock)
    @patch.object(audit_router_module, "fetch", new_callable=AsyncMock)
    def test_login_then_audit_trail_and_summary(
        self,
        mock_audit_fetch: AsyncMock,
        mock_audit_fetchrow: AsyncMock,
        mock_login_fetchrow: AsyncMock,
        mock_deps_fetchrow: AsyncMock,
    ) -> None:
        """로그인 후 감사 추적 + 요약을 조회할 수 있다."""
        mock_login_fetchrow.return_value = USER_ROW
        mock_deps_fetchrow.return_value = USER_INFO_ROW

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 로그인
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert resp.status_code == 200
        token = resp.json()["token"]

        # Step 2: 감사 추적 조회
        mock_audit_fetch.return_value = [
            {
                "event_type": "trade",
                "event_time": "2025-01-01T10:00:00Z",
                "agent_id": "strategy_a",
                "description": "BUY Samsung x10",
                "result": "executed",
            },
        ]
        mock_audit_fetchrow.return_value = {"cnt": 1}

        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        trail_body = resp.json()
        assert trail_body["total"] >= 0

        # Step 3: 감사 요약 조회
        mock_audit_fetchrow.return_value = {"total_events": 1, "pass_rate": 1.0}
        mock_audit_fetch.return_value = [{"event_type": "trade", "cnt": 1}]

        resp = client.get(
            "/api/v1/audit/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        summary_body = resp.json()
        assert "total_events" in summary_body


class TestSchedulerCheckFlow:
    """E2E: 스케줄러 상태 확인 흐름"""

    @patch("src.api.routers.scheduler.get_scheduler_status")
    def test_scheduler_status_check(self, mock_status) -> None:
        """스케줄러 상태 엔드포인트가 정상 동작한다."""
        mock_status.return_value = {"running": False, "jobs": []}

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/v1/scheduler/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "running" in body


class TestFeedbackCycleE2EFlow:
    """E2E: 피드백 사이클 실행 흐름"""

    def test_feedback_cycle_llm_only_no_external_deps(self) -> None:
        """llm_only 사이클을 외부 의존성 없이 실행할 수 있다."""
        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "llm_only"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "llm_only"
        assert body["saved_to_s3"] is False
        assert body["duration_seconds"] >= 0

    def test_feedback_cycle_backtest_only(self) -> None:
        """backtest_only 사이클을 실행할 수 있다."""
        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "backtest_only"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "backtest_only"
        assert body["backtest"] is not None
        assert body["rl_retrain"] is None


class TestMultiStepWorkflow:
    """E2E: 여러 단계를 거치는 복합 워크플로우"""

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_accuracy_then_backtest_then_cycle(self, mock_login_fetchrow: AsyncMock) -> None:
        """정확도 확인 -> 백테스트 -> 피드백 사이클 흐름."""
        mock_login_fetchrow.return_value = USER_ROW

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 정확도 확인
        resp = client.get("/api/v1/feedback/accuracy?strategy=strategy_a&days=30")
        assert resp.status_code == 200
        accuracy = resp.json()
        assert len(accuracy) == 1
        assert accuracy[0]["strategy"] == "strategy_a"

        # Step 2: 정확도에 기반한 백테스트
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={
                "strategy": "strategy_a",
                "start_date": "2025-01-01",
                "end_date": "2025-06-30",
            },
        )
        assert resp.status_code == 200
        bt = resp.json()
        assert bt["strategy"] == "strategy_a"
        assert bt["period"]["start"] == "2025-01-01"

        # Step 3: LLM 피드백 사이클
        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "llm_only"},
        )
        assert resp.status_code == 200
        cycle = resp.json()
        assert cycle["llm_feedback"] is not None


class TestFeedbackCompareWorkflow:
    """E2E: 백테스트 실행 -> 전략 비교 -> LLM 컨텍스트 조회 흐름"""

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_backtest_all_strategies_then_compare_then_context(
        self, mock_login_fetchrow: AsyncMock
    ) -> None:
        """두 전략의 백테스트를 실행한 뒤 비교하고 LLM 피드백 컨텍스트를 확인한다."""
        mock_login_fetchrow.return_value = USER_ROW

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: Strategy A 백테스트
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_a", "initial_capital": 10_000_000},
        )
        assert resp.status_code == 200
        bt_a = resp.json()
        assert bt_a["strategy"] == "strategy_a"

        # Step 2: Strategy B 백테스트
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_b", "initial_capital": 10_000_000},
        )
        assert resp.status_code == 200
        bt_b = resp.json()
        assert bt_b["strategy"] == "strategy_b"

        # Step 3: 전략 비교
        resp = client.post(
            "/api/v1/feedback/backtest/compare",
            json={"strategies": ["strategy_a", "strategy_b"]},
        )
        assert resp.status_code == 200
        compare = resp.json()
        assert "best_strategy" in compare
        assert compare["best_strategy"] in ("strategy_a", "strategy_b")

        # Step 4: 최적 전략의 LLM 컨텍스트 조회
        best = compare["best_strategy"]
        resp = client.get(f"/api/v1/feedback/llm-context/{best}")
        assert resp.status_code == 200
        ctx = resp.json()
        assert ctx["strategy"] == best
        assert "feedback_text" in ctx


class TestFullFeedbackCycleE2E:
    """E2E: 정확도 -> 백테스트 -> full 피드백 사이클 흐름"""

    def test_accuracy_then_backtest_then_full_cycle(self) -> None:
        """정확도 확인 -> 백테스트 -> full 피드백 사이클을 연속 실행한다."""
        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 정확도 확인
        resp = client.get("/api/v1/feedback/accuracy?days=7")
        assert resp.status_code == 200
        accuracy = resp.json()
        assert isinstance(accuracy, list)

        # Step 2: 백테스트 실행
        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "strategy_a"},
        )
        assert resp.status_code == 200
        bt = resp.json()
        assert "total_return" in bt
        assert bt["strategy"] == "strategy_a"

        # Step 3: backtest_only 사이클 실행
        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "backtest_only"},
        )
        assert resp.status_code == 200
        cycle = resp.json()
        assert cycle["scope"] == "backtest_only"
        assert cycle["backtest"] is not None

        # Step 4: llm_only 사이클 실행
        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "llm_only"},
        )
        assert resp.status_code == 200
        cycle2 = resp.json()
        assert cycle2["llm_feedback"] is not None


class TestLoginThenSchedulerAndFeedback:
    """E2E: 로그인 -> 스케줄러 확인 -> 피드백 사이클"""

    @patch("src.api.routers.scheduler.get_scheduler_status")
    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_login_scheduler_check_then_feedback(
        self, mock_login_fetchrow: AsyncMock, mock_scheduler: AsyncMock
    ) -> None:
        """로그인 후 스케줄러 상태를 확인하고 피드백 사이클을 실행한다."""
        mock_login_fetchrow.return_value = USER_ROW
        mock_scheduler.return_value = {"running": False, "jobs": []}

        app = _build_e2e_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: 로그인
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert resp.status_code == 200
        token = resp.json()["token"]

        # Step 2: 스케줄러 상태 확인
        resp = client.get("/api/v1/scheduler/status")
        assert resp.status_code == 200
        scheduler_body = resp.json()
        assert "running" in scheduler_body
        assert scheduler_body["running"] is False

        # Step 3: LLM 피드백 사이클
        resp = client.post(
            "/api/v1/feedback/cycle",
            json={"scope": "llm_only"},
        )
        assert resp.status_code == 200
        assert resp.json()["scope"] == "llm_only"
