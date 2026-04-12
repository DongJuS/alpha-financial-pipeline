"""
test/test_minute_archive.py — ohlcv_minute S3 Parquet 아카이브 테스트

archive_minute_bars(), check_archive_marker(), OHLCV_MINUTE_SCHEMA 검증.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

pytestmark = [pytest.mark.unit]


class TestOHLCVMinuteSchema:
    """OHLCV_MINUTE_SCHEMA 정합성 검증."""

    def test_schema_registered(self) -> None:
        """SCHEMAS dict에 OHLCV_MINUTE이 등록되어 있는지 확인."""
        from src.services.datalake import DataType, SCHEMAS

        assert DataType.OHLCV_MINUTE in SCHEMAS

    def test_schema_fields(self) -> None:
        """스키마 필드가 올바른지 확인."""
        from src.services.datalake import OHLCV_MINUTE_SCHEMA

        field_names = [f.name for f in OHLCV_MINUTE_SCHEMA]
        expected = [
            "instrument_id",
            "bucket_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trade_count",
            "vwap",
        ]
        assert field_names == expected

    def test_enum_value(self) -> None:
        """DataType.OHLCV_MINUTE 열거형 값 확인."""
        from src.services.datalake import DataType

        assert DataType.OHLCV_MINUTE.value == "ohlcv_minute"

    def test_parquet_serialization(self) -> None:
        """OHLCV_MINUTE_SCHEMA로 Parquet 직렬화 성공 확인."""
        from src.services.datalake import OHLCV_MINUTE_SCHEMA, _to_parquet_bytes

        records = [
            {
                "instrument_id": "005930",
                "bucket_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
                "open": 72000,
                "high": 73000,
                "low": 71000,
                "close": 72500,
                "volume": 150000,
                "trade_count": 320,
                "vwap": 72250.5,
            }
        ]
        data = _to_parquet_bytes(records, OHLCV_MINUTE_SCHEMA)
        assert isinstance(data, bytes)
        assert data[:4] == b"PAR1"


class TestArchiveMinuteBars:
    """archive_minute_bars() 함수 검증."""

    @pytest.mark.asyncio
    async def test_archive_minute_bars_empty(self) -> None:
        """데이터 없을 때 빈 리스트 반환."""
        from src.services.datalake import archive_minute_bars

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]):
            result = await archive_minute_bars(2026, 1)

        assert result == []

    @pytest.mark.asyncio
    async def test_archive_minute_bars_groups_by_instrument(self) -> None:
        """종목별로 파일이 분리되어 업로드되는지 확인."""
        from src.services.datalake import archive_minute_bars

        rows = [
            {
                "instrument_id": "005930",
                "bucket_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
                "open": 72000,
                "high": 73000,
                "low": 71000,
                "close": 72500,
                "volume": 150000,
                "trade_count": 320,
                "vwap": 72250.5,
            },
            {
                "instrument_id": "005930",
                "bucket_at": datetime(2026, 1, 15, 9, 31, tzinfo=timezone.utc),
                "open": 72500,
                "high": 72800,
                "low": 72400,
                "close": 72700,
                "volume": 80000,
                "trade_count": 180,
                "vwap": 72600.0,
            },
            {
                "instrument_id": "000660",
                "bucket_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
                "open": 150000,
                "high": 152000,
                "low": 149000,
                "close": 151000,
                "volume": 50000,
                "trade_count": 120,
                "vwap": 150500.0,
            },
        ]

        uploaded_keys: list[str] = []

        async def _mock_upload(data: bytes, key: str, **kwargs) -> str:  # type: ignore[no-untyped-def]
            uploaded_keys.append(key)
            return f"s3://bucket/{key}"

        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=rows),
            patch(
                "src.services.datalake._upload_with_retry",
                new_callable=AsyncMock,
                side_effect=_mock_upload,
            ),
        ):
            result = await archive_minute_bars(2026, 1)

        # 2 종목 + 1 마커 = 3 업로드
        assert len(result) == 2
        parquet_keys = [k for k in uploaded_keys if k.endswith(".parquet")]
        marker_keys = [k for k in uploaded_keys if k.endswith("_ARCHIVED")]
        assert len(parquet_keys) == 2
        assert len(marker_keys) == 1

        # 키 구조 확인
        for key in parquet_keys:
            assert key.startswith("ohlcv_minute/year=2026/month=01/")
        assert "005930.parquet" in parquet_keys[0] or "005930.parquet" in parquet_keys[1]
        assert "000660.parquet" in parquet_keys[0] or "000660.parquet" in parquet_keys[1]

    @pytest.mark.asyncio
    async def test_archive_marker_created(self) -> None:
        """아카이브 후 마커 파일이 생성되는지 확인."""
        from src.services.datalake import archive_minute_bars

        rows = [
            {
                "instrument_id": "005930",
                "bucket_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
                "open": 72000,
                "high": 73000,
                "low": 71000,
                "close": 72500,
                "volume": 150000,
                "trade_count": 320,
                "vwap": 72250.5,
            },
        ]

        uploaded_keys: list[str] = []
        uploaded_data: list[bytes] = []

        async def _mock_upload(data: bytes, key: str, **kwargs) -> str:  # type: ignore[no-untyped-def]
            uploaded_keys.append(key)
            uploaded_data.append(data)
            return f"s3://bucket/{key}"

        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=rows),
            patch(
                "src.services.datalake._upload_with_retry",
                new_callable=AsyncMock,
                side_effect=_mock_upload,
            ),
        ):
            await archive_minute_bars(2026, 1)

        marker_keys = [k for k in uploaded_keys if k.endswith("_ARCHIVED")]
        assert len(marker_keys) == 1
        assert marker_keys[0] == "ohlcv_minute/year=2026/month=01/_ARCHIVED"

        # 마커 데이터는 b"archived"
        marker_idx = uploaded_keys.index(marker_keys[0])
        assert uploaded_data[marker_idx] == b"archived"

    @pytest.mark.asyncio
    async def test_archive_december_boundary(self) -> None:
        """12월 아카이브 시 연도 경계를 올바르게 처리하는지 확인."""
        from src.services.datalake import archive_minute_bars

        with patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=[]) as mock_fetch:
            await archive_minute_bars(2026, 12)

        # fetch 호출 시 start=2026-12-01, end=2027-01-01
        call_args = mock_fetch.call_args
        assert "2026-12-01" in call_args.args[1]
        assert "2027-01-01" in call_args.args[2]

    @pytest.mark.asyncio
    async def test_archive_upload_failure_partial(self) -> None:
        """일부 종목 업로드 실패 시에도 나머지는 계속 진행."""
        from src.services.datalake import archive_minute_bars

        rows = [
            {
                "instrument_id": "005930",
                "bucket_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
                "open": 72000,
                "high": 73000,
                "low": 71000,
                "close": 72500,
                "volume": 150000,
                "trade_count": 320,
                "vwap": 72250.5,
            },
            {
                "instrument_id": "000660",
                "bucket_at": datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
                "open": 150000,
                "high": 152000,
                "low": 149000,
                "close": 151000,
                "volume": 50000,
                "trade_count": 120,
                "vwap": 150500.0,
            },
        ]

        call_count = 0

        async def _mock_upload(data: bytes, key: str, **kwargs) -> str:  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("S3 unreachable")
            return f"s3://bucket/{key}"

        with (
            patch("src.db.queries.fetch", new_callable=AsyncMock, return_value=rows),
            patch(
                "src.services.datalake._upload_with_retry",
                new_callable=AsyncMock,
                side_effect=_mock_upload,
            ),
        ):
            result = await archive_minute_bars(2026, 1)

        # 첫 종목 실패, 두 번째 종목 성공 → 1 URI
        assert len(result) == 1


class TestCheckArchiveMarker:
    """check_archive_marker() 함수 검증."""

    @pytest.mark.asyncio
    async def test_check_archive_marker_exists(self) -> None:
        """마커 존재 시 True 반환."""
        from src.services.datalake import check_archive_marker

        with patch(
            "src.utils.s3_client.object_exists",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await check_archive_marker(2026, 1)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_archive_marker_missing(self) -> None:
        """마커 없을 시 False 반환."""
        from src.services.datalake import check_archive_marker

        with patch(
            "src.utils.s3_client.object_exists",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await check_archive_marker(2026, 1)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_archive_marker_exception(self) -> None:
        """S3 예외 시 False 반환 (안전한 실패)."""
        from src.services.datalake import check_archive_marker

        with patch(
            "src.utils.s3_client.object_exists",
            new_callable=AsyncMock,
            side_effect=ConnectionError("S3 down"),
        ):
            result = await check_archive_marker(2026, 1)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_archive_marker_key_format(self) -> None:
        """올바른 S3 키로 조회하는지 확인."""
        from src.services.datalake import check_archive_marker

        with patch(
            "src.utils.s3_client.object_exists",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_exists:
            await check_archive_marker(2026, 3)

        mock_exists.assert_awaited_once_with(
            "ohlcv_minute/year=2026/month=03/_ARCHIVED"
        )
