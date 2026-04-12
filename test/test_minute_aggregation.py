"""
test/test_minute_aggregation.py -- ohlcv_minute 집계 함수 및 모델 단위 테스트

DB 없이 실행 가능하도록 src.utils.db_client의 함수를 mock합니다.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── 공통 mock 헬퍼 ──────────────────────────────────────────────────────────


class FakeRecord:
    """asyncpg.Record를 흉내 내어 dict(rec)이 동작하는 가짜 레코드."""

    def __init__(self, d: dict):
        self._d = d

    def __iter__(self):
        return iter(self._d.items())

    def keys(self):
        return self._d.keys()

    def values(self):
        return self._d.values()

    def items(self):
        return self._d.items()

    def __getitem__(self, k):
        return self._d[k]

    def get(self, k, default=None):
        return self._d.get(k, default)

    def __contains__(self, k):
        return k in self._d


# ── OhlcvMinute 모델 ──────────────────────────────────────────────────────


class TestOhlcvMinuteModel:
    def test_valid_construction(self) -> None:
        from src.db.models import OhlcvMinute

        bar = OhlcvMinute(
            instrument_id="005930.KS",
            bucket_at=datetime(2026, 4, 10, 10, 30),
            open=70000,
            high=71000,
            low=69000,
            close=70500,
            volume=15000,
            trade_count=42,
            vwap=70250.50,
        )
        assert bar.instrument_id == "005930.KS"
        assert bar.open == 70000
        assert bar.high == 71000
        assert bar.low == 69000
        assert bar.close == 70500
        assert bar.volume == 15000
        assert bar.trade_count == 42
        assert bar.vwap == 70250.50

    def test_defaults(self) -> None:
        from src.db.models import OhlcvMinute

        bar = OhlcvMinute(
            instrument_id="005930.KS",
            bucket_at=datetime(2026, 4, 10, 10, 30),
            open=70000,
            high=71000,
            low=69000,
            close=70500,
        )
        assert bar.volume == 0
        assert bar.trade_count == 0
        assert bar.vwap == 0.0

    def test_bucket_at_is_datetime(self) -> None:
        from src.db.models import OhlcvMinute

        ts = datetime(2026, 4, 10, 14, 25)
        bar = OhlcvMinute(
            instrument_id="005930.KS",
            bucket_at=ts,
            open=70000,
            high=70000,
            low=70000,
            close=70000,
        )
        assert bar.bucket_at == ts


# ── aggregate_ticks_to_minutes ─────────────────────────────────────────────


class TestAggregateTicksToMinutes:
    @pytest.mark.asyncio
    async def test_basic_call(self) -> None:
        """mock DB로 집계 함수 호출 → INSERT 결과 파싱 확인."""
        from src.db.queries import aggregate_ticks_to_minutes

        with patch(
            "src.db.queries.execute",
            new_callable=AsyncMock,
            return_value="INSERT 0 150",
        ) as mock_exec:
            count = await aggregate_ticks_to_minutes(
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

        assert count == 150
        mock_exec.assert_awaited_once()
        sql = mock_exec.call_args.args[0]
        assert "ohlcv_minute" in sql
        assert "tick_data" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        """tick_data에 데이터가 없으면 0건 반환."""
        from src.db.queries import aggregate_ticks_to_minutes

        with patch(
            "src.db.queries.execute",
            new_callable=AsyncMock,
            return_value="INSERT 0 0",
        ):
            count = await aggregate_ticks_to_minutes(
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_none_result(self) -> None:
        """execute()가 None을 반환해도 안전하게 0 반환."""
        from src.db.queries import aggregate_ticks_to_minutes

        with patch(
            "src.db.queries.execute",
            new_callable=AsyncMock,
            return_value=None,
        ):
            count = await aggregate_ticks_to_minutes(
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

        assert count == 0


# ── fetch_minute_bars ──────────────────────────────────────────────────────


class TestFetchMinuteBars:
    @pytest.mark.asyncio
    async def test_returns_formatted_rows(self) -> None:
        """mock DB에서 분봉 조회 → dict 리스트 반환."""
        from src.db.queries import fetch_minute_bars

        mock_row = FakeRecord({
            "instrument_id": "005930.KS",
            "bucket_at": datetime(2026, 4, 10, 10, 30),
            "open": 70000,
            "high": 71000,
            "low": 69000,
            "close": 70500,
            "volume": 15000,
            "trade_count": 42,
            "vwap": 70250.50,
        })

        with patch(
            "src.db.queries.fetch",
            new_callable=AsyncMock,
            return_value=[mock_row],
        ) as mock_f:
            result = await fetch_minute_bars(
                "005930.KS",
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

        assert len(result) == 1
        assert result[0]["instrument_id"] == "005930.KS"
        assert result[0]["open"] == 70000
        assert result[0]["close"] == 70500
        assert result[0]["vwap"] == 70250.50
        mock_f.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        """데이터 없으면 빈 리스트 반환."""
        from src.db.queries import fetch_minute_bars

        with patch(
            "src.db.queries.fetch",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await fetch_minute_bars(
                "005930.KS",
                datetime(2026, 4, 10, 9, 0),
                datetime(2026, 4, 10, 15, 30),
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_query_uses_correct_parameters(self) -> None:
        """SQL 쿼리에 올바른 파라미터가 전달되는지 확인."""
        from src.db.queries import fetch_minute_bars

        start = datetime(2026, 4, 10, 9, 0)
        end = datetime(2026, 4, 10, 15, 30)

        with patch(
            "src.db.queries.fetch",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_f:
            await fetch_minute_bars("005930.KS", start, end)

        args = mock_f.call_args.args
        assert args[1] == "005930.KS"
        assert args[2] == start
        assert args[3] == end
        sql = args[0]
        assert "ohlcv_minute" in sql
        assert "ORDER BY bucket_at ASC" in sql
