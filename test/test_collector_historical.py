"""
test/test_collector_historical.py — _HistoricalMixin 과거 데이터 수집 테스트

fetch_historical_ohlcv, _fetch_historical_daily, _fetch_historical_intraday,
check_data_exists 검증.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
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
    return CollectorAgent(agent_id="test_historical")


def _make_fdr_df(periods=5, start="2026-01-02"):
    dates = pd.date_range(start, periods=periods, freq="B")
    return pd.DataFrame(
        {
            "Open": [70000 + i * 100 for i in range(periods)],
            "High": [71000 + i * 100 for i in range(periods)],
            "Low": [69000 + i * 100 for i in range(periods)],
            "Close": [70500 + i * 100 for i in range(periods)],
            "Volume": [1000000 + i * 10000 for i in range(periods)],
        },
        index=dates,
    )


# =============================================================================
# fetch_historical_ohlcv dispatcher
# =============================================================================


class TestFetchHistoricalOhlcv:
    """fetch_historical_ohlcv 가 interval에 따라 올바른 메서드 호출."""

    async def test_daily_interval_delegates(self, collector):
        """interval='daily' -> _fetch_historical_daily 호출."""
        with patch.object(
            collector, "_fetch_historical_daily", new_callable=AsyncMock, return_value=[]
        ) as mock_daily:
            await collector.fetch_historical_ohlcv(
                "005930", "2026-01-01", "2026-01-31", interval="daily",
            )
        mock_daily.assert_awaited_once()

    async def test_minute_interval_delegates(self, collector):
        """interval='minute' -> _fetch_historical_intraday 호출."""
        with patch.object(
            collector, "_fetch_historical_intraday", new_callable=AsyncMock, return_value=[]
        ) as mock_intra:
            await collector.fetch_historical_ohlcv(
                "005930", "2026-01-01", "2026-01-31", interval="minute",
            )
        mock_intra.assert_awaited_once()

    async def test_default_name_uses_ticker(self, collector):
        """name 미지정 시 ticker를 name으로 사용."""
        with patch.object(
            collector, "_fetch_historical_daily", new_callable=AsyncMock, return_value=[]
        ) as mock_daily:
            await collector.fetch_historical_ohlcv(
                "005930", "2026-01-01", "2026-01-31",
            )
        call_args = mock_daily.call_args
        assert call_args[0][3] == "005930"  # name argument


# =============================================================================
# _fetch_historical_daily
# =============================================================================


class TestFetchHistoricalDaily:
    """_fetch_historical_daily FDR 기반 과거 일봉 수집."""

    async def test_normal_returns_points(self, collector):
        """정상 수집 시 MarketDataPoint 리스트 반환 + DB upsert."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(3)

        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True] * 4)
        redis_mock = AsyncMock()
        redis_mock.pipeline = MagicMock(return_value=mock_pipe)

        with (
            patch.object(collector, "_load_fdr", return_value=mock_fdr),
            patch("src.db.queries.upsert_market_data", new_callable=AsyncMock, return_value=3),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
        ):
            points = await collector._fetch_historical_daily(
                "005930", "2026-01-01", "2026-01-10", "삼성전자", "KOSPI",
            )

        assert len(points) == 3
        assert all(p.instrument_id == "005930.KS" for p in points)

    async def test_empty_returns_empty(self, collector):
        """빈 DataFrame이면 빈 리스트 + DB upsert 미호출."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = pd.DataFrame()

        with (
            patch.object(collector, "_load_fdr", return_value=mock_fdr),
            patch("src.db.queries.upsert_market_data", new_callable=AsyncMock) as mock_upsert,
        ):
            points = await collector._fetch_historical_daily(
                "999999", "2026-01-01", "2026-01-10", "테스트", "KOSPI",
            )

        assert points == []
        mock_upsert.assert_not_awaited()

    async def test_redis_cache_updated_on_success(self, collector):
        """수집 성공 시 최신 point로 Redis 캐시 갱신."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(2)

        mock_pipe = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.lpush = MagicMock()
        mock_pipe.ltrim = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[True] * 4)
        redis_mock = AsyncMock()
        redis_mock.pipeline = MagicMock(return_value=mock_pipe)

        with (
            patch.object(collector, "_load_fdr", return_value=mock_fdr),
            patch("src.db.queries.upsert_market_data", new_callable=AsyncMock, return_value=2),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
        ):
            points = await collector._fetch_historical_daily(
                "005930", "2026-01-01", "2026-01-10", "삼성전자", "KOSPI",
            )

        # Redis pipeline이 실행되었어야 함
        mock_pipe.execute.assert_awaited()


# =============================================================================
# _fetch_historical_intraday
# =============================================================================


class TestFetchHistoricalIntraday:
    """_fetch_historical_intraday KIS REST 분봉 수집."""

    async def test_no_token_returns_empty(self, collector):
        """토큰 미설정 시 빈 리스트 반환."""
        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value=None):
            points = await collector._fetch_historical_intraday(
                "005930", "2026-01-02", "2026-01-02", "삼성전자", "KOSPI",
            )
        assert points == []

    async def test_successful_intraday_collection(self, collector):
        """KIS REST API 응답을 일별로 집계."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "output2": [
                {"stck_oprc": "70000", "stck_hgpr": "71000", "stck_lwpr": "69000",
                 "stck_prpr": "70500", "cntg_vol": "1000"},
                {"stck_oprc": "70500", "stck_hgpr": "71500", "stck_lwpr": "70000",
                 "stck_prpr": "71000", "cntg_vol": "2000"},
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.agents.collector._historical.httpx.AsyncClient", return_value=mock_client),
            patch("src.db.queries.upsert_market_data", new_callable=AsyncMock, return_value=1),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            points = await collector._fetch_historical_intraday(
                "005930", "2026-01-02", "2026-01-02", "삼성전자", "KOSPI",
            )

        assert len(points) == 1
        p = points[0]
        assert p.open == 70000.0
        assert p.high == 71500.0  # max of 71000, 71500
        assert p.low == 69000.0  # min of 69000, 70000
        assert p.close == 71000.0  # last close
        assert p.volume == 3000  # 1000 + 2000

    async def test_api_error_logged_and_continues(self, collector):
        """API 에러 시 해당 날짜 건너뛰고 다음 날짜 진행."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("API down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="fake-token"),
            patch("src.agents.collector._historical.httpx.AsyncClient", return_value=mock_client),
            patch("src.agents.collector._historical.insert_collector_error", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            points = await collector._fetch_historical_intraday(
                "005930", "2026-01-02", "2026-01-02", "삼성전자", "KOSPI",
            )

        assert points == []


# =============================================================================
# check_data_exists
# =============================================================================


class TestCheckDataExists:
    """check_data_exists DB 조회 검증."""

    async def test_returns_count(self, collector):
        """정확한 count를 반환."""
        with patch("src.utils.db_client.fetchval", new_callable=AsyncMock, return_value=42):
            count = await collector.check_data_exists("005930")
        assert count == 42

    async def test_returns_zero_on_null(self, collector):
        """DB가 NULL을 반환하면 0."""
        with patch("src.utils.db_client.fetchval", new_callable=AsyncMock, return_value=None):
            count = await collector.check_data_exists("005930")
        assert count == 0

    async def test_accepts_instrument_id(self, collector):
        """instrument_id(005930.KS) 형태도 허용."""
        with patch("src.utils.db_client.fetchval", new_callable=AsyncMock, return_value=100) as mock_fv:
            count = await collector.check_data_exists("005930.KS")
        assert count == 100
        # SQL 쿼리에 instrument_id가 전달됨
        assert mock_fv.call_args[0][1] == "005930.KS"
