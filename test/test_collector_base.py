"""
test/test_collector_base.py — _CollectorBase 베이스 클래스 테스트

초기화, 티커 해석, heartbeat, Redis 캐시, KIS 인증 로직 검증.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

KST = ZoneInfo("Asia/Seoul")
pytestmark = [pytest.mark.unit]


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KIS_APP_KEY", "fake-key")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")


@pytest.fixture()
def collector(_env):
    from src.agents.collector import CollectorAgent
    return CollectorAgent(agent_id="test_base")


# =============================================================================
# 초기화 검증
# =============================================================================


class TestCollectorBaseInit:
    """_CollectorBase 초기화 검증."""

    def test_agent_id_default(self, _env):
        from src.agents.collector import CollectorAgent
        agent = CollectorAgent()
        assert agent.agent_id == "collector_agent"

    def test_agent_id_custom(self, collector):
        assert collector.agent_id == "test_base"

    def test_tick_buffer_empty(self, collector):
        assert collector._tick_buffer == []

    def test_tick_buffer_last_flush_zero(self, collector):
        assert collector._tick_buffer_last_flush == 0.0

    def test_last_tick_at_none(self, collector):
        assert collector._last_tick_at is None

    def test_last_hb_db_at_none(self, collector):
        assert collector._last_hb_db_at is None

    def test_realtime_task_none(self, collector):
        assert collector._realtime_task is None

    def test_settings_loaded(self, collector):
        assert collector.settings is not None


# =============================================================================
# _account_scope
# =============================================================================


class TestAccountScope:
    """_account_scope 메서드 검증."""

    def test_paper_scope(self, _env, monkeypatch):
        monkeypatch.setenv("KIS_IS_PAPER_TRADING", "true")
        from src.agents.collector import CollectorAgent
        agent = CollectorAgent()
        assert agent._account_scope() == "paper"

    def test_real_scope(self, _env, monkeypatch):
        monkeypatch.setenv("KIS_IS_PAPER_TRADING", "false")
        from src.agents.collector import CollectorAgent
        agent = CollectorAgent()
        assert agent._account_scope() == "real"


# =============================================================================
# _resolve_tickers
# =============================================================================


class TestResolveTickers:
    """_resolve_tickers 메서드 검증."""

    def _mock_listing(self):
        """KRX 종목 리스트 mock DataFrame."""
        import pandas as pd
        return pd.DataFrame({
            "Code": ["005930", "000660", "035420", "999999"],
            "Name": ["삼성전자", "SK하이닉스", "NAVER", "테스트"],
            "Market": ["KOSPI", "KOSPI", "KOSPI", "ETF"],
        })

    def test_resolve_tickers_limit(self, collector):
        """limit 미만으로 종목 반환."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._mock_listing()
        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            result = collector._resolve_tickers(None, limit=2)
        assert len(result) == 2

    def test_resolve_tickers_specific(self, collector):
        """requested 리스트에 포함된 종목만 반환."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._mock_listing()
        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            result = collector._resolve_tickers(["005930"], limit=20)
        tickers = [t[0] for t in result]
        assert "005930" in tickers

    def test_resolve_tickers_excludes_non_market(self, collector):
        """KOSPI/KOSDAQ가 아닌 시장(ETF 등)은 제외."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._mock_listing()
        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            result = collector._resolve_tickers(None, limit=100)
        tickers = [t[0] for t in result]
        assert "999999" not in tickers

    def test_resolve_tickers_missing_added_with_default_market(self, collector):
        """requested에 있지만 리스팅에 없는 종목은 KOSPI로 추가."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._mock_listing()
        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            result = collector._resolve_tickers(["UNKNOWN_TICKER"], limit=20)
        tickers = [t[0] for t in result]
        assert "UNKNOWN_TICKER" in tickers
        # 시장은 기본 KOSPI
        idx = tickers.index("UNKNOWN_TICKER")
        assert result[idx][2] == "KOSPI"

    def test_resolve_tickers_returns_tuples(self, collector):
        """반환값이 (ticker, name, market) 튜플 리스트."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._mock_listing()
        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            result = collector._resolve_tickers(None, limit=1)
        assert len(result) == 1
        assert len(result[0]) == 3


# =============================================================================
# async resolve_tickers wrapper
# =============================================================================


class TestResolveTickers_Async:
    """resolve_tickers (async wrapper) 검증."""

    async def test_async_wrapper(self, collector):
        """async resolve_tickers가 _resolve_tickers 결과를 반환."""
        expected = [("005930", "삼성전자", "KOSPI")]
        with patch.object(collector, "_resolve_tickers", return_value=expected):
            result = await collector.resolve_tickers(["005930"], limit=1)
        assert result == expected


# =============================================================================
# _beat (heartbeat)
# =============================================================================


class TestBeat:
    """_beat 메서드 검증."""

    async def test_beat_calls_set_heartbeat(self, collector):
        """_beat이 Redis heartbeat를 설정."""
        with (
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock) as mock_hb,
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            await collector._beat("healthy", "test", {"mode": "daily"})
        mock_hb.assert_awaited_once()

    async def test_beat_inserts_db_heartbeat_first_call(self, collector):
        """첫 호출 시 DB에도 heartbeat 기록."""
        with (
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock) as mock_db,
        ):
            await collector._beat("healthy", "test", {"mode": "daily"})
        mock_db.assert_awaited_once()

    async def test_beat_skips_db_within_30_seconds(self, collector):
        """30초 이내 재호출 시 DB insert를 건너뜀."""
        collector._last_hb_db_at = datetime.utcnow()
        with (
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock) as mock_db,
        ):
            await collector._beat("healthy", "test", {"mode": "daily"})
        mock_db.assert_not_awaited()

    async def test_beat_force_db(self, collector):
        """force_db=True 이면 30초 이내라도 DB에 기록."""
        collector._last_hb_db_at = datetime.utcnow()
        with (
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock) as mock_db,
        ):
            await collector._beat("healthy", "test", {"mode": "daily"}, force_db=True)
        mock_db.assert_awaited_once()


# =============================================================================
# _cache_latest_tick
# =============================================================================


class TestCacheLatestTick:
    """_cache_latest_tick Redis 캐시 검증."""

    async def test_cache_tick_data(self, collector):
        """TickData 캐시가 Redis pipeline으로 수행."""
        from src.agents.collector.models import TickData

        tick = TickData(
            instrument_id="005930.KS",
            price=72000.0,
            volume=100000,
            timestamp_kst=datetime.now(KST),
            name="삼성전자",
        )

        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True] * 4)
        redis_mock = AsyncMock()
        redis_mock.pipeline = MagicMock(return_value=mock_pipe)

        with patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            await collector._cache_latest_tick(tick, source="test")

        mock_pipe.set.assert_called_once()
        mock_pipe.lpush.assert_called_once()
        mock_pipe.ltrim.assert_called_once()
        mock_pipe.expire.assert_called_once()
        mock_pipe.execute.assert_awaited_once()

    async def test_cache_market_data_point(self, collector):
        """MarketDataPoint 캐시도 동일 pipeline으로 수행."""
        from datetime import date

        from src.db.models import MarketDataPoint

        point = MarketDataPoint(
            instrument_id="005930.KS",
            name="삼성전자",
            market="KOSPI",
            traded_at=date.today(),
            open=71000.0,
            high=73000.0,
            low=70000.0,
            close=72000.0,
            volume=100000,
        )

        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True] * 4)
        redis_mock = AsyncMock()
        redis_mock.pipeline = MagicMock(return_value=mock_pipe)

        with patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            await collector._cache_latest_tick(point, source="fdr_daily")

        mock_pipe.execute.assert_awaited_once()


# =============================================================================
# _get_access_token
# =============================================================================


class TestGetAccessToken:
    """_get_access_token Redis 조회 검증."""

    async def test_returns_token_from_redis(self, collector):
        """Redis에 저장된 토큰 반환."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=json.dumps({"access_token": "fake-token"}))
        with patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            token = await collector._get_access_token()
        assert token == "fake-token"

    async def test_returns_none_when_no_token(self, collector):
        """Redis에 토큰이 없으면 None 반환."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        with patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            token = await collector._get_access_token()
        assert token is None

    async def test_returns_none_on_invalid_json(self, collector):
        """Redis에 저장된 값이 유효하지 않은 JSON이면 None 반환."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value="not-json")
        with patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            token = await collector._get_access_token()
        assert token is None


# =============================================================================
# _ensure_ws_approval_key
# =============================================================================


class TestEnsureWsApprovalKey:
    """_ensure_ws_approval_key KIS WebSocket 인증키 관리 검증."""

    async def test_returns_cached_key(self, collector):
        """Redis 캐시에 키가 있으면 바로 반환."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value="cached-approval-key")
        with patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            key = await collector._ensure_ws_approval_key()
        assert key == "cached-approval-key"

    async def test_raises_without_credentials(self, _env, monkeypatch):
        """KIS 자격증명 미설정 시 RuntimeError 발생."""
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        from src.agents.collector import CollectorAgent
        agent = CollectorAgent()

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        with (
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch.object(agent, "_has_kis_market_credentials", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="미설정"):
                await agent._ensure_ws_approval_key()

    async def test_fetches_from_api_on_cache_miss(self, collector):
        """캐시 미스 시 KIS API에서 발급 후 Redis 저장."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.set = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"approval_key": "new-key-from-api"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch.object(collector, "_has_kis_market_credentials", return_value=True),
            patch("src.agents.collector._base.httpx.AsyncClient", return_value=mock_client),
        ):
            key = await collector._ensure_ws_approval_key()

        assert key == "new-key-from-api"
        redis_mock.set.assert_awaited_once()


# =============================================================================
# _has_kis_market_credentials
# =============================================================================


class TestHasKisMarketCredentials:
    """_has_kis_market_credentials 검증."""

    def test_returns_bool(self, collector):
        """반환값이 bool 타입."""
        with patch("src.agents.collector._base.has_kis_credentials", return_value=True):
            assert collector._has_kis_market_credentials() is True

    def test_calls_has_kis_credentials(self, collector):
        """has_kis_credentials를 올바른 인자로 호출."""
        with patch("src.agents.collector._base.has_kis_credentials", return_value=False) as mock_fn:
            collector._has_kis_market_credentials()
        mock_fn.assert_called_once_with(
            collector.settings,
            collector._account_scope(),
            require_account_number=False,
        )
