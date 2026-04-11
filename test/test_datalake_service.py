"""
test/test_datalake_service.py — datalake.py Parquet/S3 저장 서비스 테스트

Parquet 스키마, 직렬화, S3 파티셔닝 경로, 재시도 로직, 각 store 함수 검증.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

pytestmark = [pytest.mark.unit]


# =============================================================================
# DataType Enum
# =============================================================================


class TestDataType:
    """DataType 열거형 검증."""

    def test_all_data_types(self):
        from src.services.datalake import DataType
        expected = {"daily_bars", "tick_data", "predictions", "orders",
                    "blend_results", "debate_transcripts", "rl_episodes"}
        actual = {dt.value for dt in DataType}
        assert actual == expected

    def test_schemas_registered_for_all(self):
        from src.services.datalake import SCHEMAS, DataType
        for dt in DataType:
            assert dt in SCHEMAS, f"{dt.value} 스키마 미등록"


# =============================================================================
# Parquet 스키마 검증
# =============================================================================


class TestSchemas:
    """각 스키마의 필드 수와 이름 검증."""

    def test_daily_bars_schema_fields(self):
        from src.services.datalake import DAILY_BARS_SCHEMA
        names = [f.name for f in DAILY_BARS_SCHEMA]
        assert "ticker" in names
        assert "close" in names
        assert "volume" in names
        assert "timestamp_kst" in names

    def test_tick_data_schema_fields(self):
        from src.services.datalake import TICK_DATA_SCHEMA
        names = [f.name for f in TICK_DATA_SCHEMA]
        assert "ticker" in names
        assert "price" in names
        assert "source" in names

    def test_predictions_schema_has_signal(self):
        from src.services.datalake import PREDICTIONS_SCHEMA
        names = [f.name for f in PREDICTIONS_SCHEMA]
        assert "signal" in names
        assert "confidence" in names

    def test_orders_schema_has_strategy_id(self):
        from src.services.datalake import ORDERS_SCHEMA
        names = [f.name for f in ORDERS_SCHEMA]
        assert "strategy_id" in names

    def test_blend_results_schema(self):
        from src.services.datalake import BLEND_RESULTS_SCHEMA
        names = [f.name for f in BLEND_RESULTS_SCHEMA]
        assert "blended_signal" in names
        assert "strategy_weights" in names

    def test_debate_transcripts_schema(self):
        from src.services.datalake import DEBATE_TRANSCRIPTS_SCHEMA
        names = [f.name for f in DEBATE_TRANSCRIPTS_SCHEMA]
        assert "proposer_text" in names
        assert "challenger_text" in names
        assert "consensus_signal" in names


# =============================================================================
# _to_parquet_bytes
# =============================================================================


class TestToParquetBytes:
    """_to_parquet_bytes 직렬화 검증."""

    def test_basic_serialization(self):
        from src.services.datalake import DAILY_BARS_SCHEMA, _to_parquet_bytes
        records = [{
            "ticker": "005930", "name": "삼성전자", "market": "KOSPI",
            "timestamp_kst": datetime(2026, 4, 11, 15, 30),
            "open": 71000, "high": 73000, "low": 70000, "close": 72000,
            "volume": 100000, "change_pct": 1.5,
            "market_cap": 500000000000, "foreigner_ratio": 55.0,
        }]
        data = _to_parquet_bytes(records, DAILY_BARS_SCHEMA)
        assert isinstance(data, bytes)
        assert data[:4] == b"PAR1"

    def test_none_fields_handled(self):
        """None 필드가 있어도 직렬화 성공."""
        from src.services.datalake import DAILY_BARS_SCHEMA, _to_parquet_bytes
        records = [{
            "ticker": "005930", "name": "삼성전자", "market": "KOSPI",
            "timestamp_kst": datetime(2026, 4, 11, 15, 30),
            "open": 71000, "high": 73000, "low": 70000, "close": 72000,
            "volume": 100000, "change_pct": None,
            "market_cap": None, "foreigner_ratio": None,
        }]
        data = _to_parquet_bytes(records, DAILY_BARS_SCHEMA)
        assert len(data) > 0

    def test_missing_fields_filled_with_none(self):
        """스키마에 있는 필드가 레코드에 없으면 None으로 채움."""
        from src.services.datalake import DAILY_BARS_SCHEMA, _to_parquet_bytes
        records = [{
            "ticker": "005930",
            "name": "삼성전자",
            # 나머지 필드 누락
        }]
        data = _to_parquet_bytes(records, DAILY_BARS_SCHEMA)
        assert isinstance(data, bytes)

    def test_multiple_records(self):
        """여러 레코드 직렬화."""
        from src.services.datalake import TICK_DATA_SCHEMA, _to_parquet_bytes
        records = [
            {"ticker": "005930", "price": 72000, "volume": 100, "timestamp_kst": datetime.now(), "change_pct": 1.0, "source": "test"},
            {"ticker": "000660", "price": 150000, "volume": 200, "timestamp_kst": datetime.now(), "change_pct": -0.5, "source": "test"},
        ]
        data = _to_parquet_bytes(records, TICK_DATA_SCHEMA)
        assert data[:4] == b"PAR1"


# =============================================================================
# _make_s3_key
# =============================================================================


class TestMakeS3Key:
    """Hive-style 파티션 키 생성 검증."""

    def test_date_only_partitioning(self):
        from src.services.datalake import DataType, _make_s3_key
        key = _make_s3_key(DataType.DAILY_BARS, date(2026, 4, 11))
        assert key.startswith("daily_bars/date=2026-04-11/")
        assert key.endswith(".parquet")

    def test_date_hour_partitioning(self):
        from src.services.datalake import DataType, _make_s3_key
        key = _make_s3_key(DataType.TICK_DATA, date(2026, 4, 11), hour=9)
        assert "date=2026-04-11" in key
        assert "hour=09" in key
        assert key.endswith(".parquet")

    def test_custom_suffix(self):
        from src.services.datalake import DataType, _make_s3_key
        key = _make_s3_key(DataType.TICK_DATA, date(2026, 4, 11), suffix="_500t")
        assert "_500t" in key

    def test_default_date_is_today(self):
        from src.services.datalake import DataType, _make_s3_key
        key = _make_s3_key(DataType.PREDICTIONS)
        today_str = date.today().isoformat()
        assert f"date={today_str}" in key

    def test_all_data_types_produce_valid_keys(self):
        from src.services.datalake import DataType, _make_s3_key
        for dt in DataType:
            key = _make_s3_key(dt, date(2026, 1, 1))
            assert key.startswith(dt.value + "/")
            assert "date=2026-01-01" in key

    def test_hour_zero_padded(self):
        from src.services.datalake import DataType, _make_s3_key
        key = _make_s3_key(DataType.TICK_DATA, hour=3)
        assert "hour=03" in key


# =============================================================================
# _upload_with_retry
# =============================================================================


class TestUploadWithRetry:
    """S3 업로드 재시도 로직 검증."""

    async def test_success_on_first_attempt(self):
        from src.services.datalake import _upload_with_retry
        with patch("src.services.datalake.upload_bytes", new_callable=AsyncMock, return_value="s3://bucket/key"):
            result = await _upload_with_retry(b"data", "key")
        assert result == "s3://bucket/key"

    async def test_retry_on_failure(self):
        """첫 번째 실패 후 두 번째 성공."""
        from src.services.datalake import _upload_with_retry

        call_count = 0

        async def _upload_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("S3 unavailable")
            return "s3://bucket/key"

        with (
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock, side_effect=_upload_side_effect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _upload_with_retry(b"data", "key")

        assert result == "s3://bucket/key"
        assert call_count == 2

    async def test_max_retries_exceeded_raises(self):
        """3회 실패 시 마지막 예외 전파."""
        from src.services.datalake import _upload_with_retry

        with (
            patch("src.services.datalake.upload_bytes", new_callable=AsyncMock, side_effect=ConnectionError("fail")),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(ConnectionError, match="fail"):
                await _upload_with_retry(b"data", "key")


# =============================================================================
# store_daily_bars
# =============================================================================


class TestStoreDailyBars:
    """store_daily_bars 검증."""

    async def test_empty_records_returns_none(self):
        from src.services.datalake import store_daily_bars
        assert await store_daily_bars([]) is None

    async def test_normal_upload(self):
        from src.services.datalake import store_daily_bars
        records = [{
            "ticker": "005930", "name": "삼성전자", "market": "KOSPI",
            "timestamp_kst": datetime(2026, 4, 11, 15, 30),
            "open": 71000, "high": 73000, "low": 70000, "close": 72000,
            "volume": 100000, "change_pct": 1.5,
            "market_cap": None, "foreigner_ratio": None,
        }]
        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test"):
            result = await store_daily_bars(records)
        assert result == "s3://test"

    async def test_upload_failure_returns_none(self):
        from src.services.datalake import store_daily_bars
        records = [{
            "ticker": "005930", "name": "삼성전자", "market": "KOSPI",
            "timestamp_kst": datetime(2026, 4, 11, 15, 30),
            "open": 71000, "high": 73000, "low": 70000, "close": 72000,
            "volume": 100000, "change_pct": 1.5,
            "market_cap": None, "foreigner_ratio": None,
        }]
        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await store_daily_bars(records)
        assert result is None


# =============================================================================
# store_tick_data
# =============================================================================


class TestStoreTickData:
    """store_tick_data 검증."""

    async def test_empty_returns_none(self):
        from src.services.datalake import store_tick_data
        assert await store_tick_data([]) is None

    async def test_normal_upload(self):
        from src.services.datalake import store_tick_data
        records = [{
            "ticker": "005930", "price": 72000, "volume": 100,
            "timestamp_kst": datetime.now(), "change_pct": 1.0, "source": "test",
        }]
        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test"):
            result = await store_tick_data(records)
        assert result == "s3://test"


# =============================================================================
# store_predictions
# =============================================================================


class TestStorePredictions:
    """store_predictions 검증."""

    async def test_empty_returns_none(self):
        from src.services.datalake import store_predictions
        assert await store_predictions([]) is None

    async def test_normal_upload(self):
        from src.services.datalake import store_predictions
        records = [{
            "agent_id": "agent_a", "llm_model": "claude", "strategy": "A",
            "ticker": "005930", "signal": "BUY", "confidence": 0.8,
            "target_price": 80000, "stop_loss": 65000,
            "reasoning_summary": "test", "trading_date": "2026-04-11",
            "is_shadow": False,
        }]
        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test"):
            result = await store_predictions(records)
        assert result is not None


# =============================================================================
# store_orders
# =============================================================================


class TestStoreOrders:
    """store_orders 검증."""

    async def test_empty_returns_none(self):
        from src.services.datalake import store_orders
        assert await store_orders([]) is None

    async def test_normal_upload(self):
        from src.services.datalake import store_orders
        records = [{
            "ticker": "005930", "name": "삼성전자", "signal": "BUY",
            "quantity": 10, "price": 72000, "signal_source": "strategy_a",
            "agent_id": "agent_a", "account_scope": "paper",
            "strategy_id": "A", "created_at": datetime.now(timezone.utc),
        }]
        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test"):
            result = await store_orders(records)
        assert result is not None


# =============================================================================
# store_blend_results
# =============================================================================


class TestStoreBlendResults:
    """store_blend_results 검증."""

    async def test_empty_returns_none(self):
        from src.services.datalake import store_blend_results
        assert await store_blend_results([]) is None


# =============================================================================
# store_debate_transcripts
# =============================================================================


class TestStoreDebateTranscripts:
    """store_debate_transcripts 검증."""

    async def test_empty_returns_none(self):
        from src.services.datalake import store_debate_transcripts
        assert await store_debate_transcripts([]) is None

    async def test_normal_upload(self):
        from src.services.datalake import store_debate_transcripts
        records = [{
            "transcript_id": 1, "ticker": "005930", "strategy": "B",
            "round_number": 1, "proposer_text": "buy", "challenger_text": "sell",
            "synthesizer_text": "hold", "consensus_signal": "BUY",
            "consensus_confidence": 0.7, "trading_date": "2026-04-11",
            "created_at": datetime.now(timezone.utc),
        }]
        with patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test"):
            result = await store_debate_transcripts(records)
        assert result is not None


# =============================================================================
# flush_ticks_to_s3
# =============================================================================


class TestFlushTicksToS3:
    """flush_ticks_to_s3 시간대별 그룹핑 검증."""

    async def test_no_ticks_returns_empty(self):
        from src.services.datalake import flush_ticks_to_s3
        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            result = await flush_ticks_to_s3(date(2026, 4, 11))
        assert result == []

    async def test_groups_by_hour(self):
        """시간대별로 그룹핑하여 별도 파일 생성."""
        from src.services.datalake import flush_ticks_to_s3

        rows = [
            {"ticker": "005930", "price": 72000, "volume": 100,
             "timestamp_kst": datetime(2026, 4, 11, 9, 30),
             "change_pct": 1.0, "source": "kis_ws"},
            {"ticker": "005930", "price": 72100, "volume": 200,
             "timestamp_kst": datetime(2026, 4, 11, 10, 0),
             "change_pct": 1.1, "source": "kis_ws"},
        ]

        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=rows),
            patch("src.services.datalake._upload_with_retry", new_callable=AsyncMock, return_value="s3://test") as mock_upload,
        ):
            result = await flush_ticks_to_s3(date(2026, 4, 11))

        # 2개 시간대 (9시, 10시) → 2개 파일
        assert len(result) == 2
        assert mock_upload.await_count == 2
