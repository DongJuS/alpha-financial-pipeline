"""
src/utils/market_hours.py — 한국 주식 시장 영업시간 판정

장중(09:00~15:30 KST, 월~금)인지 확인합니다.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

MARKET_OPEN_TIME = time(9, 0)
MARKET_CLOSE_TIME = time(15, 30)

# 장 운영시간 제한 적용 여부 (True면 장중에만 실거래 주문 허용)
MARKET_HOURS_ENFORCED: bool = True


async def is_market_open_now() -> bool:
    """현재 시각이 장중인지 확인합니다."""
    now = datetime.now(KST)
    # 월~금 (weekday 0~4)
    if now.weekday() > 4:  # 토요일, 일요일
        return False
    return MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME


async def market_session_status() -> dict:
    """현재 시장 세션 상태를 반환합니다."""
    now = datetime.now(KST)
    is_weekday = now.weekday() <= 4
    current_time = now.time()
    is_open = is_weekday and MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME

    if not is_weekday:
        session = "weekend"
    elif current_time < MARKET_OPEN_TIME:
        session = "pre_market"
    elif current_time > MARKET_CLOSE_TIME:
        session = "post_market"
    else:
        session = "open"

    return {
        "is_open": is_open,
        "session": session,
        "current_time_kst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_open": MARKET_OPEN_TIME.strftime("%H:%M"),
        "market_close": MARKET_CLOSE_TIME.strftime("%H:%M"),
    }
