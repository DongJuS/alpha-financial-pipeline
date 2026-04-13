"""
test/test_collector_daily.py — _DailyMixin FDR/Yahoo 일봉 수집 테스트

collect_daily_bars, _fetch_daily_bars, _yahoo_ticker, collect_yahoo_daily_bars 검증.
"""

from __future__ import annotations

import json
import os
import sys
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


@pytest.fixture()
def collector(_env):
    from src.agents.collector import CollectorAgent
    return CollectorAgent(agent_id="test_daily")


def _make_fdr_df(periods=3, start="2026-01-02"):
    """FDR DataReader 가 반환하는 형태의 DataFrame."""
    dates = pd.date_range(start, periods=periods, freq="B")
    return pd.DataFrame(
        {
            "Open": [70000 + i * 500 for i in range(periods)],
            "High": [71000 + i * 500 for i in range(periods)],
            "Low": [69000 + i * 500 for i in range(periods)],
            "Close": [70500 + i * 500 for i in range(periods)],
            "Volume": [1000000 + i * 100000 for i in range(periods)],
            "Change": [0.01] * periods,
        },
        index=dates,
    )


# =============================================================================
# _yahoo_ticker
# =============================================================================


class TestYahooTicker:
    """_yahoo_ticker 변환 검증."""

    def test_kospi_suffix(self, collector):
        assert collector._yahoo_ticker("005930", "KOSPI") == "005930.KS"

    def test_kosdaq_suffix(self, collector):
        assert collector._yahoo_ticker("035720", "KOSDAQ") == "035720.KQ"

    def test_already_has_dot_no_suffix(self, collector):
        """이미 '.'가 포함되어 있으면 그대로 반환."""
        assert collector._yahoo_ticker("005930.KS", "KOSPI") == "005930.KS"

    def test_other_market_gets_kq(self, collector):
        """KOSPI가 아닌 시장은 .KQ 접미사."""
        assert collector._yahoo_ticker("123456", "OTHER") == "123456.KQ"


# =============================================================================
# _fetch_daily_bars
# =============================================================================


class TestFetchDailyBars:
    """_fetch_daily_bars 동기 메서드 검증."""

    def test_returns_market_data_points(self, collector):
        """정상 데이터 반환 시 MarketDataPoint 리스트."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(3)

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("005930", "삼성전자", "KOSPI", 120)

        assert len(points) == 3
        assert all(p.instrument_id == "005930.KS" for p in points)
        assert all(p.name == "삼성전자" for p in points)
        assert all(p.market == "KOSPI" for p in points)

    def test_empty_df_returns_empty_list(self, collector):
        """빈 DataFrame이면 빈 리스트 반환."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = pd.DataFrame()

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("999999", "테스트", "KOSPI", 120)

        assert points == []

    def test_none_df_returns_empty_list(self, collector):
        """None DataFrame이면 빈 리스트 반환."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = None

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("999999", "테스트", "KOSPI", 120)

        assert points == []

    def test_skips_zero_close(self, collector):
        """Close 값이 0인 행은 건너뜀."""
        mock_fdr = MagicMock()
        dates = pd.date_range("2026-01-02", periods=2, freq="B")
        df = pd.DataFrame(
            {
                "Open": [70000, 0],
                "High": [71000, 0],
                "Low": [69000, 0],
                "Close": [70500, 0],
                "Volume": [1000000, 0],
            },
            index=dates,
        )
        mock_fdr.DataReader.return_value = df

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("005930", "삼성전자", "KOSPI", 120)

        assert len(points) == 1

    def test_change_pct_calculated(self, collector):
        """change_pct가 전일 종가 대비 계산."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(3)

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("005930", "삼성전자", "KOSPI", 120)

        # 첫 번째는 전일 종가가 없으므로 None일 수 있음 (compute_change_pct 구현에 따라)
        # 두 번째부터는 값이 있어야 함
        assert points[1].change_pct is not None or points[2].change_pct is not None

    def test_invalid_market_defaults_to_kospi(self, collector):
        """잘못된 시장코드는 KOSPI로 기본 설정."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(1)

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("005930", "삼성전자", "INVALID", 120)

        assert len(points) == 1
        assert points[0].market == "KOSPI"


# =============================================================================
# collect_daily_bars (async)
# =============================================================================


class TestCollectDailyBars:
    """collect_daily_bars 전체 흐름 검증."""

    async def test_full_pipeline(self, collector):
        """수집 → DB 저장 → S3 저장 → Redis 캐시 → Pub/Sub 발행."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930"],
            "Name": ["삼성전자"],
            "Market": ["KOSPI"],
        })
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
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, return_value=2) as mock_upsert,
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock),
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock, return_value="s3://test"),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock) as mock_pub,
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await collector.collect_daily_bars(tickers=["005930"], lookback_days=30)

        assert len(points) == 2
        mock_upsert.assert_awaited_once()
        mock_pub.assert_awaited_once()

        pub_data = json.loads(mock_pub.call_args[0][1])
        assert pub_data["type"] == "data_ready"

    async def test_error_handling_per_ticker(self, collector):
        """개별 종목 수집 실패 시 다른 종목은 계속 수집."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930", "000660"],
            "Name": ["삼성전자", "SK하이닉스"],
            "Market": ["KOSPI", "KOSPI"],
        })
        # 첫 번째는 정상, 두 번째는 예외
        call_count = 0

        def _side_effect(ticker, start_date):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("FDR 다운")
            return _make_fdr_df(1)

        mock_fdr.DataReader.side_effect = _side_effect

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
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, return_value=1),
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock) as mock_err,
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock, return_value="s3://test"),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock),
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await collector.collect_daily_bars(tickers=["005930", "000660"])

        # 첫 번째 종목의 1건만 수집됨
        assert len(points) == 1
        # 에러 기록이 삽입됨
        mock_err.assert_awaited_once()

    async def test_s3_failure_does_not_block(self, collector):
        """S3 저장 실패 시 나머지 파이프라인은 계속 진행."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930"],
            "Name": ["삼성전자"],
            "Market": ["KOSPI"],
        })
        mock_fdr.DataReader.return_value = _make_fdr_df(1)

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
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, return_value=1),
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock),
            patch("src.services.datalake.store_daily_bars", new_callable=AsyncMock, side_effect=ConnectionError("S3 down")),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock) as mock_pub,
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await collector.collect_daily_bars(tickers=["005930"])

        assert len(points) == 1
        # S3 실패 후에도 Pub/Sub 발행
        mock_pub.assert_awaited_once()


# =============================================================================
# 에지케이스: FDR 타임아웃 / 중복 upsert / 빈 응답 / 음수 Close
# =============================================================================


class TestDailyBarsEdgeCases:
    """_DailyMixin 에지 케이스 보강 (Agent 2 QA Round 2)."""

    def test_negative_close_skipped(self, collector):
        """Close 값이 음수인 행은 건너뜀 (close_value <= 0 조건)."""
        mock_fdr = MagicMock()
        dates = pd.date_range("2026-01-02", periods=2, freq="B")
        df = pd.DataFrame(
            {
                "Open": [70000, 70000],
                "High": [71000, 71000],
                "Low": [69000, 69000],
                "Close": [70500, -100],
                "Volume": [1000000, 500000],
            },
            index=dates,
        )
        mock_fdr.DataReader.return_value = df

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("005930", "삼성전자", "KOSPI", 120)

        assert len(points) == 1
        assert points[0].close == 70500.0

    def test_fdr_exception_propagates_from_fetch(self, collector):
        """FDR DataReader가 예외를 발생시키면 _fetch_daily_bars에서 전파."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.side_effect = TimeoutError("FDR timeout after 30s")

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            with pytest.raises(TimeoutError):
                collector._fetch_daily_bars("005930", "삼성전자", "KOSPI", 120)

    async def test_collect_daily_bars_fdr_timeout_per_ticker(self, collector):
        """개별 종목 FDR 타임아웃 시 에러 기록 후 계속 진행."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930", "000660"],
            "Name": ["삼성전자", "SK하이닉스"],
            "Market": ["KOSPI", "KOSPI"],
        })
        mock_fdr.DataReader.side_effect = TimeoutError("FDR timeout")

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
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, return_value=0),
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock) as mock_err,
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock),
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await collector.collect_daily_bars(tickers=["005930", "000660"])

        assert points == []
        assert mock_err.await_count == 2  # 2종목 모두 에러

    def test_change_pct_first_row_is_none(self, collector):
        """첫 번째 행의 change_pct는 previous_close가 None이므로 None."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(1)

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("005930", "삼성전자", "KOSPI", 120)

        # compute_change_pct(close, None) -> None
        assert points[0].change_pct is None

    def test_kosdaq_market_preserved(self, collector):
        """KOSDAQ 종목은 instrument_id에 .KQ suffix 적용."""
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df(1)

        with patch.object(collector, "_load_fdr", return_value=mock_fdr):
            points = collector._fetch_daily_bars("035720", "카카오", "KOSDAQ", 120)

        assert points[0].instrument_id == "035720.KQ"
        assert points[0].market == "KOSDAQ"

    async def test_collect_daily_bars_all_empty_data(self, collector):
        """모든 종목의 데이터가 빈 경우에도 정상 완료 (upsert 0건)."""
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({
            "Code": ["005930", "000660"],
            "Name": ["삼성전자", "SK하이닉스"],
            "Market": ["KOSPI", "KOSPI"],
        })
        mock_fdr.DataReader.return_value = pd.DataFrame()

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
            patch("src.agents.collector._daily.upsert_market_data", new_callable=AsyncMock, return_value=0) as mock_upsert,
            patch("src.agents.collector._daily.insert_collector_error", new_callable=AsyncMock),
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock),
            patch("src.agents.collector._base.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.collector._daily.publish_message", new_callable=AsyncMock) as mock_pub,
            patch("src.agents.collector._base.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.collector._base.insert_heartbeat", new_callable=AsyncMock),
        ):
            points = await collector.collect_daily_bars(tickers=["005930", "000660"])

        assert points == []
        mock_upsert.assert_awaited_once()
        # 빈 데이터여도 Pub/Sub 발행 (count=0)
        mock_pub.assert_awaited_once()
        pub_data = json.loads(mock_pub.call_args[0][1])
        assert pub_data["count"] == 0
