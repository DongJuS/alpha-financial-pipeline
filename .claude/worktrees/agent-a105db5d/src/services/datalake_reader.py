"""
src/services/datalake_reader.py — Data Lake 읽기 서비스

S3(MinIO)에 저장된 Parquet 데이터를 읽어오는 통합 서비스입니다.
피드백 루프, RL 재학습, 백테스트 등 배치 워크로드에서 사용합니다.

사용 예:
    records = await load_records(DataType.PREDICTIONS, start=date(2026,3,1), end=date(2026,3,15))
    df = await load_dataframe(DataType.DAILY_BARS, start=date(2026,1,1), ticker="005930")
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from src.services.datalake import DataType, SCHEMA_MAP
from src.utils.logging import get_logger
from src.utils.s3_client import download_bytes, list_objects

logger = get_logger(__name__)


def _date_range(start: date, end: date) -> list[date]:
    """start~end 사이의 날짜 리스트를 반환합니다."""
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _prefix_for(data_type: DataType, dt: date) -> str:
    """특정 날짜의 파티션 prefix를 생성합니다."""
    return (
        f"{data_type.value}"
        f"/year={dt.year:04d}"
        f"/month={dt.month:02d}"
        f"/day={dt.day:02d}/"
    )


def _parquet_bytes_to_records(
    data: bytes,
    schema: pa.Schema | None = None,
) -> list[dict[str, Any]]:
    """Parquet 바이트를 딕셔너리 리스트로 역직렬화합니다."""
    buf = io.BytesIO(data)
    table = pq.read_table(buf, schema=schema)
    return table.to_pylist()


async def list_keys(
    data_type: DataType,
    start: date,
    end: date | None = None,
    ticker: str | None = None,
) -> list[str]:
    """날짜 범위 내 S3 오브젝트 키 목록을 반환합니다.

    Args:
        data_type: 데이터 타입
        start: 시작 날짜
        end: 종료 날짜 (기본값: start와 동일)
        ticker: 특정 티커 필터 (파일명 기준)

    Returns:
        S3 오브젝트 키 리스트
    """
    end = end or start
    all_keys: list[str] = []

    for dt in _date_range(start, end):
        prefix = _prefix_for(data_type, dt)
        try:
            keys = await list_objects(prefix)
            if ticker:
                keys = [k for k in keys if f"/{ticker}." in k]
            all_keys.extend(keys)
        except Exception:
            logger.debug("S3 키 조회 실패: %s", prefix)

    return all_keys


async def load_records(
    data_type: DataType,
    start: date,
    end: date | None = None,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """날짜 범위의 Parquet 레코드를 딕셔너리 리스트로 로드합니다.

    Args:
        data_type: 데이터 타입
        start: 시작 날짜
        end: 종료 날짜 (기본값: start와 동일)
        ticker: 특정 티커 필터

    Returns:
        레코드 딕셔너리 리스트 (합산)
    """
    end = end or start
    schema = SCHEMA_MAP.get(data_type)
    keys = await list_keys(data_type, start, end, ticker=ticker)

    all_records: list[dict[str, Any]] = []
    for key in keys:
        try:
            raw = await download_bytes(key)
            records = _parquet_bytes_to_records(raw, schema=schema)
            all_records.extend(records)
            logger.debug("로드 완료: %s (%d records)", key, len(records))
        except Exception:
            logger.warning("Parquet 로드 실패: %s", key, exc_info=True)

    logger.info(
        "Data Lake 로드: %s [%s ~ %s] %s → %d records",
        data_type.value, start, end,
        f"ticker={ticker}" if ticker else "all",
        len(all_records),
    )
    return all_records


async def load_dataframe(
    data_type: DataType,
    start: date,
    end: date | None = None,
    ticker: str | None = None,
) -> pa.Table:
    """날짜 범위의 Parquet 데이터를 PyArrow Table로 로드합니다.

    pandas가 아닌 PyArrow Table을 반환하여 의존성을 최소화합니다.
    필요 시 table.to_pandas()로 변환할 수 있습니다.

    Returns:
        PyArrow Table (빈 결과 시 빈 테이블)
    """
    end = end or start
    schema = SCHEMA_MAP.get(data_type)
    keys = await list_keys(data_type, start, end, ticker=ticker)

    tables: list[pa.Table] = []
    for key in keys:
        try:
            raw = await download_bytes(key)
            buf = io.BytesIO(raw)
            table = pq.read_table(buf, schema=schema)
            tables.append(table)
        except Exception:
            logger.warning("Parquet Table 로드 실패: %s", key, exc_info=True)

    if not tables:
        return pa.table({f.name: pa.array([], type=f.type) for f in schema}) if schema else pa.table({})

    return pa.concat_tables(tables, promote_options="default")


async def load_predictions_with_outcomes(
    start: date,
    end: date,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """예측 시그널과 실제 일봉을 매칭하여 정확도를 포함한 레코드를 반환합니다.

    각 prediction 레코드에 다음 필드를 추가합니다:
        - actual_close: 해당 일 종가
        - actual_change_pct: 전일 대비 변동률
        - was_correct: 시그널 방향과 실제 방향 일치 여부
        - pnl_pct: target_price 기준 예상 수익률 (없으면 actual_change_pct)

    Returns:
        보강된 prediction 레코드 리스트
    """
    predictions = await load_records(DataType.PREDICTIONS, start, end, ticker=ticker)
    if not predictions:
        return []

    # 일봉 데이터 로드 (예측 날짜 +1일까지 포함하여 다음날 종가 확인)
    bars = await load_records(
        DataType.DAILY_BARS,
        start,
        end + timedelta(days=5),
        ticker=ticker,
    )

    # ticker+date → bar 인덱스 구축
    bar_index: dict[str, dict[str, Any]] = {}
    for bar in bars:
        bar_date = bar.get("date")
        if bar_date is None:
            continue
        bar_key = f"{bar.get('ticker')}_{bar_date}"
        bar_index[bar_key] = bar

    enriched: list[dict[str, Any]] = []
    for pred in predictions:
        ts = pred.get("timestamp")
        if ts is None:
            continue

        # timestamp에서 date 추출
        if hasattr(ts, "date"):
            pred_date = ts.date()
        elif isinstance(ts, str):
            pred_date = date.fromisoformat(ts[:10])
        else:
            pred_date = ts

        pred_ticker = pred.get("ticker", "")
        signal = str(pred.get("signal", "HOLD")).upper()

        # 당일 종가 찾기
        bar_key = f"{pred_ticker}_{pred_date}"
        bar = bar_index.get(bar_key)

        # 다음 거래일 종가 (1~3일 후)
        next_bar = None
        for offset in range(1, 4):
            next_date = pred_date + timedelta(days=offset)
            next_key = f"{pred_ticker}_{next_date}"
            if next_key in bar_index:
                next_bar = bar_index[next_key]
                break

        actual_close = None
        actual_change_pct = None
        was_correct = None
        pnl_pct = None

        if bar and next_bar:
            close_today = float(bar.get("close", 0))
            close_next = float(next_bar.get("close", 0))

            if close_today > 0:
                actual_change_pct = ((close_next - close_today) / close_today) * 100
                actual_close = close_next

                # 방향 정확도 평가
                if signal == "BUY":
                    was_correct = actual_change_pct > 0
                    pnl_pct = actual_change_pct
                elif signal == "SELL":
                    was_correct = actual_change_pct < 0
                    pnl_pct = -actual_change_pct
                else:  # HOLD
                    was_correct = abs(actual_change_pct) < 1.0  # 변동 1% 미만이면 정확
                    pnl_pct = 0.0

                # target_price 기반 수익률 (있으면 더 정밀)
                target = pred.get("target_price")
                if target and float(target) > 0 and close_today > 0:
                    pnl_pct = ((float(target) - close_today) / close_today) * 100
                    if signal == "SELL":
                        pnl_pct = -pnl_pct

        enriched.append({
            **pred,
            "pred_date": pred_date.isoformat(),
            "actual_close": actual_close,
            "actual_change_pct": round(actual_change_pct, 4) if actual_change_pct is not None else None,
            "was_correct": was_correct,
            "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
        })

    return enriched


async def compute_strategy_accuracy(
    start: date,
    end: date,
    strategy: str | None = None,
) -> dict[str, Any]:
    """전략별 예측 정확도 및 P&L 통계를 계산합니다.

    Returns:
        {
            "total": int,
            "evaluated": int,
            "correct": int,
            "accuracy": float,
            "avg_pnl_pct": float,
            "by_strategy": { "A": {...}, "B": {...}, "RL": {...} },
            "by_signal": { "BUY": {...}, "SELL": {...}, "HOLD": {...} },
        }
    """
    records = await load_predictions_with_outcomes(start, end)

    if strategy:
        records = [r for r in records if r.get("strategy") == strategy]

    total = len(records)
    evaluated = [r for r in records if r.get("was_correct") is not None]
    correct = [r for r in evaluated if r["was_correct"]]

    pnl_values = [r["pnl_pct"] for r in evaluated if r.get("pnl_pct") is not None]
    avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0

    # 전략별 분류
    by_strategy: dict[str, dict[str, Any]] = {}
    for r in records:
        s = r.get("strategy", "unknown")
        bucket = by_strategy.setdefault(s, {"total": 0, "evaluated": 0, "correct": 0, "pnl_sum": 0.0})
        bucket["total"] += 1
        if r.get("was_correct") is not None:
            bucket["evaluated"] += 1
            if r["was_correct"]:
                bucket["correct"] += 1
            if r.get("pnl_pct") is not None:
                bucket["pnl_sum"] += r["pnl_pct"]

    for s, b in by_strategy.items():
        b["accuracy"] = round(b["correct"] / b["evaluated"], 4) if b["evaluated"] > 0 else 0.0
        b["avg_pnl_pct"] = round(b["pnl_sum"] / b["evaluated"], 4) if b["evaluated"] > 0 else 0.0
        del b["pnl_sum"]

    # 시그널별 분류
    by_signal: dict[str, dict[str, Any]] = {}
    for r in records:
        sig = str(r.get("signal", "HOLD")).upper()
        bucket = by_signal.setdefault(sig, {"total": 0, "evaluated": 0, "correct": 0, "pnl_sum": 0.0})
        bucket["total"] += 1
        if r.get("was_correct") is not None:
            bucket["evaluated"] += 1
            if r["was_correct"]:
                bucket["correct"] += 1
            if r.get("pnl_pct") is not None:
                bucket["pnl_sum"] += r["pnl_pct"]

    for sig, b in by_signal.items():
        b["accuracy"] = round(b["correct"] / b["evaluated"], 4) if b["evaluated"] > 0 else 0.0
        b["avg_pnl_pct"] = round(b["pnl_sum"] / b["evaluated"], 4) if b["evaluated"] > 0 else 0.0
        del b["pnl_sum"]

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "total": total,
        "evaluated": len(evaluated),
        "correct": len(correct),
        "accuracy": round(len(correct) / len(evaluated), 4) if evaluated else 0.0,
        "avg_pnl_pct": round(avg_pnl, 4),
        "by_strategy": by_strategy,
        "by_signal": by_signal,
    }
