"""
src/services/datalake.py — Data Lake 업로드 서비스

모든 데이터(틱, 일봉, 매크로, 검색, 리서치, 예측)를 Parquet 포맷으로
S3(MinIO)에 저장하는 통합 서비스입니다.

파티셔닝 구조:
    s3://alpha-lake/{data_type}/year={YYYY}/month={MM}/day={DD}/{filename}.parquet

데이터 타입:
    - ticks       : KIS WebSocket 실시간 체결 데이터
    - daily_bars  : FDR/yfinance 일봉 데이터
    - macro       : 지수/환율/원자재 매크로 데이터
    - search      : SearXNG 검색 결과
    - research    : LLM 리서치 결과
    - predictions : 전략 예측 시그널
    - orders      : 주문/체결 기록
"""

from __future__ import annotations

import io
from datetime import date, datetime
from enum import Enum
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from src.utils.logging import get_logger
from src.utils.s3_client import ensure_bucket, upload_bytes

logger = get_logger(__name__)


class DataType(str, Enum):
    TICKS = "ticks"
    DAILY_BARS = "daily_bars"
    MACRO = "macro"
    SEARCH = "search"
    RESEARCH = "research"
    PREDICTIONS = "predictions"
    ORDERS = "orders"


# ── Parquet 스키마 정의 ──────────────────────────────────────────────────────

TICK_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("timestamp", pa.timestamp("ms", tz="Asia/Seoul")),
    ("price", pa.float64()),
    ("volume", pa.int64()),
    ("change_rate", pa.float64()),
    ("bid_price", pa.float64()),
    ("ask_price", pa.float64()),
    ("total_volume", pa.int64()),
    ("total_amount", pa.int64()),
])

DAILY_BAR_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("date", pa.date32()),
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.int64()),
    ("change_rate", pa.float64()),
    ("market_cap", pa.int64()),
    ("source", pa.string()),
])

MACRO_SCHEMA = pa.schema([
    ("indicator", pa.string()),
    ("date", pa.date32()),
    ("value", pa.float64()),
    ("change_rate", pa.float64()),
    ("source", pa.string()),
])

SEARCH_SCHEMA = pa.schema([
    ("query", pa.string()),
    ("timestamp", pa.timestamp("ms", tz="Asia/Seoul")),
    ("title", pa.string()),
    ("url", pa.string()),
    ("snippet", pa.string()),
    ("score", pa.float64()),
    ("source_engine", pa.string()),
])

RESEARCH_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("timestamp", pa.timestamp("ms", tz="Asia/Seoul")),
    ("model", pa.string()),
    ("summary", pa.string()),
    ("sentiment", pa.string()),
    ("confidence", pa.float64()),
    ("raw_output", pa.string()),
])

PREDICTION_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("timestamp", pa.timestamp("ms", tz="Asia/Seoul")),
    ("strategy", pa.string()),
    ("signal", pa.string()),
    ("confidence", pa.float64()),
    ("target_price", pa.float64()),
    ("stop_loss", pa.float64()),
    ("reasoning", pa.string()),
])

ORDER_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("timestamp", pa.timestamp("ms", tz="Asia/Seoul")),
    ("side", pa.string()),
    ("quantity", pa.int64()),
    ("price", pa.float64()),
    ("order_type", pa.string()),
    ("account_scope", pa.string()),
    ("strategy", pa.string()),
    ("status", pa.string()),
    ("broker_order_id", pa.string()),
])

SCHEMA_MAP: dict[DataType, pa.Schema] = {
    DataType.TICKS: TICK_SCHEMA,
    DataType.DAILY_BARS: DAILY_BAR_SCHEMA,
    DataType.MACRO: MACRO_SCHEMA,
    DataType.SEARCH: SEARCH_SCHEMA,
    DataType.RESEARCH: RESEARCH_SCHEMA,
    DataType.PREDICTIONS: PREDICTION_SCHEMA,
    DataType.ORDERS: ORDER_SCHEMA,
}


# ── 핵심 유틸 ────────────────────────────────────────────────────────────────

def _build_key(
    data_type: DataType,
    dt: date,
    filename: str,
) -> str:
    """파티셔닝 키를 생성합니다.

    예: ticks/year=2026/month=03/day=15/005930.parquet
    """
    return (
        f"{data_type.value}"
        f"/year={dt.year:04d}"
        f"/month={dt.month:02d}"
        f"/day={dt.day:02d}"
        f"/{filename}.parquet"
    )


def _records_to_parquet(
    records: list[dict[str, Any]],
    schema: pa.Schema,
) -> bytes:
    """레코드 리스트를 Parquet 바이트로 직렬화합니다."""
    # 스키마에 맞게 누락 필드를 None으로 채움
    field_names = [f.name for f in schema]
    padded = []
    for rec in records:
        padded.append({k: rec.get(k) for k in field_names})

    table = pa.Table.from_pylist(padded, schema=schema)
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="snappy",
        write_statistics=True,
        write_page_index=True,
    )
    return buf.getvalue()


# ── 공개 API ─────────────────────────────────────────────────────────────────

async def store_records(
    data_type: DataType,
    records: list[dict[str, Any]],
    dt: date | None = None,
    filename: str | None = None,
) -> str | None:
    """레코드 리스트를 Parquet으로 변환하여 S3에 저장합니다.

    Args:
        data_type: 데이터 타입 (ticks, daily_bars, ...)
        records: 딕셔너리 리스트
        dt: 파티셔닝 날짜 (기본값: 오늘)
        filename: 파일 이름 (기본값: 첫 레코드의 ticker 또는 data_type)

    Returns:
        저장된 S3 URI 또는 빈 리스트시 None
    """
    if not records:
        return None

    dt = dt or date.today()
    schema = SCHEMA_MAP[data_type]

    # 파일명 결정
    if not filename:
        first = records[0]
        filename = first.get("ticker") or first.get("indicator") or data_type.value

    try:
        await ensure_bucket()
        parquet_bytes = _records_to_parquet(records, schema)
        key = _build_key(data_type, dt, filename)
        uri = await upload_bytes(
            data=parquet_bytes,
            key=key,
            content_type="application/x-parquet",
            metadata={
                "data_type": data_type.value,
                "record_count": str(len(records)),
                "partition_date": dt.isoformat(),
            },
        )
        logger.info(
            "Data Lake 저장 완료: %s (%d records, %d bytes)",
            uri, len(records), len(parquet_bytes),
        )
        return uri
    except Exception:
        logger.exception("Data Lake 저장 실패: %s, %d records", data_type.value, len(records))
        return None


async def store_tick_batch(
    ticker: str,
    ticks: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """틱 데이터 배치를 S3에 저장합니다.

    대량 틱은 시간 단위로 분할하여 저장하는 것을 권장합니다.
    """
    return await store_records(DataType.TICKS, ticks, dt=dt, filename=ticker)


async def store_daily_bars(
    ticker: str,
    bars: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """일봉 데이터를 S3에 저장합니다."""
    return await store_records(DataType.DAILY_BARS, bars, dt=dt, filename=ticker)


async def store_macro(
    indicator: str,
    data: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """매크로 지표 데이터를 S3에 저장합니다."""
    return await store_records(DataType.MACRO, data, dt=dt, filename=indicator)


async def store_search_results(
    query: str,
    results: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """검색 결과를 S3에 저장합니다."""
    # 파일명에서 특수문자 제거
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:50]
    return await store_records(DataType.SEARCH, results, dt=dt, filename=safe_name)


async def store_research(
    ticker: str,
    research: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """LLM 리서치 결과를 S3에 저장합니다."""
    return await store_records(DataType.RESEARCH, research, dt=dt, filename=ticker)


async def store_predictions(
    ticker: str,
    predictions: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """전략 예측 시그널을 S3에 저장합니다."""
    return await store_records(DataType.PREDICTIONS, predictions, dt=dt, filename=ticker)


async def store_orders(
    orders: list[dict[str, Any]],
    dt: date | None = None,
) -> str | None:
    """주문/체결 기록을 S3에 저장합니다."""
    return await store_records(DataType.ORDERS, orders, dt=dt, filename="orders")
