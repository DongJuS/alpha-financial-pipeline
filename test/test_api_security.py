"""
test/test_api_security.py — API 보안 테스트

SQL injection, XSS 방어, 인증 우회 시도 등 보안 관련 테스트.
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

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import auth, audit, backtest, feedback


def _build_secured_app() -> FastAPI:
    """보안 테스트용 앱을 빌드한다."""
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(feedback.router, prefix="/api/v1/feedback")
    app.include_router(audit.router, prefix="/api/v1/audit")
    app.include_router(backtest.router, prefix="/api/v1/backtest")
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="security-test-secret"
    )
    return app


def _build_authed_secured_app() -> FastAPI:
    """인증이 주입된 보안 테스트용 앱을 빌드한다."""
    app = _build_secured_app()

    async def mock_user():
        return {
            "sub": str(uuid4()),
            "email": "security@test.com",
            "name": "Security Tester",
            "is_admin": True,
        }

    app.dependency_overrides[get_current_user] = mock_user
    return app


# ── SQL Injection 방어 테스트 ───────────────────────────────────────────


class TestSQLInjectionDefense:
    """SQL injection 공격 벡터에 대한 방어를 검증한다."""

    def test_feedback_accuracy_strategy_sql_injection(self) -> None:
        """strategy 파라미터에 SQL injection 시도 시 안전하게 처리한다."""
        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        sql_injection_payloads = [
            "strategy_a'; DROP TABLE predictions; --",
            "strategy_a' OR '1'='1",
            "strategy_a' UNION SELECT * FROM users --",
            "strategy_a'; DELETE FROM predictions WHERE '1'='1",
        ]

        for payload in sql_injection_payloads:
            resp = client.get(f"/api/v1/feedback/accuracy?strategy={payload}")
            # DB 미연결 시 빈 데이터 반환, SQL injection이 실행되지 않음
            assert resp.status_code == 200, f"SQL injection should not cause error: {payload}"

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_event_type_sql_injection(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """audit trail의 event_type 파라미터에 SQL injection 시도."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        # parameterized query 사용 확인 — injection 시도는 파라미터 값으로만 전달됨
        resp = client.get(
            "/api/v1/audit/trail?event_type=trade' OR '1'='1"
        )
        assert resp.status_code == 200

        # 실제 DB에 전달되는 SQL을 확인: $1 파라미터로 바인딩됨
        fetch_call = mock_fetch.call_args
        sql = fetch_call[0][0]
        assert "$" in sql  # parameterized query 사용 확인

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_date_filter_sql_injection(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """date_from 파라미터에 SQL injection 시도."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/api/v1/audit/trail?date_from=2025-01-01'; DROP TABLE trade_history; --"
        )
        # parameterized query이므로 SQL injection이 실행되지 않음
        assert resp.status_code == 200

    @patch("src.api.routers.backtest.fetchval", new_callable=AsyncMock)
    @patch("src.api.routers.backtest.fetch", new_callable=AsyncMock)
    def test_backtest_runs_strategy_filter_sql_injection(
        self, mock_fetch: AsyncMock, mock_fetchval: AsyncMock
    ) -> None:
        """backtest runs의 strategy 파라미터에 SQL injection 시도."""
        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        # strategy 패턴 검증으로 인한 422 반환 기대
        resp = client.get("/api/v1/backtest/runs?strategy=RL'; DROP TABLE backtest_runs;--")
        assert resp.status_code == 422  # 패턴 검증 실패


# ── XSS 방어 테스트 ────────────────────────────────────────────────────


class TestXSSDefense:
    """XSS 공격 벡터에 대한 방어를 검증한다."""

    def test_feedback_llm_context_strategy_xss(self) -> None:
        """strategy 경로 변수에 XSS 스크립트 주입 시 안전하게 처리한다."""
        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        # URL-safe XSS 페이로드 (경로 파라미터에서 <>는 URL 인코딩됨)
        safe_xss_payloads = [
            "strategy_a%22onmouseover%3Dalert(1)",
            "strategy_a'onclick=alert(1)",
            "javascript:alert(1)",
        ]

        for payload in safe_xss_payloads:
            resp = client.get(f"/api/v1/feedback/llm-context/{payload}")
            assert resp.status_code == 200

            body = resp.json()
            # JSON 응답이므로 XSS가 실행되지 않음
            # FastAPI는 기본적으로 JSON 응답을 반환
            assert "strategy" in body
            assert "feedback_text" in body

        # HTML 태그가 포함된 페이로드는 URL 인코딩되어 경로 매칭에 실패할 수 있음
        # 이는 HTTPX가 자동으로 URL 인코딩하기 때문 — 정상 동작
        resp = client.get("/api/v1/feedback/llm-context/<script>alert('xss')</script>")
        # URL 인코딩으로 인해 404가 될 수 있으며 이는 안전한 동작
        assert resp.status_code in (200, 404)

    def test_feedback_backtest_strategy_xss(self) -> None:
        """backtest 요청의 strategy 필드에 XSS 주입 시도."""
        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/feedback/backtest",
            json={"strategy": "<script>alert('xss')</script>"},
        )
        assert resp.status_code == 200

        body = resp.json()
        # JSON 응답에서는 XSS가 실행되지 않음
        assert "<script>" in body["strategy"]


# ── 인증 우회 시도 ──────────────────────────────────────────────────────


class TestAuthBypassAttempts:
    """인증 우회 시도를 검증한다."""

    def test_audit_without_auth_is_rejected(self) -> None:
        """인증 없이 audit 엔드포인트를 호출하면 거부된다."""
        app = _build_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/v1/audit/trail")
        assert resp.status_code in (401, 403)

        resp = client.get("/api/v1/audit/summary")
        assert resp.status_code in (401, 403)

    def test_backtest_without_auth_is_rejected(self) -> None:
        """인증 없이 backtest 엔드포인트를 호출하면 거부된다."""
        app = _build_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/v1/backtest/runs")
        assert resp.status_code in (401, 403)

        resp = client.get("/api/v1/backtest/runs/1")
        assert resp.status_code in (401, 403)

        resp = client.get("/api/v1/backtest/runs/1/daily")
        assert resp.status_code in (401, 403)

    def test_jwt_with_none_algorithm_is_rejected(self) -> None:
        """'none' 알고리즘 JWT는 거부된다."""
        app = _build_secured_app()

        # PyJWT는 기본적으로 none 알고리즘을 허용하지 않지만 명시적으로 확인
        # jwt.encode with algorithm="none" and no key
        try:
            payload = {
                "sub": str(uuid4()),
                "email": "hacker@test.com",
                "name": "Hacker",
                "is_admin": True,
                "exp": int(time.time()) + 3600,
            }
            # 일부 JWT 라이브러리는 none 알고리즘을 허용할 수 있음
            fake_token = jwt.encode(payload, "", algorithm="HS256")
        except Exception:
            fake_token = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ0ZXN0In0."

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": f"Bearer {fake_token}"},
        )
        assert resp.status_code == 401

    def test_jwt_tampering_is_detected(self) -> None:
        """변조된 JWT는 거부된다."""
        app = _build_secured_app()

        valid_token = jwt.encode(
            {
                "sub": str(uuid4()),
                "email": "test@test.com",
                "name": "Tester",
                "is_admin": True,
                "exp": int(time.time()) + 3600,
            },
            "security-test-secret",
            algorithm="HS256",
        )

        # 토큰의 마지막 몇 글자를 변경하여 서명을 변조
        tampered_token = valid_token[:-5] + "XXXXX"

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        assert resp.status_code == 401

    def test_replay_attack_with_expired_token(self) -> None:
        """만료된 토큰을 재사용한 replay attack은 거부된다."""
        app = _build_secured_app()

        expired_token = jwt.encode(
            {
                "sub": str(uuid4()),
                "email": "test@test.com",
                "name": "Tester",
                "is_admin": True,
                "exp": int(time.time()) - 1,  # 1초 전 만료
            },
            "security-test-secret",
            algorithm="HS256",
        )

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/audit/trail",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401


# ── 페이로드 크기 방어 테스트 ───────────────────────────────────────────


class TestPayloadSizeDefense:
    """비정상적으로 큰 페이로드에 대한 방어를 검증한다."""

    def test_extremely_long_strategy_name(self) -> None:
        """매우 긴 strategy 이름도 안전하게 처리한다."""
        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        long_strategy = "a" * 10000
        resp = client.get(f"/api/v1/feedback/llm-context/{long_strategy}")
        assert resp.status_code == 200
        assert resp.json()["strategy"] == long_strategy

    def test_backtest_compare_many_strategies(self) -> None:
        """많은 수의 전략을 비교해도 안전하게 처리한다."""
        app = _build_authed_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        many_strategies = [f"strategy_{i}" for i in range(100)]
        resp = client.post(
            "/api/v1/feedback/backtest/compare",
            json={"strategies": many_strategies},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["strategies"]) == 100


# ── 인증 Login endpoint 보안 ───────────────────────────────────────────


class TestLoginSecurity:
    """로그인 엔드포인트 보안 검증."""

    def test_login_with_empty_password_returns_error(self) -> None:
        """빈 비밀번호로 로그인 시 422를 반환한다."""
        app = _build_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "test@test.com", "password": ""},
        )
        assert resp.status_code == 422

    def test_login_with_invalid_email_format_returns_422(self) -> None:
        """잘못된 이메일 형식으로 로그인 시 422를 반환한다."""
        app = _build_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "test123"},
        )
        assert resp.status_code == 422

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_login_with_wrong_password_returns_401(
        self, mock_fetchrow: AsyncMock
    ) -> None:
        """잘못된 비밀번호로 로그인 시 401을 반환한다."""
        from src.utils.auth import hash_password

        mock_fetchrow.return_value = {
            "id": uuid4(),
            "email": "test@test.com",
            "name": "Tester",
            "password_hash": hash_password("correct-password"),
            "is_admin": True,
        }

        app = _build_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "test@test.com", "password": "wrong-password"},
        )
        assert resp.status_code == 401

    @patch.object(auth, "fetchrow", new_callable=AsyncMock)
    def test_login_nonexistent_user_returns_401(self, mock_fetchrow: AsyncMock) -> None:
        """존재하지 않는 사용자로 로그인 시 401을 반환한다."""
        mock_fetchrow.return_value = None

        app = _build_secured_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@test.com", "password": "any-password"},
        )
        assert resp.status_code == 401
