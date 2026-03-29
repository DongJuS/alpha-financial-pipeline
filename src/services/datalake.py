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

SCHEMAS: dict[DataType, pa.Schema] = {
    DataType.DAILY_BARS: DAILY_BARS_SCHEMA,
    DataType.PREDICTIONS: PREDICTIONS_SCHEMA,
    DataType.ORDERS: ORDERS_SCHEMA,
    DataType.BLEND_RESULTS: BLEND_RESULTS_SCHEMA,
    DataType.TICK_DATA: TICK_DATA_SCHEMA,
    DataType.DEBATE_TRANSCRIPTS: DEBATE_TRANSCRIPTS_SCHEMA,
    DataType.RL_EPISODES: RL_EPISODES_SCHEMA,
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
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def _make_s3_key(
    data_type: DataType,
    partition_date: date | None = None,
    suffix: str = "",
) -> str:
    """Hive-style 파티션 키를 생성합니다."""
    dt = partition_date or date.today()
    ts = datetime.utcnow().strftime("%H%M%S")
    name = f"{data_type.value}_{ts}{suffix}.parquet"
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
