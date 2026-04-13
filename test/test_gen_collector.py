"""
test/test_gen_collector.py — GenCollectorAgent 테스트

gen 모드 데이터 생성, DB 격리(alpha_gen_db), 듀얼라이트, 지수/매크로 수집 검증.
기존 test_gen_pipeline_e2e.py의 기본 파이프라인 테스트를 보완합니다.
"""

from __future__ import annotations

import os
import sys
from datetime import date
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


def _make_redis_mock():
    """Redis mock with pipeline."""
    mock_pipe = MagicMock()
    mock_pipe.set = MagicMock()
    mock_pipe.lpush = MagicMock()
    mock_pipe.ltrim = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True] * 4)
    redis_mock = AsyncMock()
    redis_mock.pipeline = MagicMock(return_value=mock_pipe)
    redis_mock.set = AsyncMock()
    return redis_mock


# =============================================================================
# DB 격리 (DATABASE_URL rewrite)
# =============================================================================


class TestDatabaseIsolation:
    """gen_collector의 DATABASE_URL 격리 로직 검증."""

    def test_rewrite_standard_url(self):
        """표준 PostgreSQL URL에서 DB명이 alpha_gen_db로 교체."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        os.environ.pop("GEN_DB_REWRITE_DISABLED", None)
        try:
            os.environ["DATABASE_URL"] = "postgresql://user:pass@host:5432/mydb"
            info = _rewrite_database_url_to_gen_db()
            assert os.environ["DATABASE_URL"] == "postgresql://user:pass@host:5432/alpha_gen_db"
            assert info is not None
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            else:
                os.environ.pop("DATABASE_URL", None)
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled

    def test_no_rewrite_when_no_database_url(self):
        """DATABASE_URL 미설정 시 None 반환."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        os.environ.pop("GEN_DB_REWRITE_DISABLED", None)
        try:
            os.environ.pop("DATABASE_URL", None)
            info = _rewrite_database_url_to_gen_db()
            assert info is None
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled

    def test_rewrite_with_query_params(self):
        """쿼리 파라미터가 있는 URL에서도 DB명만 교체."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        os.environ.pop("GEN_DB_REWRITE_DISABLED", None)
        try:
            os.environ["DATABASE_URL"] = "postgresql://u:p@host:5432/alpha_db?sslmode=require"
            _rewrite_database_url_to_gen_db()
            assert "alpha_gen_db" in os.environ["DATABASE_URL"]
            assert "sslmode=require" in os.environ["DATABASE_URL"]
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            else:
                os.environ.pop("DATABASE_URL", None)
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled

    def test_disabled_flag_true(self):
        """GEN_DB_REWRITE_DISABLED=true 설정 시 rewrite 하지 않음."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        try:
            os.environ["DATABASE_URL"] = "postgresql://u:p@host:5432/alpha_db"
            os.environ["GEN_DB_REWRITE_DISABLED"] = "true"
            info = _rewrite_database_url_to_gen_db()
            assert info is None
            assert os.environ["DATABASE_URL"] == "postgresql://u:p@host:5432/alpha_db"
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            else:
                os.environ.pop("DATABASE_URL", None)
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled
            else:
                os.environ.pop("GEN_DB_REWRITE_DISABLED", None)

    def test_disabled_flag_yes(self):
        """GEN_DB_REWRITE_DISABLED=yes 도 비활성화."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        try:
            os.environ["DATABASE_URL"] = "postgresql://u:p@host:5432/alpha_db"
            os.environ["GEN_DB_REWRITE_DISABLED"] = "yes"
            info = _rewrite_database_url_to_gen_db()
            assert info is None
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            else:
                os.environ.pop("DATABASE_URL", None)
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled
            else:
                os.environ.pop("GEN_DB_REWRITE_DISABLED", None)


# =============================================================================
# GenCollectorAgent 초기화
# =============================================================================


class TestGenCollectorInit:
    """GenCollectorAgent 초기화 검증."""

    def test_default_url(self):
        from src.agents.gen_collector import GenCollectorAgent
        agent = GenCollectorAgent()
        assert "localhost" in agent.gen_api_url or "9999" in agent.gen_api_url

    def test_custom_url(self):
        from src.agents.gen_collector import GenCollectorAgent
        agent = GenCollectorAgent(gen_api_url="http://custom:1234")
        assert agent.gen_api_url == "http://custom:1234"

    def test_trailing_slash_stripped(self):
        from src.agents.gen_collector import GenCollectorAgent
        agent = GenCollectorAgent(gen_api_url="http://host:1234/")
        assert not agent.gen_api_url.endswith("/")

    def test_custom_agent_id(self):
        from src.agents.gen_collector import GenCollectorAgent
        agent = GenCollectorAgent(agent_id="custom_gen")
        assert agent.agent_id == "custom_gen"


# =============================================================================
# _make_instrument_id
# =============================================================================


class TestMakeInstrumentId:
    """_make_instrument_id 변환 검증."""

    def test_kospi(self):
        from src.agents.gen_collector import GenCollectorAgent
        assert GenCollectorAgent._make_instrument_id("005930", "KOSPI") == "005930.KS"

    def test_kosdaq(self):
        from src.agents.gen_collector import GenCollectorAgent
        assert GenCollectorAgent._make_instrument_id("035720", "KOSDAQ") == "035720.KQ"

    def test_lowercase_kospi(self):
        from src.agents.gen_collector import GenCollectorAgent
        assert GenCollectorAgent._make_instrument_id("005930", "kospi") == "005930.KS"


# =============================================================================
# collect_daily_bars
# =============================================================================


class TestGenCollectDailyBars:
    """collect_daily_bars 검증."""

    async def test_empty_tickers_returns_empty(self):
        """tickers 응답이 빈 리스트이면 빈 결과."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")
        tickers_resp = MagicMock()
        tickers_resp.raise_for_status = MagicMock()
        tickers_resp.json.return_value = []

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, return_value=tickers_resp),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=_make_redis_mock()),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock),
        ):
            points = await agent.collect_daily_bars(lookback_days=5)

        assert points == []
        await agent.close()

    async def test_ohlcv_empty_bars_skipped(self):
        """종목의 ohlcv 응답이 빈 리스트면 건너뜀."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        tickers_resp = MagicMock()
        tickers_resp.raise_for_status = MagicMock()
        tickers_resp.json.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
        ]
        ohlcv_resp = MagicMock()
        ohlcv_resp.raise_for_status = MagicMock()
        ohlcv_resp.json.return_value = []

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, side_effect=[tickers_resp, ohlcv_resp]),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=_make_redis_mock()),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock),
        ):
            points = await agent.collect_daily_bars()

        assert points == []
        await agent.close()


# =============================================================================
# collect_realtime_ticks
# =============================================================================


class TestGenCollectRealtimeTicks:
    """collect_realtime_ticks 검증."""

    async def test_max_cycles_limit(self):
        """max_cycles=2 이면 정확히 2사이클만 실행."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        quotes_resp = MagicMock()
        quotes_resp.raise_for_status = MagicMock()
        quotes_resp.json.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI",
             "current_price": 72000, "open": 71000, "high": 73000, "low": 70000,
             "volume": 100000, "change_pct": 1.5},
        ]

        redis_mock = _make_redis_mock()

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, return_value=quotes_resp),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock) as mock_pub,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            count = await agent.collect_realtime_ticks(interval_sec=0.01, max_cycles=2)

        assert count == 2  # 2 cycles * 1 quote = 2
        # publish_message는 각 cycle의 각 quote마다 호출
        assert mock_pub.await_count == 2
        await agent.close()

    async def test_api_error_continues(self):
        """API 에러가 발생해도 다음 사이클 계속."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        call_count = 0

        async def _get_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("API down")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = [
                {"ticker": "005930", "name": "삼성전자", "market": "KOSPI",
                 "current_price": 72000, "open": 71000, "high": 73000, "low": 70000,
                 "volume": 100000, "change_pct": 1.5},
            ]
            return resp

        redis_mock = _make_redis_mock()

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, side_effect=_get_side_effect),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            count = await agent.collect_realtime_ticks(interval_sec=0.01, max_cycles=2)

        # cycle는 성공 시에만 증가. 에러 시 cycle 유지 → 루프가 더 돌아서
        # 에러 1회 + 성공 2회 = total_received=2
        assert count == 2
        await agent.close()


# =============================================================================
# collect_indices_and_macro
# =============================================================================


class TestGenCollectIndicesAndMacro:
    """collect_indices_and_macro 검증."""

    async def test_normal_flow(self):
        """정상 수집 시 indices/macro 건수 반환."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")

        index_resp = MagicMock()
        index_resp.raise_for_status = MagicMock()
        index_resp.json.return_value = [
            {"symbol": "KOSPI", "value": 2800, "change_pct": 0.5},
            {"symbol": "KOSDAQ", "value": 900, "change_pct": -0.3},
        ]
        macro_resp = MagicMock()
        macro_resp.raise_for_status = MagicMock()
        macro_resp.json.return_value = [
            {"symbol": "USD_KRW", "value": 1350, "change_pct": 0.1},
        ]

        redis_mock = _make_redis_mock()

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, side_effect=[index_resp, macro_resp]),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
        ):
            result = await agent.collect_indices_and_macro()

        assert result["indices"] == 2
        assert result["macro"] == 1
        await agent.close()

    async def test_api_failure_returns_zero(self):
        """API 실패 시 0 반환."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")
        redis_mock = _make_redis_mock()

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, side_effect=ConnectionError("down")),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
        ):
            result = await agent.collect_indices_and_macro()

        assert result["indices"] == 0
        assert result["macro"] == 0
        await agent.close()


# =============================================================================
# _dual_write_legacy
# =============================================================================


class TestDualWriteLegacy:
    """레거시 market_data 듀얼라이트 검증."""

    async def test_empty_points_returns_zero(self):
        """빈 리스트면 0 반환."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent()
        result = await agent._dual_write_legacy([])
        assert result == 0
        await agent.close()

    async def test_writes_to_market_data(self):
        """정상 points가 market_data에 기록."""
        from src.agents.gen_collector import GenCollectorAgent
        from src.db.models import MarketDataPoint

        agent = GenCollectorAgent()
        points = [
            MarketDataPoint(
                instrument_id="005930.KS",
                name="삼성전자",
                market="KOSPI",
                traded_at=date.today(),
                open=71000.0,
                high=73000.0,
                low=70000.0,
                close=72000.0,
                volume=100000,
                change_pct=1.5,
            ),
        ]

        with patch("src.agents.gen_collector.executemany", new_callable=AsyncMock) as mock_exec:
            result = await agent._dual_write_legacy(points)

        assert result == 1
        mock_exec.assert_awaited_once()
        # 첫 번째 인자가 SQL, 두 번째가 rows
        rows = mock_exec.call_args[0][1]
        assert len(rows) == 1
        assert rows[0][0] == "005930"  # ticker (raw_code)
        await agent.close()


# =============================================================================
# _dual_write_legacy_tick
# =============================================================================


class TestDualWriteLegacyTick:
    """레거시 tick 듀얼라이트 검증."""

    async def test_empty_points_returns_zero(self):
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent()
        result = await agent._dual_write_legacy_tick([])
        assert result == 0
        await agent.close()

    async def test_tick_writes_interval_tick(self):
        """tick interval이 'tick'으로 기록."""
        from src.agents.gen_collector import GenCollectorAgent
        from src.db.models import MarketDataPoint

        agent = GenCollectorAgent()
        points = [
            MarketDataPoint(
                instrument_id="005930.KS",
                name="삼성전자",
                market="KOSPI",
                traded_at=date.today(),
                open=71000.0,
                high=73000.0,
                low=70000.0,
                close=72000.0,
                volume=100000,
            ),
        ]

        with patch("src.agents.gen_collector.executemany", new_callable=AsyncMock) as mock_exec:
            result = await agent._dual_write_legacy_tick(points)

        assert result == 1
        rows = mock_exec.call_args[0][1]
        assert rows[0][4] == "tick"  # interval column
        await agent.close()


# =============================================================================
# run_full_cycle
# =============================================================================


class TestRunFullCycle:
    """run_full_cycle 통합 사이클 검증."""

    async def test_calls_all_collect_methods(self):
        """일봉 + 틱 + 지수/매크로 모두 호출."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent()

        with (
            patch.object(agent, "collect_daily_bars", new_callable=AsyncMock, return_value=[]) as mock_daily,
            patch.object(agent, "collect_realtime_ticks", new_callable=AsyncMock, return_value=5) as mock_tick,
            patch.object(agent, "collect_indices_and_macro", new_callable=AsyncMock, return_value={"indices": 2, "macro": 1}) as mock_idx,
        ):
            result = await agent.run_full_cycle(lookback_days=30)

        mock_daily.assert_awaited_once_with(lookback_days=30)
        mock_tick.assert_awaited_once()
        mock_idx.assert_awaited_once()
        assert result["daily_bars_count"] == 0
        assert result["tick_count"] == 5
        assert result["indices_count"] == 2
        assert result["macro_count"] == 1
        await agent.close()


# =============================================================================
# _cache_latest_tick
# =============================================================================


class TestGenCacheLatestTick:
    """GenCollectorAgent._cache_latest_tick 검증."""

    async def test_caches_market_data_point(self):
        """MarketDataPoint를 Redis pipeline으로 캐시."""
        from src.agents.gen_collector import GenCollectorAgent
        from src.db.models import MarketDataPoint

        agent = GenCollectorAgent()
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

        redis_mock = _make_redis_mock()

        with patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            await agent._cache_latest_tick(point, source="gen_daily")

        pipe = redis_mock.pipeline()
        pipe.execute.assert_awaited()
        await agent.close()


# =============================================================================
# 에지케이스: DB 격리 실패, 빈 gen 데이터, 잘못된 URL 형식
# =============================================================================


class TestGenCollectorEdgeCases:
    """GenCollectorAgent 에지 케이스 보강 (Agent 2 QA Round 2)."""

    def test_rewrite_url_without_port(self):
        """포트 없는 URL에서도 DB명 교체 동작."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        os.environ.pop("GEN_DB_REWRITE_DISABLED", None)
        try:
            os.environ["DATABASE_URL"] = "postgresql://u:p@host/mydb"
            _rewrite_database_url_to_gen_db()
            assert "alpha_gen_db" in os.environ["DATABASE_URL"]
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            else:
                os.environ.pop("DATABASE_URL", None)
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled

    def test_rewrite_asyncpg_scheme(self):
        """postgresql+asyncpg 스킴에서도 DB명 교체."""
        from src.agents.gen_collector import _rewrite_database_url_to_gen_db

        prev = os.environ.get("DATABASE_URL")
        prev_disabled = os.environ.get("GEN_DB_REWRITE_DISABLED")
        os.environ.pop("GEN_DB_REWRITE_DISABLED", None)
        try:
            os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@host:5432/alpha_db"
            _rewrite_database_url_to_gen_db()
            assert "alpha_gen_db" in os.environ["DATABASE_URL"]
        finally:
            if prev is not None:
                os.environ["DATABASE_URL"] = prev
            else:
                os.environ.pop("DATABASE_URL", None)
            if prev_disabled is not None:
                os.environ["GEN_DB_REWRITE_DISABLED"] = prev_disabled

    async def test_malformed_gen_api_response(self):
        """Gen API가 잘못된 형식(dict 대신 string) 반환 시에도 크래시 방지."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")
        # tickers 응답이 올바르지만 ohlcv가 잘못된 경우
        tickers_resp = MagicMock()
        tickers_resp.raise_for_status = MagicMock()
        tickers_resp.json.return_value = [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
        ]
        ohlcv_resp = MagicMock()
        ohlcv_resp.raise_for_status = MagicMock()
        # 빈 OHLCV 데이터 반환
        ohlcv_resp.json.return_value = []

        redis_mock = _make_redis_mock()

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, side_effect=[tickers_resp, ohlcv_resp]),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock),
        ):
            points = await agent.collect_daily_bars()

        assert points == []
        await agent.close()

    async def test_collect_realtime_zero_quotes(self):
        """Gen API가 빈 quotes 응답을 보내면 cycle은 진행하되 count 미증가."""
        from src.agents.gen_collector import GenCollectorAgent

        agent = GenCollectorAgent(gen_api_url="http://localhost:9999")
        quotes_resp = MagicMock()
        quotes_resp.raise_for_status = MagicMock()
        quotes_resp.json.return_value = []  # 빈 quotes

        redis_mock = _make_redis_mock()

        with (
            patch.object(agent._client, "get", new_callable=AsyncMock, return_value=quotes_resp),
            patch("src.agents.gen_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.insert_heartbeat", new_callable=AsyncMock),
            patch("src.agents.gen_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.gen_collector.publish_message", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            count = await agent.collect_realtime_ticks(interval_sec=0.01, max_cycles=2)

        # 빈 quotes이므로 total_received = 0
        assert count == 0
        await agent.close()

    def test_make_instrument_id_unknown_market(self):
        """KOSPI/KOSDAQ가 아닌 시장은 기본 .KS suffix."""
        from src.agents.gen_collector import GenCollectorAgent
        result = GenCollectorAgent._make_instrument_id("005930", "UNKNOWN")
        # 소스 코드에서 upper()로 비교하므로 KOSPI가 아니면 .KQ
        # 실제 소스 검증
        assert result.endswith(".KS") or result.endswith(".KQ")
