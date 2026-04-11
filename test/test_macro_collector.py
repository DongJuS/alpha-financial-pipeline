"""
test/test_macro_collector.py — MacroCollector 매크로 지표 수집 테스트

해외지수, 환율, 원자재 수집, Redis 캐시 TTL, FDR 재시도, DB 저장 검증.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
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


def _make_fdr_df(close_values):
    """FDR DataReader 형태의 DataFrame 생성."""
    n = len(close_values)
    dates = pd.date_range("2026-04-01", periods=n, freq="B")
    return pd.DataFrame({"Close": close_values}, index=dates)


# =============================================================================
# Constants
# =============================================================================


class TestMacroCollectorConstants:
    """매크로 지표 정의 검증."""

    def test_foreign_indices_count(self):
        from src.agents.macro_collector import FOREIGN_INDICES
        assert len(FOREIGN_INDICES) == 6

    def test_currencies_count(self):
        from src.agents.macro_collector import CURRENCIES
        assert len(CURRENCIES) == 4

    def test_commodities_count(self):
        from src.agents.macro_collector import COMMODITIES
        assert len(COMMODITIES) == 3

    def test_foreign_indices_symbols(self):
        from src.agents.macro_collector import FOREIGN_INDICES
        assert "US500" in FOREIGN_INDICES
        assert "IXIC" in FOREIGN_INDICES

    def test_currencies_symbols(self):
        from src.agents.macro_collector import CURRENCIES
        assert "USD/KRW" in CURRENCIES

    def test_commodities_symbols(self):
        from src.agents.macro_collector import COMMODITIES
        assert "GC=F" in COMMODITIES  # Gold


# =============================================================================
# MacroCollector 초기화
# =============================================================================


class TestMacroCollectorInit:
    """MacroCollector 초기화 검증."""

    def test_default_agent_id(self):
        from src.agents.macro_collector import MacroCollector
        c = MacroCollector()
        assert c.agent_id == "macro_collector"

    def test_custom_agent_id(self):
        from src.agents.macro_collector import MacroCollector
        c = MacroCollector(agent_id="custom")
        assert c.agent_id == "custom"


# =============================================================================
# _fetch_indicator
# =============================================================================


class TestFetchIndicator:
    """_fetch_indicator FDR 조회 + 재시도 로직."""

    def test_normal_returns_tuple(self):
        """정상 데이터 반환 시 (value, change_pct, previous_close) 튜플."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df([5000.0, 5050.0])

        with patch.object(c, "_load_fdr", return_value=mock_fdr):
            result = c._fetch_indicator("US500", lookback_days=5)

        assert result is not None
        value, change_pct, prev_close = result
        assert value == 5050.0
        assert prev_close == 5000.0
        assert change_pct is not None
        assert abs(change_pct - 1.0) < 0.1  # ~1% 상승

    def test_empty_df_retries(self):
        """첫 번째 빈 응답 후 더 긴 lookback으로 재시도."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        mock_fdr = MagicMock()
        # 첫 번째 빈, 두 번째 정상
        mock_fdr.DataReader.side_effect = [pd.DataFrame(), _make_fdr_df([100.0])]

        with patch.object(c, "_load_fdr", return_value=mock_fdr):
            result = c._fetch_indicator("US500", lookback_days=5)

        assert result is not None
        assert mock_fdr.DataReader.call_count == 2

    def test_all_retries_fail_returns_none(self):
        """모든 재시도 실패 시 None 반환."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = pd.DataFrame()

        with patch.object(c, "_load_fdr", return_value=mock_fdr):
            result = c._fetch_indicator("INVALID", lookback_days=5)

        assert result is None
        assert mock_fdr.DataReader.call_count == 3  # 3회 재시도

    def test_close_zero_returns_none(self):
        """Close=0이면 None 반환."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df([0.0])

        with patch.object(c, "_load_fdr", return_value=mock_fdr):
            result = c._fetch_indicator("US500")

        assert result is None

    def test_single_row_no_change_pct(self):
        """단일 행이면 change_pct=None, previous_close=None."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        mock_fdr = MagicMock()
        mock_fdr.DataReader.return_value = _make_fdr_df([5000.0])

        with patch.object(c, "_load_fdr", return_value=mock_fdr):
            result = c._fetch_indicator("US500")

        assert result is not None
        value, change_pct, prev_close = result
        assert value == 5000.0
        assert change_pct is None
        assert prev_close is None

    def test_fdr_exception_retries(self):
        """FDR 예외 발생 시 재시도."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        mock_fdr = MagicMock()
        mock_fdr.DataReader.side_effect = [
            ValueError("FDR error"),
            _make_fdr_df([5000.0]),
        ]

        with patch.object(c, "_load_fdr", return_value=mock_fdr):
            result = c._fetch_indicator("US500", lookback_days=5)

        assert result is not None


# =============================================================================
# collect_foreign_indices
# =============================================================================


class TestCollectForeignIndices:
    """collect_foreign_indices 해외지수 수집."""

    async def test_all_success(self):
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()

        with patch.object(
            c, "_fetch_indicator", return_value=(5000.0, 1.0, 4950.0)
        ):
            indicators = await c.collect_foreign_indices()

        assert len(indicators) == 6
        assert all(i.category == "index" for i in indicators)
        assert all(i.source == "fdr" for i in indicators)

    async def test_partial_failure(self):
        """일부 실패해도 성공한 것만 반환."""
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()
        call_count = 0

        def _side_effect(fdr_symbol, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # 실패
            return (5000.0, 1.0, 4950.0)

        with patch.object(c, "_fetch_indicator", side_effect=_side_effect):
            indicators = await c.collect_foreign_indices()

        assert len(indicators) == 5  # 6개 중 1개 실패


# =============================================================================
# collect_currencies
# =============================================================================


class TestCollectCurrencies:
    """collect_currencies 환율 수집."""

    async def test_all_success(self):
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()

        with patch.object(
            c, "_fetch_indicator", return_value=(1350.0, 0.1, 1348.65)
        ):
            indicators = await c.collect_currencies()

        assert len(indicators) == 4
        assert all(i.category == "currency" for i in indicators)


# =============================================================================
# collect_commodities
# =============================================================================


class TestCollectCommodities:
    """collect_commodities 원자재 수집."""

    async def test_all_success(self):
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()

        with patch.object(
            c, "_fetch_indicator", return_value=(2000.0, 0.5, 1990.0)
        ):
            indicators = await c.collect_commodities()

        assert len(indicators) == 3
        assert all(i.category == "commodity" for i in indicators)


# =============================================================================
# collect_all
# =============================================================================


class TestCollectAll:
    """collect_all 통합 수집."""

    async def test_calls_all_sub_collectors(self):
        from src.agents.macro_collector import MacroCollector

        c = MacroCollector()

        with (
            patch.object(c, "collect_foreign_indices", new_callable=AsyncMock, return_value=[]) as mock_idx,
            patch.object(c, "collect_currencies", new_callable=AsyncMock, return_value=[]) as mock_cur,
            patch.object(c, "collect_commodities", new_callable=AsyncMock, return_value=[]) as mock_com,
        ):
            result = await c.collect_all()

        mock_idx.assert_awaited_once()
        mock_cur.assert_awaited_once()
        mock_com.assert_awaited_once()
        assert result == 0  # 빈 리스트

    async def test_saves_to_db_and_redis(self):
        from src.agents.macro_collector import MacroCollector
        from src.db.models import MacroIndicator

        c = MacroCollector()
        indicators = [
            MacroIndicator(
                category="index", symbol="US500", name="S&P 500",
                value=5000.0, change_pct=1.0, previous_close=4950.0,
                snapshot_date=datetime.now(KST).date(), source="fdr",
            ),
        ]

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock()

        with (
            patch.object(c, "collect_foreign_indices", new_callable=AsyncMock, return_value=indicators),
            patch.object(c, "collect_currencies", new_callable=AsyncMock, return_value=[]),
            patch.object(c, "collect_commodities", new_callable=AsyncMock, return_value=[]),
            patch("src.agents.macro_collector.upsert_macro_indicators", new_callable=AsyncMock, return_value=1),
            patch("src.agents.macro_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock),
            patch("src.agents.macro_collector.publish_message", new_callable=AsyncMock),
            patch("src.agents.macro_collector.set_heartbeat", new_callable=AsyncMock),
            patch("src.agents.macro_collector.insert_heartbeat", new_callable=AsyncMock),
        ):
            result = await c.collect_all()

        assert result == 1
        redis_mock.set.assert_awaited()


# =============================================================================
# _refresh_macro_cache
# =============================================================================


class TestRefreshMacroCache:
    """_refresh_macro_cache Redis 캐시 갱신."""

    async def test_groups_by_category(self):
        """카테고리별로 Redis 키가 생성."""
        from src.agents.macro_collector import MacroCollector
        from src.db.models import MacroIndicator

        c = MacroCollector()
        indicators = [
            MacroIndicator(
                category="index", symbol="US500", name="S&P 500",
                value=5000.0, snapshot_date=datetime.now(KST).date(), source="fdr",
            ),
            MacroIndicator(
                category="currency", symbol="USD/KRW", name="달러/원",
                value=1350.0, snapshot_date=datetime.now(KST).date(), source="fdr",
            ),
        ]

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock()

        with patch("src.agents.macro_collector.get_redis", new_callable=AsyncMock, return_value=redis_mock):
            await c._refresh_macro_cache(indicators)

        # index, currency 각각 한 번 → 총 2번
        assert redis_mock.set.await_count == 2
