"""
test/test_qa_notifications_heatmap.py — QA Round 2 coverage: Notifications + Heatmap

QA WARN 보강 테스트:
  1. Notifications: 실제 데이터가 있을 때의 응답 구조 검증 (history, stats, preferences PUT)
  2. Marketplace Heatmap: Redis cache miss -> DB fallback 경로 검증

기존 integration 테스트에서 빠진 경로:
  - notifications history/stats: fetch=[] (빈 리스트) mock만 존재 -> 실제 데이터 응답 미검증
  - heatmap: Redis cache hit만 테스트 -> cache miss + DB fallback 미검증
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
from src.api.routers import notifications as notif_module
from src.api.routers import marketplace as mp_module

API_NOTIF = "/api/v1/notifications"
API_MP = "/api/v1/marketplace"

_MP_PATCH = "src.api.routers.marketplace"


def _build_notif_client() -> TestClient:
    """Notifications 라우터 전용 TestClient (인증 mock 포함)."""
    app = FastAPI()
    app.include_router(notif_module.router, prefix=API_NOTIF)

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


def _build_mp_client() -> TestClient:
    """Marketplace 라우터 전용 TestClient (인증 mock 포함)."""
    app = FastAPI()
    app.include_router(mp_module.router, prefix=API_MP)

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


# ── Notifications: 실제 데이터 응답 구조 검증 ──────────────────────────────────


class TestNotificationHistoryWithItems:
    """GET /api/v1/notifications/history — 실제 알림 데이터 존재 시 응답 구조."""

    @patch("src.api.routers.notifications.fetch", new_callable=AsyncMock)
    def test_notification_history_with_items(self, mock_fetch: AsyncMock) -> None:
        """history 엔드포인트에 실제 알림 데이터가 있을 때 응답 필드를 검증한다."""
        mock_fetch.return_value = [
            {
                "event_type": "trade_alert",
                "message": "삼성전자 매수 체결",
                "success": True,
                "error_msg": None,
                "sent_at": "2026-04-12T09:30:00+09:00",
            },
            {
                "event_type": "morning_brief",
                "message": "오늘의 시장 브리핑",
                "success": True,
                "error_msg": None,
                "sent_at": "2026-04-12T08:00:00+09:00",
            },
            {
                "event_type": "circuit_breaker",
                "message": "서킷브레이커 발동 알림",
                "success": False,
                "error_msg": "Telegram timeout",
                "sent_at": "2026-04-11T14:30:00+09:00",
            },
        ]

        client = _build_notif_client()
        resp = client.get(f"{API_NOTIF}/history")
        assert resp.status_code == 200

        body = resp.json()
        assert "notifications" in body
        notifications = body["notifications"]
        assert len(notifications) == 3

        # 각 알림 항목의 필수 필드 존재 및 타입 검증
        for item in notifications:
            assert "event_type" in item
            assert "message" in item
            assert "success" in item
            assert "error_msg" in item
            assert "sent_at" in item
            assert isinstance(item["event_type"], str)
            assert isinstance(item["message"], str)
            assert isinstance(item["success"], bool)

        # 실패 항목의 error_msg가 문자열인지 확인
        failed = [n for n in notifications if not n["success"]]
        assert len(failed) == 1
        assert isinstance(failed[0]["error_msg"], str)


class TestNotificationStatsWithData:
    """GET /api/v1/notifications/stats — 실제 통계 데이터 존재 시."""

    @patch("src.api.routers.notifications.fetch", new_callable=AsyncMock)
    @patch("src.utils.db_client.fetchrow", new_callable=AsyncMock)
    def test_notification_stats_with_data(
        self, mock_fetchrow: AsyncMock, mock_fetch: AsyncMock
    ) -> None:
        """stats 엔드포인트에 실제 통계 데이터가 있을 때 구조를 검증한다."""
        mock_fetchrow.return_value = {"total_sent": 150, "success_rate": 0.9733}

        # fetch는 두 번 호출됨: by_type_rows, daily_rows
        mock_fetch.side_effect = [
            # by_type_rows
            [
                {"event_type": "trade_alert", "cnt": 80},
                {"event_type": "morning_brief", "cnt": 50},
                {"event_type": "circuit_breaker", "cnt": 20},
            ],
            # daily_rows
            [
                {"date": "2026-04-12", "cnt": 15, "success_cnt": 14},
                {"date": "2026-04-11", "cnt": 20, "success_cnt": 20},
                {"date": "2026-04-10", "cnt": 12, "success_cnt": 11},
            ],
        ]

        client = _build_notif_client()
        resp = client.get(f"{API_NOTIF}/stats")
        assert resp.status_code == 200

        body = resp.json()

        # total_sent > 0 검증
        assert body["total_sent"] == 150
        assert body["total_sent"] > 0

        # success_rate 검증
        assert body["success_rate"] == pytest.approx(0.9733, abs=1e-4)

        # by_type에 항목이 포함되어 있는지 검증
        assert isinstance(body["by_type"], dict)
        assert len(body["by_type"]) == 3
        assert body["by_type"]["trade_alert"] == 80
        assert body["by_type"]["morning_brief"] == 50
        assert body["by_type"]["circuit_breaker"] == 20

        # daily_trend 구조 검증
        assert isinstance(body["daily_trend"], list)
        assert len(body["daily_trend"]) == 3
        for day in body["daily_trend"]:
            assert "date" in day
            assert "cnt" in day
            assert "success_cnt" in day


class TestNotificationPreferencesUpdate:
    """PUT /api/v1/notifications/preferences — 설정 변경 후 반영 확인."""

    @patch("src.utils.redis_client.get_redis", new_callable=AsyncMock)
    def test_notification_preferences_update(self, mock_get_redis: AsyncMock) -> None:
        """PUT /preferences로 설정 변경 후 변경값이 응답에 반영되는지 검증한다."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock()
        mock_get_redis.return_value = redis_mock

        client = _build_notif_client()

        # morning_brief=False, trade_alerts=False로 변경
        resp = client.put(
            f"{API_NOTIF}/preferences",
            json={
                "morning_brief": False,
                "trade_alerts": False,
                "circuit_breaker": True,
                "daily_report": True,
                "weekly_summary": False,
            },
        )
        assert resp.status_code == 200

        body = resp.json()
        assert "message" in body
        assert "preferences" in body

        prefs = body["preferences"]
        # 변경된 값이 정확히 반영되었는지 확인
        assert prefs["morning_brief"] is False
        assert prefs["trade_alerts"] is False
        assert prefs["circuit_breaker"] is True
        assert prefs["daily_report"] is True
        assert prefs["weekly_summary"] is False

        # Redis에 저장이 호출되었는지 확인
        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        assert call_args[0][0] == "system:notification_preferences"
        saved_data = json.loads(call_args[0][1])
        assert saved_data["morning_brief"] is False
        assert saved_data["trade_alerts"] is False


# ── Marketplace Heatmap: cache miss + DB fallback 검증 ─────────────────────


class TestHeatmapCacheMissFallsBackToDb:
    """GET /api/v1/marketplace/sectors/heatmap — Redis cache miss -> DB fallback."""

    @patch("src.utils.db_client.fetch", new_callable=AsyncMock)
    @patch(f"{_MP_PATCH}.get_redis", new_callable=AsyncMock)
    def test_heatmap_cache_miss_falls_back_to_db(
        self, mock_get_redis: AsyncMock, mock_db_fetch: AsyncMock
    ) -> None:
        """Redis cache miss 시 DB 쿼리로 fallback하여 결과를 반환한다."""
        # Redis: cache miss (None 반환)
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.set = AsyncMock()
        mock_get_redis.return_value = redis_mock

        # DB fallback 결과
        mock_db_fetch.return_value = [
            {
                "sector": "전기전자",
                "stock_count": 50,
                "avg_change_pct": 1.23,
                "total_market_cap": 500000000000,
                "total_volume": 12000000,
            },
            {
                "sector": "화학",
                "stock_count": 30,
                "avg_change_pct": -0.45,
                "total_market_cap": 200000000000,
                "total_volume": 5000000,
            },
        ]

        client = _build_mp_client()
        resp = client.get(f"{API_MP}/sectors/heatmap")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2

        # DB에서 가져온 데이터가 올바르게 가공되었는지 검증
        assert body[0]["sector"] == "전기전자"
        assert body[0]["stock_count"] == 50
        assert body[0]["avg_change_pct"] == 1.23
        assert body[0]["total_market_cap"] == 500000000000
        assert body[0]["total_volume"] == 12000000

        assert body[1]["sector"] == "화학"
        assert body[1]["avg_change_pct"] == -0.45

        # DB fetch가 호출되었는지 확인
        mock_db_fetch.assert_called_once()


class TestHeatmapEmptyDbReturnsEmptyList:
    """GET /api/v1/marketplace/sectors/heatmap — cache miss + DB 빈 결과."""

    @patch("src.utils.db_client.fetch", new_callable=AsyncMock)
    @patch(f"{_MP_PATCH}.get_redis", new_callable=AsyncMock)
    def test_heatmap_empty_db_returns_empty_list(
        self, mock_get_redis: AsyncMock, mock_db_fetch: AsyncMock
    ) -> None:
        """Redis cache miss + DB도 빈 결과일 때 빈 리스트를 반환한다."""
        # Redis: cache miss
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.set = AsyncMock()
        mock_get_redis.return_value = redis_mock

        # DB: 빈 결과
        mock_db_fetch.return_value = []

        client = _build_mp_client()
        resp = client.get(f"{API_MP}/sectors/heatmap")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 0

        # DB fetch 호출 확인
        mock_db_fetch.assert_called_once()


class TestHeatmapResultCachedAfterDbQuery:
    """GET /api/v1/marketplace/sectors/heatmap — DB fallback 후 Redis 캐싱."""

    @patch("src.utils.db_client.fetch", new_callable=AsyncMock)
    @patch(f"{_MP_PATCH}.get_redis", new_callable=AsyncMock)
    def test_heatmap_result_cached_after_db_query(
        self, mock_get_redis: AsyncMock, mock_db_fetch: AsyncMock
    ) -> None:
        """DB fallback 후 결과가 Redis에 캐싱되는지 검증한다 (redis.set 호출 확인)."""
        # Redis: cache miss
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.set = AsyncMock()
        mock_get_redis.return_value = redis_mock

        # DB fallback 결과
        mock_db_fetch.return_value = [
            {
                "sector": "IT",
                "stock_count": 100,
                "avg_change_pct": 2.50,
                "total_market_cap": 800000000000,
                "total_volume": 30000000,
            },
        ]

        client = _build_mp_client()
        resp = client.get(f"{API_MP}/sectors/heatmap")
        assert resp.status_code == 200

        # redis.set이 호출되었는지 확인
        redis_mock.set.assert_called_once()

        # 캐시 키와 TTL 검증
        call_args = redis_mock.set.call_args
        assert call_args[0][0] == "redis:cache:sector_heatmap"

        # 저장된 데이터가 올바른지 검증
        cached_json = call_args[0][1]
        cached_data = json.loads(cached_json)
        assert isinstance(cached_data, list)
        assert len(cached_data) == 1
        assert cached_data[0]["sector"] == "IT"
        assert cached_data[0]["stock_count"] == 100
        assert cached_data[0]["avg_change_pct"] == 2.5

        # TTL 300초 (5분) 검증
        assert call_args[1]["ex"] == 300
