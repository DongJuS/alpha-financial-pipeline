"""
src/utils/market_hours.py — KRX 정규장 정책 유틸
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from scripts.fetch_krx_holidays import ensure_holidays_cached, is_trading_day
from src.utils.logging import get_logger

logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN_TIME = time(9, 0)
MARKET_CLOSE_TIME = time(15, 30)
MARKET_HOURS_ENFORCED = True
MARKET_WINDOW_KST = "09:00-15:30"


def _to_kst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


async def market_session_status(now: datetime | None = None) -> str:
    """현재 한국 정규장 상태를 반환합니다."""
    now_kst = _to_kst(now)

    if now_kst.weekday() >= 5:
        return "weekend"

    try:
        holidays = await ensure_holidays_cached(now_kst.year)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("KRX 휴장일 조회 실패로 장 종료 처리: %s", exc)
        return "closed"

    if not is_trading_day(now_kst.date(), holidays):
        return "holiday"

    current_time = now_kst.time()
    if current_time < MARKET_OPEN_TIME:
        return "pre_open"
    if current_time > MARKET_CLOSE_TIME:
        return "after_hours"
    return "open"


async def is_market_open_now(now: datetime | None = None) -> bool:
    """현재 시각이 KRX 정규장 내인지 반환합니다."""
    return await market_session_status(now) == "open"
