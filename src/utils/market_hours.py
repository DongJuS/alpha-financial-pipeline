"""
src/utils/market_hours.py — 한국 주식 시장 영업시간 판정

장중(09:00~15:30 KST, 월~금)인지 확인합니다.
"""

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

MARKET_OPEN_TIME = time(9, 0)
MARKET_CLOSE_TIME = time(15, 30)

# 장외 시간 주문 차단 여부 (환경 변수로 끌 수 있음)
MARKET_HOURS_ENFORCED: bool = os.getenv("MARKET_HOURS_ENFORCED", "true").lower() in (
    "true",
    "1",
    "yes",
)


async def is_market_open_now() -> bool:
    """현재 시각이 장중인지 확인합니다."""
    now = datetime.now(KST)
    # 월~금 (weekday 0~4)
    if now.weekday() > 4:  # 토요일, 일요일
        return False
    return MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME


async def market_session_status() -> str:
    """현재 장 상태를 문자열로 반환합니다.

    Returns:
        "open"       — 정규장 (09:00~15:30)
        "pre_market" — 프리마켓 (08:30~09:00)
        "closed"     — 장 마감 또는 주말/공휴일
    """
    now = datetime.now(KST)
    if now.weekday() > 4:
        return "closed"

    current = now.time()
    if MARKET_OPEN_TIME <= current <= MARKET_CLOSE_TIME:
        return "open"
    if time(8, 30) <= current < MARKET_OPEN_TIME:
        return "pre_market"
    return "closed"
