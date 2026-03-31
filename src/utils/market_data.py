"""
src/utils/market_data.py — 시장 데이터 정규화 유틸
"""

from __future__ import annotations

import math
from typing import Optional


MAX_ABS_CHANGE_PCT = 999.999

# ── instrument_id 변환 유틸 ──────────────────────────────────────────────────

_MARKET_TO_SUFFIX: dict[str, str] = {
    "KOSPI": "KS",
    "KOSDAQ": "KQ",
    "NYSE": "US",
    "NASDAQ": "US",
}

_SUFFIX_TO_MARKET: dict[str, str] = {
    "KS": "KOSPI",
    "KQ": "KOSDAQ",
    "US": "NYSE",
}


def to_instrument_id(ticker: str, market: str = "KOSPI") -> str:
    """raw_code + market -> instrument_id  (e.g. '005930' + 'KOSPI' -> '005930.KS')"""
    suffix = _MARKET_TO_SUFFIX.get(market, "KS")
    return f"{ticker}.{suffix}"


def from_instrument_id(instrument_id: str) -> tuple[str, str]:
    """instrument_id -> (raw_code, market)  (e.g. '005930.KS' -> ('005930', 'KOSPI'))"""
    parts = instrument_id.rsplit(".", 1)
    raw_code = parts[0]
    suffix = parts[1] if len(parts) > 1 else "KS"
    market = _SUFFIX_TO_MARKET.get(suffix, "KOSPI")
    return raw_code, market


def sanitize_change_pct(value: object) -> Optional[float]:
    """DB 스키마 범위를 넘거나 비정상인 change_pct 값을 정리합니다."""
    if value is None:
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(numeric):
        return None

    if abs(numeric) > MAX_ABS_CHANGE_PCT:
        return None

    return round(numeric, 3)


def compute_change_pct(current_close: int | float, previous_close: int | float | None) -> Optional[float]:
    """이전 종가 대비 등락률(%)을 계산합니다."""
    if previous_close is None:
        return None

    try:
        current = float(current_close)
        previous = float(previous_close)
    except (TypeError, ValueError):
        return None

    if previous <= 0 or not math.isfinite(current) or not math.isfinite(previous):
        return None

    return sanitize_change_pct(((current - previous) / previous) * 100.0)
