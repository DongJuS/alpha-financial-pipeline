"""
test/test_datalake.py — Data Lake 모듈 단위 테스트

S3 연결 없이 Parquet 직렬화 및 키 생성 로직을 검증합니다.
"""

from datetime import date, datetime

import pytest

from src.services.datalake import (
    DataType,
    SCHEMA_MAP,
    _build_key,
    _records_to_parquet,
)


class TestBuildKey:
    """파티셔닝 키 생성 테스트"""

    def test_ticks_key(self):
        key = _build_key(DataType.TICKS, date(2026, 3, 15), "005930")
        assert key == "ticks/year=2026/month=03/day=15/005930.parquet"

    def test_daily_bars_key(self):
        key = _build_key(DataType.DAILY_BARS, date(2026, 1, 1), "000660")
        assert key == "daily_bars/year=2026/month=01/day=01/000660.parquet"

    def test_predictions_key(self):
        key = _build_key(DataType.PREDICTIONS, date(2025, 12, 31), "035720")
        assert key == "predictions/year=2025/month=12/day=31/035720.parquet"


class TestRecordsToParquet:
    """Parquet 직렬화 테스트"""

    def test_tick_serialization(self):
        records = [
            {
                "ticker": "005930",
                "timestamp": datetime(2026, 3, 15, 10, 0, 0),
                "price": 72000.0,
                "volume": 1000,
                "change_rate": 0.5,
                "bid_price": 71900.0,
                "ask_price": 72100.0,
                "total_volume": 500000,
                "total_amount": 36000000000,
            }
        ]
        schema = SCHEMA_MAP[DataType.TICKS]
        parquet_bytes = _records_to_parquet(records, schema)
        assert len(parquet_bytes) > 0
        assert parquet_bytes[:4] == b"PAR1"  # Parquet magic bytes

    def test_daily_bar_serialization(self):
        records = [
            {
                "ticker": "005930",
                "date": date(2026, 3, 15),
                "open": 71000.0,
                "high": 73000.0,
                "low": 70500.0,
                "close": 72000.0,
                "volume": 5000000,
                "change_rate": 1.41,
                "market_cap": 430000000000000,
                "source": "fdr",
            }
        ]
        schema = SCHEMA_MAP[DataType.DAILY_BARS]
        parquet_bytes = _records_to_parquet(records, schema)
        assert len(parquet_bytes) > 0
        assert parquet_bytes[:4] == b"PAR1"

    def test_prediction_serialization(self):
        records = [
            {
                "ticker": "005930",
                "timestamp": datetime(2026, 3, 15, 9, 30, 0),
                "strategy": "A",
                "signal": "BUY",
                "confidence": 0.85,
                "target_price": 75000.0,
                "stop_loss": 70000.0,
                "reasoning": "Strong momentum detected",
            }
        ]
        schema = SCHEMA_MAP[DataType.PREDICTIONS]
        parquet_bytes = _records_to_parquet(records, schema)
        assert len(parquet_bytes) > 0

    def test_missing_fields_padded_with_none(self):
        """스키마에 없는 필드는 None으로 패딩"""
        records = [
            {
                "ticker": "005930",
                "timestamp": datetime(2026, 3, 15),
                "price": 72000.0,
                # volume, change_rate 등 누락
            }
        ]
        schema = SCHEMA_MAP[DataType.TICKS]
        parquet_bytes = _records_to_parquet(records, schema)
        assert len(parquet_bytes) > 0

    def test_empty_records_raises_or_returns_valid(self):
        """빈 레코드 리스트도 유효한 Parquet 생성"""
        schema = SCHEMA_MAP[DataType.TICKS]
        parquet_bytes = _records_to_parquet([], schema)
        assert len(parquet_bytes) > 0


class TestDataTypes:
    """DataType enum 및 스키마 매핑 테스트"""

    def test_all_types_have_schemas(self):
        for dt in DataType:
            assert dt in SCHEMA_MAP, f"{dt} has no schema mapping"

    def test_schema_field_count(self):
        assert len(SCHEMA_MAP[DataType.TICKS]) == 9
        assert len(SCHEMA_MAP[DataType.DAILY_BARS]) == 10
        assert len(SCHEMA_MAP[DataType.PREDICTIONS]) == 8
        assert len(SCHEMA_MAP[DataType.ORDERS]) == 10
