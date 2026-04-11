"""
test/integration/test_api_notifications.py — Notifications/Models/Audit/Feedback API 통합 테스트

FastAPI TestClient로 알림, 모델, 감사, 피드백 라우터를 격리 테스트한다.
DB/Redis는 mock으로 대체.

테스트 대상:
  - GET  /api/v1/notifications/history      — 알림 이력
  - GET  /api/v1/notifications/preferences  — 알림 설정
  - GET  /api/v1/notifications/stats        — 알림 통계
  - GET  /api/v1/models/config              — 모델 설정
  - GET  /api/v1/models/debug-providers     — 프로바이더 디버그 정보
  - GET  /api/v1/audit/trail                — 감사 추적 로그
  - GET  /api/v1/audit/summary              — 감사 요약
  - GET  /api/v1/feedback/accuracy          — 전략 정확도
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_admin_user, get_current_settings, get_current_user
from src.api.routers import (
    audit as audit_module,
    feedback as feedback_module,
    models as models_module,
    notifications as notif_module,
)

API_NOTIF = "/api/v1/notifications"
API_MODELS = "/api/v1/models"
API_AUDIT = "/api/v1/audit"
API_FEEDBACK = "/api/v1/feedback"


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(notif_module.router, prefix=API_NOTIF)
    app.include_router(models_module.router, prefix=API_MODELS)
    app.include_router(audit_module.router, prefix=API_AUDIT)
    app.include_router(feedback_module.router, prefix=API_FEEDBACK)
    if authenticated:
        async def mock_user():
            return {
                "sub": str(uuid4()),
                "email": "test@test.com",
                "name": "Tester",
                "is_admin": True,
            }
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_admin_user] = mock_user
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(
        jwt_secret="test-secret"
    )
    return TestClient(app, raise_server_exceptions=False)


# ── Notifications ────────────────────────────────────────────────────────────


class TestNotificationsHistory:
    """GET /api/v1/notifications/history"""

    @patch("src.api.routers.notifications.fetch", new_callable=AsyncMock, return_value=[])
    def test_get_history(self, mock_fetch: AsyncMock) -> None:
        """알림 이력을 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_NOTIF}/history")
        assert resp.status_code == 200
        body = resp.json()
        assert "notifications" in body
        assert isinstance(body["notifications"], list)

    def test_history_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401/403을 반환한다."""
        client = _build_client(authenticated=False)
        resp = client.get(f"{API_NOTIF}/history")
        assert resp.status_code in (401, 403)


class TestNotificationsPreferences:
    """GET /api/v1/notifications/preferences"""

    @patch("src.utils.redis_client.get_redis", new_callable=AsyncMock)
    def test_get_preferences(self, mock_redis: AsyncMock) -> None:
        """알림 설정을 조회한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock

        client = _build_client()
        resp = client.get(f"{API_NOTIF}/preferences")
        assert resp.status_code == 200
        body = resp.json()
        assert "preferences" in body
        assert isinstance(body["preferences"], dict)

    @patch("src.utils.redis_client.get_redis", new_callable=AsyncMock)
    def test_preferences_has_default_keys(self, mock_redis: AsyncMock) -> None:
        """알림 설정에 기본 키가 포함되어야 한다."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock

        client = _build_client()
        resp = client.get(f"{API_NOTIF}/preferences")
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        expected_keys = {"morning_brief", "trade_alerts", "circuit_breaker", "daily_report", "weekly_summary"}
        assert expected_keys.issubset(set(prefs.keys()))


class TestNotificationsStats:
    """GET /api/v1/notifications/stats"""

    @patch("src.api.routers.notifications.fetch", new_callable=AsyncMock, return_value=[])
    @patch("src.utils.db_client.fetchrow", new_callable=AsyncMock)
    def test_get_stats(self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock) -> None:
        """알림 통계를 조회한다."""
        mock_fetchrow.return_value = {"total_sent": 42, "success_rate": 0.95}

        client = _build_client()
        resp = client.get(f"{API_NOTIF}/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_sent" in body
        assert "by_type" in body
        assert "daily_trend" in body

    @patch("src.api.routers.notifications.fetch", new_callable=AsyncMock, return_value=[])
    @patch("src.utils.db_client.fetchrow", new_callable=AsyncMock)
    def test_stats_has_valid_types(
        self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """통계 응답의 필드 타입이 올바른지 확인한다."""
        mock_fetchrow.return_value = {"total_sent": 10, "success_rate": 1.0}

        client = _build_client()
        resp = client.get(f"{API_NOTIF}/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["total_sent"], int)
        assert isinstance(body["by_type"], dict)
        assert isinstance(body["daily_trend"], list)


# ── Models ───────────────────────────────────────────────────────────────────


class TestModelsConfig:
    """GET /api/v1/models/config"""

    @patch("src.services.model_config.get_strategy_b_roles", new_callable=AsyncMock, return_value=[])
    @patch("src.services.model_config.get_strategy_a_profiles", new_callable=AsyncMock, return_value=[])
    def test_get_model_config(
        self, mock_a_profiles: AsyncMock, mock_b_roles: AsyncMock
    ) -> None:
        """모델 설정을 조회한다 (admin 전용)."""
        client = _build_client()
        resp = client.get(f"{API_MODELS}/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "supported_models" in body
        assert "provider_status" in body
        assert "strategy_a" in body
        assert "strategy_b" in body
        assert "rule_based_fallback_allowed" in body

    @patch("src.services.model_config.get_strategy_b_roles", new_callable=AsyncMock, return_value=[])
    @patch("src.services.model_config.get_strategy_a_profiles", new_callable=AsyncMock, return_value=[])
    def test_model_config_supported_models_is_list(
        self, mock_a_profiles: AsyncMock, mock_b_roles: AsyncMock
    ) -> None:
        """supported_models는 리스트여야 한다."""
        client = _build_client()
        resp = client.get(f"{API_MODELS}/config")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["supported_models"], list)
        assert isinstance(body["provider_status"], list)
        assert isinstance(body["strategy_a"], list)
        assert isinstance(body["strategy_b"], list)


class TestModelsDebugProviders:
    """GET /api/v1/models/debug-providers"""

    def test_get_debug_providers(self) -> None:
        """프로바이더 디버그 정보를 조회한다 (admin 전용)."""
        client = _build_client()
        resp = client.get(f"{API_MODELS}/debug-providers")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)

    def test_debug_providers_has_provider_keys(self) -> None:
        """디버그 응답에 claude, gemini, gpt 키가 포함되어야 한다."""
        client = _build_client()
        resp = client.get(f"{API_MODELS}/debug-providers")
        assert resp.status_code == 200
        body = resp.json()
        assert "claude" in body
        assert "gemini" in body
        assert "gpt" in body


# ── Audit ────────────────────────────────────────────────────────────────────


class TestAuditTrail:
    """GET /api/v1/audit/trail"""

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_get_audit_trail(self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock) -> None:
        """감사 추적 로그를 조회한다."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        client = _build_client()
        resp = client.get(f"{API_AUDIT}/trail")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "total" in body
        assert "page" in body
        assert "limit" in body
        assert isinstance(body["data"], list)

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    def test_audit_trail_with_pagination(
        self, mock_fetch: AsyncMock, mock_fetchrow: AsyncMock
    ) -> None:
        """감사 추적 로그에 페이지네이션을 적용할 수 있다."""
        mock_fetch.return_value = []
        mock_fetchrow.return_value = {"cnt": 0}

        client = _build_client()
        resp = client.get(f"{API_AUDIT}/trail", params={"page": 1, "limit": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) <= 5


class TestAuditSummary:
    """GET /api/v1/audit/summary"""

    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock, return_value=[])
    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    def test_get_audit_summary(
        self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """감사 요약을 조회한다."""
        mock_fetchrow.return_value = {"total_events": 0, "pass_rate": None}

        client = _build_client()
        resp = client.get(f"{API_AUDIT}/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_events" in body
        assert "by_type" in body
        assert isinstance(body["total_events"], int)
        assert isinstance(body["by_type"], dict)


# ── Feedback ─────────────────────────────────────────────────────────────────


class TestFeedbackAccuracy:
    """GET /api/v1/feedback/accuracy"""

    def test_get_accuracy(self) -> None:
        """전략 정확도 통계를 조회한다."""
        client = _build_client()
        resp = client.get(f"{API_FEEDBACK}/accuracy")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_accuracy_items_have_required_fields(self) -> None:
        """정확도 항목에는 필수 필드가 포함되어야 한다."""
        client = _build_client()
        resp = client.get(f"{API_FEEDBACK}/accuracy")
        assert resp.status_code == 200
        body = resp.json()
        for item in body:
            assert "strategy" in item
            assert "total_predictions" in item
            assert "correct_predictions" in item
            assert "accuracy" in item
            assert "signal_distribution" in item

    def test_accuracy_with_strategy_filter(self) -> None:
        """전략 필터를 적용하여 정확도를 조회할 수 있다."""
        client = _build_client()
        resp = client.get(f"{API_FEEDBACK}/accuracy", params={"strategy": "strategy_a"})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        if body:
            assert body[0]["strategy"] == "strategy_a"
