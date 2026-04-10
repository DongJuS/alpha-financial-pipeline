"""
test/test_approval_key_cache.py — approval_key Redis 캐싱 테스트

캐시 hit/miss 시나리오를 검증한다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")


@pytest.fixture()
def collector(_env):
    from src.agents.collector import CollectorAgent

    return CollectorAgent(agent_id="test_collector")


class TestApprovalKeyCacheHit:
    """Redis에 캐시된 approval_key가 있으면 KIS API를 호출하지 않는다."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_value(self, collector):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="cached-approval-key-abc")

        with patch("src.agents.collector._base.get_redis", return_value=mock_redis):
            result = await collector._ensure_ws_approval_key()

        assert result == "cached-approval-key-abc"
        mock_redis.get.assert_awaited_once()
        mock_redis.set.assert_not_awaited()


class TestApprovalKeyCacheMiss:
    """Redis에 캐시가 없으면 KIS API로 발급 후 Redis에 저장한다."""

    @pytest.mark.asyncio
    async def test_cache_miss_issues_and_stores(self, collector):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_response = MagicMock()
        mock_response.json.return_value = {"approval_key": "new-approval-key-xyz"}
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)

        from src.utils.redis_client import TTL_KIS_APPROVAL_KEY

        with (
            patch("src.agents.collector._base.get_redis", return_value=mock_redis),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            result = await collector._ensure_ws_approval_key()

        assert result == "new-approval-key-xyz"
        mock_redis.get.assert_awaited_once()
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][1] == "new-approval-key-xyz"
        assert call_args[1]["ex"] == TTL_KIS_APPROVAL_KEY
