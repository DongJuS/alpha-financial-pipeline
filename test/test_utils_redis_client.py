"""
test/test_utils_redis_client.py -- src/utils/redis_client.py 단위 테스트

실제 Redis 없이 mock으로 연결/TTL/pub-sub 동작을 검증합니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── 상수 검증 ───────────────────────────────────────────────────────────────


class TestConstants:
    def test_topic_names_defined(self):
        from src.utils.redis_client import (
            TOPIC_ALERTS,
            TOPIC_HEARTBEAT,
            TOPIC_MARKET_DATA,
            TOPIC_ORDERS,
            TOPIC_SIGNALS,
        )

        assert TOPIC_MARKET_DATA.startswith("redis:topic:")
        assert TOPIC_SIGNALS.startswith("redis:topic:")
        assert TOPIC_ORDERS.startswith("redis:topic:")
        assert TOPIC_HEARTBEAT.startswith("redis:topic:")
        assert TOPIC_ALERTS.startswith("redis:topic:")

    def test_ttl_values_positive(self):
        from src.utils.redis_client import (
            TTL_HEARTBEAT,
            TTL_KIS_TOKEN,
            TTL_KIS_APPROVAL_KEY,
            TTL_KRX_HOLIDAYS,
            TTL_LATEST_TICKS,
            TTL_REALTIME_SERIES,
            TTL_MACRO_CONTEXT,
            TTL_MARKET_INDEX,
            TTL_STOCK_MASTER,
        )

        assert TTL_HEARTBEAT > 0
        assert TTL_KIS_TOKEN > 0
        assert TTL_KIS_APPROVAL_KEY > 0
        assert TTL_KRX_HOLIDAYS > 0
        assert TTL_LATEST_TICKS > 0
        assert TTL_REALTIME_SERIES > 0
        assert TTL_MACRO_CONTEXT > 0
        assert TTL_MARKET_INDEX > 0
        assert TTL_STOCK_MASTER > 0

    def test_ttl_ordering(self):
        """TTL 값이 논리적으로 올바른 순서인지 확인."""
        from src.utils.redis_client import (
            TTL_HEARTBEAT,
            TTL_KIS_TOKEN,
            TTL_LATEST_TICKS,
            TTL_MARKET_INDEX,
        )

        # 실시간 캐시 < heartbeat < 토큰
        assert TTL_LATEST_TICKS < TTL_HEARTBEAT
        assert TTL_MARKET_INDEX < TTL_KIS_TOKEN

    def test_key_patterns_have_placeholders(self):
        from src.utils.redis_client import (
            KEY_HEARTBEAT,
            KEY_KIS_OAUTH_TOKEN,
            KEY_LATEST_TICKS,
        )

        assert "{agent_id}" in KEY_HEARTBEAT
        assert "{scope}" in KEY_KIS_OAUTH_TOKEN
        assert "{ticker}" in KEY_LATEST_TICKS


# ── kis_oauth_token_key / kis_approval_key ──────────────────────────────────


class TestKeyHelpers:
    def test_oauth_token_key_paper(self):
        from src.utils.redis_client import kis_oauth_token_key

        key = kis_oauth_token_key("paper")
        assert "paper" in key
        assert "real" not in key

    def test_oauth_token_key_real(self):
        from src.utils.redis_client import kis_oauth_token_key

        key = kis_oauth_token_key("real")
        assert "real" in key

    def test_oauth_token_key_normalizes(self):
        from src.utils.redis_client import kis_oauth_token_key

        # any non-"real" scope → "paper"
        key = kis_oauth_token_key("virtual")
        assert "paper" in key

    def test_approval_key_paper(self):
        from src.utils.redis_client import kis_approval_key

        key = kis_approval_key("paper")
        assert "paper" in key

    def test_approval_key_real(self):
        from src.utils.redis_client import kis_approval_key

        key = kis_approval_key("real")
        assert "real" in key


# ── publish_message ─────────────────────────────────────────────────────────


class TestPublishMessage:
    @pytest.mark.asyncio
    async def test_publish_calls_redis(self):
        from src.utils.redis_client import publish_message

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await publish_message("test:topic", '{"data": "hello"}')

        mock_redis.publish.assert_awaited_once_with("test:topic", '{"data": "hello"}')


# ── set_heartbeat ───────────────────────────────────────────────────────────


class TestSetHeartbeat:
    @pytest.mark.asyncio
    async def test_sets_hash_with_ttl(self):
        from src.utils.redis_client import set_heartbeat, TTL_HEARTBEAT

        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await set_heartbeat("test_agent", status="ok", mode="paper")

        mock_redis.hset.assert_awaited_once()
        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        if mapping is None:
            mapping = call_kwargs.kwargs.get("mapping")
        assert mapping is not None
        assert mapping["status"] == "ok"
        assert mapping["mode"] == "paper"

        mock_redis.expire.assert_awaited_once()
        expire_args = mock_redis.expire.call_args.args
        assert expire_args[1] == TTL_HEARTBEAT

    @pytest.mark.asyncio
    async def test_handles_wrongtype_error(self):
        """기존 STRING 키가 있을 때 삭제 후 재시도."""
        from src.utils.redis_client import set_heartbeat

        mock_redis = AsyncMock()
        # 첫 hset 호출에서 예외, 두 번째는 성공
        mock_redis.hset = AsyncMock(side_effect=[Exception("WRONGTYPE"), None])
        mock_redis.delete = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await set_heartbeat("test_agent")

        # delete가 호출됨
        mock_redis.delete.assert_awaited_once()
        # hset이 2번 호출됨
        assert mock_redis.hset.await_count == 2


# ── check_heartbeat ─────────────────────────────────────────────────────────


class TestCheckHeartbeat:
    @pytest.mark.asyncio
    async def test_returns_true_when_exists(self):
        from src.utils.redis_client import check_heartbeat

        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await check_heartbeat("test_agent")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_missing(self):
        from src.utils.redis_client import check_heartbeat

        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await check_heartbeat("test_agent")

        assert result is False


# ── get_heartbeat_detail ────────────────────────────────────────────────────


class TestGetHeartbeatDetail:
    @pytest.mark.asyncio
    async def test_returns_dict_when_exists(self):
        from src.utils.redis_client import get_heartbeat_detail

        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"status": "ok", "updated_at": "1234567890"})

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await get_heartbeat_detail("test_agent")

        assert result is not None
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self):
        from src.utils.redis_client import get_heartbeat_detail

        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})

        with patch("src.utils.redis_client.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await get_heartbeat_detail("nonexistent_agent")

        assert result is None


# ── close_redis ─────────────────────────────────────────────────────────────


class TestCloseRedis:
    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        import src.utils.redis_client as mod
        from src.utils.redis_client import close_redis

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        original = mod._redis_client
        mod._redis_client = mock_redis
        try:
            await close_redis()
            mock_redis.aclose.assert_awaited_once()
            assert mod._redis_client is None
        finally:
            mod._redis_client = original

    @pytest.mark.asyncio
    async def test_close_noop_when_none(self):
        import src.utils.redis_client as mod
        from src.utils.redis_client import close_redis

        original = mod._redis_client
        mod._redis_client = None
        try:
            await close_redis()  # should not raise
        finally:
            mod._redis_client = original
