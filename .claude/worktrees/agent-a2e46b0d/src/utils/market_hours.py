"""
src/utils/market_hours.py — 한국 주식 시장 영업시간 판정

장중(09:00~15:30 KST, 월~금)인지 확인합니다.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

MARKET_OPEN_TIME = time(9, 0)
MARKET_CLOSE_TIME = time(15, 30)


async def is_market_open_now() -> bool:
    """현재 시각이 장중인지 확인합니다."""
    now = datetime.now(KST)
    # 월~금 (weekday 0~4)
    if now.weekday() > 4:  # 토요일, 일요일
        return False
    return MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME
