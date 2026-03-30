"""
test/integration/test_api_notifications.py — Notifications/Models/Audit/Feedback API 통합 테스트

K3s 클러스터에서 실행 중인 API에 HTTP 요청을 보내
알림, 모델 설정, 감사 추적, 피드백 관련 엔드포인트를 검증합니다.

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

import os
import unittest

import httpx
import pytest

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:18000")
LOGIN_EMAIL = "admin@alpha-trading.com"
LOGIN_PASSWORD = "admin123"


async def get_token() -> str:
    """로그인하여 JWT 토큰을 획득합니다."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        )
        resp.raise_for_status()
        return resp.json()["token"]


# ── Notifications ────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestNotificationsHistory(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/notifications/history"""

    async def test_get_history(self) -> None:
        """알림 이력을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/notifications/history",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("notifications", body)
        self.assertIsInstance(body["notifications"], list)

    async def test_history_without_token_returns_401(self) -> None:
        """토큰 없이 요청하면 401을 반환한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/notifications/history")

        self.assertEqual(resp.status_code, 401)


@pytest.mark.integration
class TestNotificationsPreferences(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/notifications/preferences"""

    async def test_get_preferences(self) -> None:
        """알림 설정을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/notifications/preferences",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("preferences", body)
        self.assertIsInstance(body["preferences"], dict)

    async def test_preferences_has_default_keys(self) -> None:
        """알림 설정에 기본 키가 포함되어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/notifications/preferences",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        prefs = resp.json()["preferences"]
        expected_keys = {"morning_brief", "trade_alerts", "circuit_breaker", "daily_report", "weekly_summary"}
        self.assertTrue(expected_keys.issubset(set(prefs.keys())))


@pytest.mark.integration
class TestNotificationsStats(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/notifications/stats"""

    async def test_get_stats(self) -> None:
        """알림 통계를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/notifications/stats",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("total_sent", body)
        self.assertIn("by_type", body)
        self.assertIn("daily_trend", body)

    async def test_stats_has_valid_types(self) -> None:
        """통계 응답의 필드 타입이 올바른지 확인한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/notifications/stats",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["total_sent"], int)
        self.assertIsInstance(body["by_type"], dict)
        self.assertIsInstance(body["daily_trend"], list)


# ── Models ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestModelsConfig(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/models/config"""

    async def test_get_model_config(self) -> None:
        """모델 설정을 조회한다 (admin 전용)."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/models/config",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("supported_models", body)
        self.assertIn("provider_status", body)
        self.assertIn("strategy_a", body)
        self.assertIn("strategy_b", body)
        self.assertIn("rule_based_fallback_allowed", body)

    async def test_model_config_supported_models_is_list(self) -> None:
        """supported_models는 리스트여야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/models/config",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body["supported_models"], list)
        self.assertIsInstance(body["provider_status"], list)
        self.assertIsInstance(body["strategy_a"], list)
        self.assertIsInstance(body["strategy_b"], list)


@pytest.mark.integration
class TestModelsDebugProviders(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/models/debug-providers"""

    async def test_get_debug_providers(self) -> None:
        """프로바이더 디버그 정보를 조회한다 (admin 전용)."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/models/debug-providers",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)

    async def test_debug_providers_has_provider_keys(self) -> None:
        """디버그 응답에 claude, gemini, gpt 키가 포함되어야 한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/models/debug-providers",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("claude", body)
        self.assertIn("gemini", body)
        self.assertIn("gpt", body)


# ── Audit ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAuditTrail(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/audit/trail"""

    async def test_get_audit_trail(self) -> None:
        """감사 추적 로그를 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/audit/trail",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("total", body)
        self.assertIn("page", body)
        self.assertIn("limit", body)
        self.assertIsInstance(body["data"], list)

    async def test_audit_trail_with_pagination(self) -> None:
        """감사 추적 로그에 페이지네이션을 적용할 수 있다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/audit/trail",
                params={"page": 1, "limit": 5},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertLessEqual(len(body["data"]), 5)


@pytest.mark.integration
class TestAuditSummary(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/audit/summary"""

    async def test_get_audit_summary(self) -> None:
        """감사 요약을 조회한다."""
        token = await get_token()
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/audit/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("total_events", body)
        self.assertIn("by_type", body)
        self.assertIsInstance(body["total_events"], int)
        self.assertIsInstance(body["by_type"], dict)


# ── Feedback ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestFeedbackAccuracy(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/feedback/accuracy"""

    async def test_get_accuracy(self) -> None:
        """전략 정확도 통계를 조회한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/feedback/accuracy")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)

    async def test_accuracy_items_have_required_fields(self) -> None:
        """정확도 항목에는 필수 필드가 포함되어야 한다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/feedback/accuracy")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for item in body:
            self.assertIn("strategy", item)
            self.assertIn("total_predictions", item)
            self.assertIn("correct_predictions", item)
            self.assertIn("accuracy", item)
            self.assertIn("signal_distribution", item)

    async def test_accuracy_with_strategy_filter(self) -> None:
        """전략 필터를 적용하여 정확도를 조회할 수 있다."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get(
                "/api/v1/feedback/accuracy",
                params={"strategy": "strategy_a"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)
        if body:
            self.assertEqual(body[0]["strategy"], "strategy_a")
