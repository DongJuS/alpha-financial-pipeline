"""
src/services/datalake.py — S3 Data Lake Parquet 저장 서비스

수집된 시장 데이터, 예측 시그널, 주문 기록 등을
Parquet 형식으로 S3/MinIO에 저장합니다.
Hive-style 파티셔닝(data_type/date=YYYY-MM-DD/)을 사용합니다.
"""

from __future__ import annotations

import asyncio
import io
from datetime import date, datetime
from enum import Enum
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from src.utils.logging import get_logger
from src.utils.s3_client import upload_bytes

logger = get_logger(__name__)


class DataType(str, Enum):
    """Data Lake에 저장하는 데이터 유형."""
    DAILY_BARS = "daily_bars"
    TICK_DATA = "tick_data"
    PREDICTIONS = "predictions"
    ORDERS = "orders"
    BLEND_RESULTS = "blend_results"
    DEBATE_TRANSCRIPTS = "debate_transcripts"
    RL_EPISODES = "rl_episodes"
    OHLCV_MINUTE = "ohlcv_minute"


# ── PyArrow 스키마 정의 ──────────────────────────────────────────────────────

DAILY_BARS_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("name", pa.string()),
    ("market", pa.string()),
    ("timestamp_kst", pa.timestamp("ms")),
    ("open", pa.int64()),
    ("high", pa.int64()),
    ("low", pa.int64()),
    ("close", pa.int64()),
    ("volume", pa.int64()),
    ("change_pct", pa.float64()),
    ("market_cap", pa.int64()),
    ("foreigner_ratio", pa.float64()),
])

PREDICTIONS_SCHEMA = pa.schema([
    ("agent_id", pa.string()),
    ("llm_model", pa.string()),
    ("strategy", pa.string()),
    ("ticker", pa.string()),
    ("signal", pa.string()),
    ("confidence", pa.float64()),
    ("target_price", pa.int64()),
    ("stop_loss", pa.int64()),
    ("reasoning_summary", pa.string()),
    ("trading_date", pa.string()),
    ("is_shadow", pa.bool_()),
])

ORDERS_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("name", pa.string()),
    ("signal", pa.string()),
    ("quantity", pa.int64()),
    ("price", pa.int64()),
    ("signal_source", pa.string()),
    ("agent_id", pa.string()),
    ("account_scope", pa.string()),
    ("strategy_id", pa.string()),
    ("created_at", pa.timestamp("ms")),
])

BLEND_RESULTS_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("blended_signal", pa.string()),
    ("blended_confidence", pa.float64()),
    ("strategy_weights", pa.string()),  # JSON string
    ("created_at", pa.timestamp("ms")),
])

TICK_DATA_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("price", pa.int64()),
    ("volume", pa.int64()),
    ("timestamp_kst", pa.timestamp("ms")),
    ("change_pct", pa.float64()),
    ("source", pa.string()),  # "kis_websocket" | "kis_rest_fallback"
])

DEBATE_TRANSCRIPTS_SCHEMA = pa.schema([
    ("transcript_id", pa.int64()),
    ("ticker", pa.string()),
    ("strategy", pa.string()),       # "B"
    ("round_number", pa.int64()),
    ("proposer_text", pa.string()),
    ("challenger_text", pa.string()),
    ("synthesizer_text", pa.string()),
    ("consensus_signal", pa.string()),
    ("consensus_confidence", pa.float64()),
    ("trading_date", pa.string()),
    ("created_at", pa.timestamp("ms")),
])

RL_EPISODES_SCHEMA = pa.schema([
    ("ticker", pa.string()),
    ("policy_id", pa.string()),
    ("profile_id", pa.string()),
    ("dataset_days", pa.int64()),
    ("train_return_pct", pa.float64()),
    ("holdout_return_pct", pa.float64()),
    ("excess_return_pct", pa.float64()),
    ("max_drawdown_pct", pa.float64()),
    ("walk_forward_passed", pa.bool_()),
    ("walk_forward_consistency", pa.float64()),
    ("deployed", pa.bool_()),
    ("created_at", pa.timestamp("ms")),
])

OHLCV_MINUTE_SCHEMA = pa.schema([
    ("instrument_id", pa.string()),
    ("bucket_at", pa.timestamp("ms")),
    ("open", pa.int32()),
    ("high", pa.int32()),
    ("low", pa.int32()),
    ("close", pa.int32()),
    ("volume", pa.int64()),
    ("trade_count", pa.int32()),
    ("vwap", pa.float64()),
])

SCHEMAS: dict[DataType, pa.Schema] = {
    DataType.DAILY_BARS: DAILY_BARS_SCHEMA,
    DataType.PREDICTIONS: PREDICTIONS_SCHEMA,
    DataType.ORDERS: ORDERS_SCHEMA,
    DataType.BLEND_RESULTS: BLEND_RESULTS_SCHEMA,
    DataType.TICK_DATA: TICK_DATA_SCHEMA,
    DataType.DEBATE_TRANSCRIPTS: DEBATE_TRANSCRIPTS_SCHEMA,
    DataType.RL_EPISODES: RL_EPISODES_SCHEMA,
    DataType.OHLCV_MINUTE: OHLCV_MINUTE_SCHEMA,
}


def _to_parquet_bytes(records: list[dict[str, Any]], schema: pa.Schema) -> bytes:
    """레코드 리스트를 Parquet 바이트로 직렬화합니다."""
    # None 값을 스키마에 맞게 정리
    cleaned = []
    for rec in records:
        row = {}
        for field in schema:
            val = rec.get(field.name)
            row[field.name] = val
        cleaned.append(row)

    # dict-of-lists 형태로 변환
    columns: dict[str, list] = {field.name: [] for field in schema}
    for row in cleaned:
        for field in schema:
            columns[field.name].append(row[field.name])

    table = pa.table(columns, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def _make_s3_key(
    data_type: DataType,
    partition_date: date | None = None,
    suffix: str = "",
    hour: int | None = None,
) -> str:
    """Hive-style 파티션 키를 생성합니다.

    hour를 지정하면 date/hour 2단계 파티셔닝을 사용합니다.
    미지정 시 기존 date-only 파티셔닝을 유지합니다.
    """
    dt = partition_date or date.today()
    ts = datetime.utcnow().strftime("%H%M%S")
    name = f"{data_type.value}_{ts}{suffix}.parquet"
    if hour is not None:
        return f"{data_type.value}/date={dt.isoformat()}/hour={hour:02d}/{name}"
    return f"{data_type.value}/date={dt.isoformat()}/{name}"


# ── 재시도 로직 (exponential backoff) ────────────────────────────────────────
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


async def _upload_with_retry(
    data: bytes,
    key: str,
    content_type: str = "application/x-parquet",
) -> str:
    """S3 업로드를 최대 _MAX_RETRIES회 재시도합니다 (exponential backoff)."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await upload_bytes(data, key, content_type=content_type)
        except Exception as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "S3 업로드 재시도 %d/%d (key=%s): %s — %.1f초 후 재시도",
                    attempt, _MAX_RETRIES, key, e, delay,
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def store_daily_bars(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """일봉 데이터를 Parquet으로 S3에 저장합니다."""
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, DAILY_BARS_SCHEMA)
        key = _make_s3_key(DataType.DAILY_BARS, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 일봉 저장 완료: %s (%d건, %d bytes)", s3_uri, len(records), len(data))
        return s3_uri
    except Exception as e:
        logger.error("S3 일봉 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def store_predictions(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """예측 시그널을 Parquet으로 S3에 저장합니다."""
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, PREDICTIONS_SCHEMA)
        key = _make_s3_key(DataType.PREDICTIONS, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 예측 저장 완료: %s (%d건)", s3_uri, len(records))
        return s3_uri
    except Exception as e:
        logger.error("S3 예측 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def store_orders(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """주문 기록을 Parquet으로 S3에 저장합니다."""
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, ORDERS_SCHEMA)
        key = _make_s3_key(DataType.ORDERS, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 주문 저장 완료: %s (%d건)", s3_uri, len(records))
        return s3_uri
    except Exception as e:
        logger.error("S3 주문 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def store_blend_results(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """블렌딩 결과를 Parquet으로 S3에 저장합니다."""
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, BLEND_RESULTS_SCHEMA)
        key = _make_s3_key(DataType.BLEND_RESULTS, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 블렌딩 저장 완료: %s (%d건)", s3_uri, len(records))
        return s3_uri
    except Exception as e:
        logger.error("S3 블렌딩 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def store_tick_data(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """실시간 틱 데이터를 Parquet으로 S3에 저장합니다.

    collector.py의 collect_realtime_ticks()에서 배치 flush 시 호출합니다.
    필드: ticker, price, volume, timestamp_kst, change_pct, source
    """
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, TICK_DATA_SCHEMA)
        key = _make_s3_key(DataType.TICK_DATA, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 틱 데이터 저장 완료: %s (%d건, %d bytes)", s3_uri, len(records), len(data))
        return s3_uri
    except Exception as e:
        logger.error("S3 틱 데이터 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def flush_ticks_to_s3(target_date: date | None = None) -> list[str]:
    """DB의 당일 틱 데이터를 시간대별로 묶어 S3에 일괄 저장합니다.

    장 종료 후 크론(15:40 KST)에서 호출합니다.
    시간대별로 그룹핑하여 hour 파티셔닝된 대형 Parquet 파일을 생성합니다.
    """
    from collections import defaultdict
    from src.db.queries import fetch

    dt = target_date or date.today()
    start = datetime(dt.year, dt.month, dt.day, 0, 0, 0)
    end = datetime(dt.year, dt.month, dt.day, 23, 59, 59)

    rows = await fetch(
        """
        SELECT instrument_id AS ticker, price, volume,
               timestamp_kst, change_pct, source
        FROM tick_data
        WHERE timestamp_kst >= $1 AND timestamp_kst < $2
        ORDER BY timestamp_kst ASC
        """,
        start, end,
    )

    if not rows:
        logger.info("flush_ticks_to_s3: %s 틱 데이터 없음 — 스킵", dt.isoformat())
        return []

    # 시간대별 그룹핑
    by_hour: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        ts = row["timestamp_kst"]
        h = ts.hour if hasattr(ts, "hour") else 0
        by_hour[h].append({
            "ticker": row["ticker"],
            "price": int(row["price"]),
            "volume": int(row["volume"]),
            "timestamp_kst": row["timestamp_kst"],
            "change_pct": row.get("change_pct"),
            "source": row.get("source", "unknown"),
        })

    uris: list[str] = []
    for h, records in sorted(by_hour.items()):
        try:
            data = _to_parquet_bytes(records, TICK_DATA_SCHEMA)
            key = _make_s3_key(DataType.TICK_DATA, dt, suffix=f"_{len(records)}t", hour=h)
            s3_uri = await _upload_with_retry(data, key)
            uris.append(s3_uri)
            logger.info("S3 틱 flush: hour=%02d, %d건, %d bytes → %s", h, len(records), len(data), s3_uri)
        except Exception as e:
            logger.error("S3 틱 flush 실패 (hour=%02d): %s", h, e, exc_info=True)

    logger.info("flush_ticks_to_s3 완료: %s, %d파일, 총 %d건", dt.isoformat(), len(uris), len(rows))
    return uris


async def store_debate_transcripts(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """Strategy B 토론 전문을 Parquet으로 S3에 저장합니다.

    strategy_b 에서 debate_transcripts 테이블 insert 후 S3 아카이빙에 사용합니다.
    필드: transcript_id, ticker, strategy, round_number,
          proposer_text, challenger_text, synthesizer_text,
          consensus_signal, consensus_confidence, trading_date, created_at
    """
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, DEBATE_TRANSCRIPTS_SCHEMA)
        key = _make_s3_key(DataType.DEBATE_TRANSCRIPTS, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 토론 전문 저장 완료: %s (%d건)", s3_uri, len(records))
        return s3_uri
    except Exception as e:
        logger.error("S3 토론 전문 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def store_rl_episodes(records: list[dict[str, Any]], partition_date: date | None = None) -> str | None:
    """RL 학습 에피소드(학습/검증 결과)를 Parquet으로 S3에 저장합니다.

    RLContinuousImprover의 retrain_ticker() 완료 후 호출합니다.
    필드: ticker, policy_id, profile_id, dataset_days,
          train_return_pct, holdout_return_pct, excess_return_pct,
          max_drawdown_pct, walk_forward_passed, walk_forward_consistency,
          deployed, created_at
    """
    if not records:
        return None
    try:
        data = _to_parquet_bytes(records, RL_EPISODES_SCHEMA)
        key = _make_s3_key(DataType.RL_EPISODES, partition_date)
        s3_uri = await _upload_with_retry(data, key)
        logger.info("S3 RL 에피소드 저장 완료: %s (%d건)", s3_uri, len(records))
        return s3_uri
    except Exception as e:
        logger.error("S3 RL 에피소드 저장 최종 실패 (%d회 재시도 후): %s", _MAX_RETRIES, e, exc_info=True)
        return None


async def archive_minute_bars(year: int, month: int) -> list[str]:
    """지정 월의 ohlcv_minute 데이터를 종목별 S3 Parquet으로 아카이브합니다.

    S3 키 구조: ohlcv_minute/year=YYYY/month=MM/{instrument_id}.parquet
    아카이브 완료 시 _ARCHIVED 마커 파일을 생성합니다.

    Returns:
        업로드된 S3 URI 목록
    """
    from collections import defaultdict

    from src.db.queries import fetch

    # 해당 월의 분봉 데이터 조회
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    rows = await fetch(
        """
        SELECT instrument_id, bucket_at, open, high, low, close,
               volume, trade_count, vwap
        FROM ohlcv_minute
        WHERE bucket_at >= $1::timestamptz
          AND bucket_at < $2::timestamptz
        ORDER BY instrument_id, bucket_at
        """,
        start,
        end,
    )

    if not rows:
        logger.info("archive_minute_bars: %04d-%02d 데이터 없음 — 스킵", year, month)
        return []

    # 종목별 그룹핑
    by_instrument: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_instrument[row["instrument_id"]].append(
            {
                "instrument_id": row["instrument_id"],
                "bucket_at": row["bucket_at"],
                "open": int(row["open"]),
                "high": int(row["high"]),
                "low": int(row["low"]),
                "close": int(row["close"]),
                "volume": int(row["volume"]),
                "trade_count": int(row["trade_count"]),
                "vwap": float(row["vwap"]),
            }
        )

    uris: list[str] = []
    prefix = f"ohlcv_minute/year={year:04d}/month={month:02d}"

    for instrument_id, records in by_instrument.items():
        try:
            data = _to_parquet_bytes(records, OHLCV_MINUTE_SCHEMA)
            key = f"{prefix}/{instrument_id}.parquet"
            s3_uri = await _upload_with_retry(data, key)
            uris.append(s3_uri)
            logger.info(
                "S3 분봉 아카이브: %s, %d건 → %s",
                instrument_id,
                len(records),
                s3_uri,
            )
        except Exception as e:
            logger.error(
                "S3 분봉 아카이브 실패 (%s): %s", instrument_id, e, exc_info=True
            )

    # 마커 파일 생성
    if uris:
        try:
            marker_key = f"{prefix}/_ARCHIVED"
            await _upload_with_retry(
                b"archived",
                marker_key,
                content_type="text/plain",
            )
            logger.info("S3 분봉 아카이브 마커 생성: %s", marker_key)
        except Exception as e:
            logger.error("S3 아카이브 마커 생성 실패: %s", e, exc_info=True)

    logger.info(
        "archive_minute_bars 완료: %04d-%02d, %d종목, %d파일",
        year,
        month,
        len(by_instrument),
        len(uris),
    )
    return uris


async def check_archive_marker(year: int, month: int) -> bool:
    """S3에 해당 월의 아카이브 마커(_ARCHIVED)가 존재하는지 확인합니다."""
    from src.utils.s3_client import object_exists

    marker_key = f"ohlcv_minute/year={year:04d}/month={month:02d}/_ARCHIVED"
    try:
        return await object_exists(marker_key)
    except Exception as exc:
        logger.warning("S3 아카이브 마커 확인 실패 (%s): %s", marker_key, exc)
        return False
