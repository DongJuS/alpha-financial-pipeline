"""
src/utils/market_data.py — 시장 데이터 정규화 유틸
"""

from __future__ import annotations

import math
from typing import Optional


MAX_ABS_CHANGE_PCT = 999.999


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
