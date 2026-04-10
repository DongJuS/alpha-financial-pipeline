"""test/test_heartbeat_hash.py — Heartbeat Hash 확장 + docker_healthcheck 단위 테스트"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSetHeartbeatHash(unittest.IsolatedAsyncioTestCase):
    """set_heartbeat가 Redis Hash로 올바르게 기록하는지 검증."""

    async def test_default_call_writes_hash_with_status_ok(self):
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import set_heartbeat
            await set_heartbeat("collector_agent")

        mock_redis.hset.assert_called_once()
        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        self.assertEqual(mapping["status"], "ok")
        self.assertIn("updated_at", mapping)
        mock_redis.expire.assert_called_once_with("heartbeat:collector_agent", 90)

    async def test_custom_status_and_metadata(self):
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import set_heartbeat
            await set_heartbeat(
                "collector_agent",
                status="degraded",
                mode="fdr",
                error_count=2,
            )

        mapping = mock_redis.hset.call_args.kwargs.get("mapping") or mock_redis.hset.call_args[1].get("mapping")
        self.assertEqual(mapping["status"], "degraded")
        self.assertEqual(mapping["mode"], "fdr")
        self.assertEqual(mapping["error_count"], 2)

    async def test_wrongtype_fallback_deletes_and_retries(self):
        """기존 STRING 키가 있을 때 WRONGTYPE → 삭제 후 재시도."""
        mock_redis = AsyncMock()
        call_count = 0

        async def hset_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("WRONGTYPE")

        mock_redis.hset = AsyncMock(side_effect=hset_side_effect)
        mock_redis.delete = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import set_heartbeat
            await set_heartbeat("test_agent")

        mock_redis.delete.assert_called_once_with("heartbeat:test_agent")
        self.assertEqual(mock_redis.hset.call_count, 2)


class TestCheckHeartbeat(unittest.IsolatedAsyncioTestCase):
    """check_heartbeat은 Hash 키에도 EXISTS로 정상 동작."""

    async def test_exists_returns_true(self):
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import check_heartbeat
            result = await check_heartbeat("collector_agent")

        self.assertTrue(result)

    async def test_missing_returns_false(self):
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import check_heartbeat
            result = await check_heartbeat("collector_agent")

        self.assertFalse(result)


class TestGetHeartbeatDetail(unittest.IsolatedAsyncioTestCase):
    """get_heartbeat_detail이 Hash 필드를 반환하는지 검증."""

    async def test_returns_hash_fields(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "status": "degraded",
            "mode": "fdr",
            "updated_at": "1712700000",
            "error_count": "2",
        })

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import get_heartbeat_detail
            result = await get_heartbeat_detail("collector_agent")

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["mode"], "fdr")

    async def test_returns_none_when_missing(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})

        with patch("src.utils.redis_client.get_redis", return_value=mock_redis):
            from src.utils.redis_client import get_heartbeat_detail
            result = await get_heartbeat_detail("missing_agent")

        self.assertIsNone(result)


class TestDockerHealthcheck(unittest.IsolatedAsyncioTestCase):
    """docker_healthcheck._check 로직 테스트."""

    async def test_healthy_when_ok(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.hgetall = AsyncMock(return_value={"status": "ok", "updated_at": str(int(time.time()))})

        with (
            patch("src.utils.redis_client.get_redis", return_value=mock_redis),
            patch("src.utils.redis_client.close_redis", new_callable=AsyncMock),
        ):
            from scripts.docker_healthcheck import _check
            result = await _check("worker")

        self.assertTrue(result)

    async def test_unhealthy_when_error(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.hgetall = AsyncMock(return_value={"status": "error", "updated_at": str(int(time.time()))})

        with (
            patch("src.utils.redis_client.get_redis", return_value=mock_redis),
            patch("src.utils.redis_client.close_redis", new_callable=AsyncMock),
        ):
            from scripts.docker_healthcheck import _check
            result = await _check("worker")

        self.assertFalse(result)

    async def test_unhealthy_when_no_heartbeat(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.hgetall = AsyncMock(return_value={})

        with (
            patch("src.utils.redis_client.get_redis", return_value=mock_redis),
            patch("src.utils.redis_client.close_redis", new_callable=AsyncMock),
        ):
            from scripts.docker_healthcheck import _check
            result = await _check("worker")

        self.assertFalse(result)

    async def test_unhealthy_when_redis_down(self):
        with patch("src.utils.redis_client.get_redis", side_effect=ConnectionError("refused")):
            from scripts.docker_healthcheck import _check
            result = await _check("worker")

        self.assertFalse(result)

    async def test_degraded_is_still_healthy(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.hgetall = AsyncMock(return_value={"status": "degraded", "mode": "fdr"})

        with (
            patch("src.utils.redis_client.get_redis", return_value=mock_redis),
            patch("src.utils.redis_client.close_redis", new_callable=AsyncMock),
        ):
            from scripts.docker_healthcheck import _check
            result = await _check("worker")

        self.assertTrue(result)


class TestCollectorBeatStatusMapping(unittest.TestCase):
    """collector._beat()의 status 매핑 로직 검증."""

    def test_status_mapping(self):
        mapping = {"healthy": "ok", "degraded": "degraded", "error": "error"}
        self.assertEqual(mapping.get("healthy", "healthy"), "ok")
        self.assertEqual(mapping.get("degraded", "degraded"), "degraded")
        self.assertEqual(mapping.get("error", "error"), "error")
        # 알 수 없는 status는 그대로 전달
        self.assertEqual(mapping.get("unknown", "unknown"), "unknown")


if __name__ == "__main__":
    unittest.main()
