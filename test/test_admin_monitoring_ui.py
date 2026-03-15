"""
test/test_admin_monitoring_ui.py — 관리 모니터링 UI API 엔드포인트 테스트

5개 기능의 백엔드 API 테스트:
1. 에이전트 로그/제어 (pause/resume)
2. 시스템 헬스 모니터링
3. 데이터 레이크(S3) 관리
4. 알림 히스토리 + 통계
5. 감사 추적
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# 1. 에이전트 Pause / Resume 엔드포인트
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentPauseResume(unittest.IsolatedAsyncioTestCase):
    """POST /agents/{agent_id}/pause, /agents/{agent_id}/resume"""

    @patch("src.api.routers.agents.publish_message", new_callable=AsyncMock)
    async def test_pause_agent_success(self, mock_pub):
        from src.api.routers.agents import pause_agent

        result = await pause_agent("collector_agent", {})
        self.assertIn("일시정지", result["message"])
        mock_pub.assert_awaited_once()
        payload = json.loads(mock_pub.call_args[0][1])
        self.assertEqual(payload["type"], "pause_request")
        self.assertEqual(payload["agent_id"], "collector_agent")

    @patch("src.api.routers.agents.publish_message", new_callable=AsyncMock)
    async def test_resume_agent_success(self, mock_pub):
        from src.api.routers.agents import resume_agent

        result = await resume_agent("collector_agent", {})
        self.assertIn("재개", result["message"])
        mock_pub.assert_awaited_once()
        payload = json.loads(mock_pub.call_args[0][1])
        self.assertEqual(payload["type"], "resume_request")

    async def test_pause_unknown_agent_404(self):
        from fastapi import HTTPException
        from src.api.routers.agents import pause_agent

        with self.assertRaises(HTTPException) as ctx:
            await pause_agent("unknown_agent_xyz", {})
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_resume_unknown_agent_404(self):
        from fastapi import HTTPException
        from src.api.routers.agents import resume_agent

        with self.assertRaises(HTTPException) as ctx:
            await resume_agent("unknown_agent_xyz", {})
        self.assertEqual(ctx.exception.status_code, 404)


# ──────────────────────────────────────────────────────────────────────────────
# 2. 시스템 헬스 모니터링 라우터
# ──────────────────────────────────────────────────────────────────────────────


class TestSystemHealthRouter(unittest.IsolatedAsyncioTestCase):
    """GET /system/overview, /system/metrics"""

    @patch("src.api.routers.system_health.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.system_health.fetchval", new_callable=AsyncMock)
    @patch("src.api.routers.system_health.check_heartbeat", new_callable=AsyncMock)
    async def test_health_overview(self, mock_hb, mock_val, mock_row):
        mock_val.return_value = 1
        mock_hb.return_value = True
        mock_row.return_value = {"recorded_at": "2026-03-16T12:00:00Z"}

        with patch("src.api.routers.system_health.get_redis", new_callable=AsyncMock) as mock_redis_fn:
            redis_mock = AsyncMock()
            redis_mock.ping = AsyncMock(return_value=True)
            mock_redis_fn.return_value = redis_mock

            with patch("src.api.routers.system_health._get_s3_client") as mock_s3:
                s3_client = MagicMock()
                s3_client.head_bucket = MagicMock()
                mock_s3.return_value = s3_client

                with patch("src.api.routers.system_health.get_settings") as mock_settings:
                    mock_settings.return_value = MagicMock(s3_bucket_name="test-bucket")

                    from src.api.routers.system_health import get_health_overview
                    result = await get_health_overview({})

                    self.assertEqual(result.overall_status, "healthy")
                    self.assertEqual(len(result.services), 3)
                    self.assertEqual(result.agent_summary.total, 9)

    @patch("src.api.routers.system_health.fetch", new_callable=AsyncMock)
    @patch("src.api.routers.system_health.fetchrow", new_callable=AsyncMock)
    async def test_system_metrics(self, mock_row, mock_fetch):
        mock_row.side_effect = [
            {"error_count": 2, "total_count": 100},
            {"cnt": 5},
            {"cnt": 20},
        ]
        mock_fetch.return_value = []

        from src.api.routers.system_health import get_system_metrics
        result = await get_system_metrics({})

        self.assertEqual(result.error_count_24h, 2)
        self.assertEqual(result.total_heartbeats_24h, 100)
        self.assertEqual(result.active_agents, 5)
        self.assertEqual(result.db_table_count, 20)


# ──────────────────────────────────────────────────────────────────────────────
# 3. 데이터 레이크 관리 라우터
# ──────────────────────────────────────────────────────────────────────────────


class TestDatalakeRouter(unittest.IsolatedAsyncioTestCase):
    """GET /datalake/overview, /datalake/objects"""

    @patch("src.api.routers.datalake.get_settings")
    @patch("src.api.routers.datalake._get_s3_client")
    async def test_datalake_overview(self, mock_s3, mock_settings):
        mock_settings.return_value = MagicMock(s3_bucket_name="test-bucket")
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {"Contents": [{"Key": "ticks/2026/data.parquet", "Size": 1024}]}
        ]
        client = MagicMock()
        client.get_paginator.return_value = paginator_mock
        mock_s3.return_value = client

        from src.api.routers.datalake import get_datalake_overview
        result = await get_datalake_overview({})

        self.assertEqual(result.bucket_name, "test-bucket")
        self.assertEqual(result.total_objects, 1)
        self.assertEqual(result.total_size_bytes, 1024)
        self.assertEqual(len(result.prefixes), 1)
        self.assertEqual(result.prefixes[0]["prefix"], "ticks")

    @patch("src.api.routers.datalake.get_settings")
    @patch("src.api.routers.datalake._get_s3_client")
    async def test_list_objects(self, mock_s3, mock_settings):
        from datetime import datetime
        mock_settings.return_value = MagicMock(s3_bucket_name="test-bucket")
        client = MagicMock()
        client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "data/file1.parquet", "Size": 512, "LastModified": datetime(2026, 3, 16)}
            ],
            "CommonPrefixes": [{"Prefix": "data/sub/"}],
        }
        mock_s3.return_value = client

        from src.api.routers.datalake import list_datalake_objects
        result = await list_datalake_objects({}, prefix="data/", limit=100, delimiter="/")

        self.assertEqual(result.prefix, "data/")
        self.assertEqual(len(result.objects), 1)
        self.assertEqual(result.objects[0].key, "data/file1.parquet")
        self.assertEqual(result.common_prefixes, ["data/sub/"])

    @patch("src.api.routers.datalake.get_settings")
    @patch("src.api.routers.datalake._get_s3_client")
    async def test_delete_object(self, mock_s3, mock_settings):
        mock_settings.return_value = MagicMock(s3_bucket_name="test-bucket")
        client = MagicMock()
        client.delete_object = MagicMock()
        mock_s3.return_value = client

        from src.api.routers.datalake import delete_object
        result = await delete_object({}, key="data/file1.parquet")

        self.assertIn("삭제", result["message"])
        client.delete_object.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 4. 알림 통계 엔드포인트
# ──────────────────────────────────────────────────────────────────────────────


class TestNotificationStats(unittest.IsolatedAsyncioTestCase):
    """GET /notifications/stats"""

    @patch("src.api.routers.notifications.fetch", new_callable=AsyncMock)
    async def test_notification_stats(self, mock_fetch):
        mock_fetch.side_effect = [
            # First call — stats aggregate
            [{"total": 100, "success_count": 95, "fail_count": 5, "last_24h": 10}],
            # Second call — by_type breakdown
            [{"event_type": "trade", "cnt": 60, "ok": 58}],
            # Third call — daily
            [{"date": "2026-03-16", "total": 10, "success": 9, "fail": 1}],
        ]

        from src.api.routers.notifications import get_notification_stats
        result = await get_notification_stats({})

        self.assertEqual(result["total"], 100)
        self.assertEqual(result["success_rate"], 95.0)
        self.assertEqual(len(result["by_type"]), 1)
        self.assertEqual(len(result["daily"]), 1)


# ──────────────────────────────────────────────────────────────────────────────
# 5. 감사 추적 라우터
# ──────────────────────────────────────────────────────────────────────────────


class TestAuditRouter(unittest.IsolatedAsyncioTestCase):
    """GET /audit/trail, /audit/summary"""

    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    async def test_audit_trail(self, mock_fetch, mock_row):
        mock_fetch.return_value = [
            {
                "id": 1,
                "audit_type": "security",
                "event_source": "operational",
                "summary": "보안 감사 통과",
                "details": None,
                "success": True,
                "actor": "system",
                "created_at": "2026-03-16T12:00:00Z",
            }
        ]
        mock_row.return_value = {"cnt": 1}

        from src.api.routers.audit import get_audit_trail
        result = await get_audit_trail(
            {}, audit_type=None, from_date=None, to_date=None, page=1, per_page=30
        )

        self.assertEqual(result.total, 1)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].audit_type, "security")

    @patch("src.api.routers.audit.fetch", new_callable=AsyncMock)
    @patch("src.api.routers.audit.fetchrow", new_callable=AsyncMock)
    async def test_audit_summary(self, mock_row, mock_fetch):
        mock_row.return_value = {
            "total": 50, "cnt_24h": 10, "cnt_7d": 30, "pass_count": 45
        }
        mock_fetch.return_value = [
            {"audit_type": "security", "cnt": 20},
            {"audit_type": "notification", "cnt": 30},
        ]

        from src.api.routers.audit import get_audit_summary
        result = await get_audit_summary({})

        self.assertEqual(result.total_events, 50)
        self.assertEqual(result.events_24h, 10)
        self.assertEqual(result.pass_rate, 90.0)
        self.assertEqual(len(result.by_type), 2)


# ──────────────────────────────────────────────────────────────────────────────
# 6. Pydantic 모델 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestPydanticModels(unittest.TestCase):
    """Pydantic 모델 직렬화 검증"""

    def test_service_status_model(self):
        from src.api.routers.system_health import ServiceStatus
        s = ServiceStatus(name="PostgreSQL", status="ok", latency_ms=1.5)
        self.assertEqual(s.name, "PostgreSQL")
        self.assertEqual(s.status, "ok")

    def test_datalake_overview_model(self):
        from src.api.routers.datalake import DataLakeOverview
        d = DataLakeOverview(
            bucket_name="test",
            total_objects=10,
            total_size_bytes=1024,
            total_size_display="1.0 KB",
            prefixes=[],
        )
        self.assertEqual(d.total_objects, 10)

    def test_audit_trail_item_model(self):
        from src.api.routers.audit import AuditTrailItem
        a = AuditTrailItem(
            id=1,
            audit_type="security",
            event_source="operational",
            summary="test",
            created_at="2026-03-16T00:00:00Z",
        )
        self.assertEqual(a.audit_type, "security")

    def test_format_size_helper(self):
        from src.api.routers.datalake import _format_size
        self.assertIn("B", _format_size(500))
        self.assertIn("KB", _format_size(2048))
        self.assertIn("MB", _format_size(5 * 1024 * 1024))
        self.assertIn("GB", _format_size(3 * 1024 * 1024 * 1024))


# ──────────────────────────────────────────────────────────────────────────────
# 7. AST 구문 검증 (전체 새 파일)
# ──────────────────────────────────────────────────────────────────────────────


class TestASTValidation(unittest.TestCase):
    """모든 새 파일의 Python AST 구문 검증"""

    def test_all_new_files_parse(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        files = [
            root / "src" / "api" / "routers" / "system_health.py",
            root / "src" / "api" / "routers" / "datalake.py",
            root / "src" / "api" / "routers" / "audit.py",
            root / "src" / "api" / "routers" / "agents.py",
            root / "src" / "api" / "routers" / "notifications.py",
            root / "src" / "api" / "main.py",
        ]
        for f in files:
            with self.subTest(file=str(f)):
                self.assertTrue(f.exists(), f"{f} does not exist")
                ast.parse(f.read_text())


if __name__ == "__main__":
    unittest.main()
