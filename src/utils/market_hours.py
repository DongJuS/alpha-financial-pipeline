"""
src/utils/market_hours.py — 한국 주식 시장 영업시간 판정

장중(09:00~15:30 KST, 월~금)인지 확인합니다.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.utils.config import get_settings

KST = ZoneInfo("Asia/Seoul")

MARKET_OPEN_TIME = time(9, 0)
MARKET_CLOSE_TIME = time(15, 30)

# 장외 시간 주문 차단 여부 (환경 변수로 끌 수 있음)
MARKET_HOURS_ENFORCED: bool = get_settings().market_hours_enforced


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


def next_trading_day_start(now: datetime | None = None) -> datetime:
    """다음 거래일 09:00 KST 시각을 반환합니다.

    Sell strategy Phase A Layer 3 lockout 만료 시각 계산에 사용
    (docs/plans/SELL_STRATEGY_PHASES.md §3-1, open question §8-8).

    주말 (토·일) skip. 공휴일 skip 은 KRX calendar 미도입이라 미처리 —
    공휴일 lockout 은 over-lock 방향이라 안전 (자본 보존 mandate 정합).

    Args:
        now: 기준 시각 (테스트용). None 이면 현재 KST.
    """
    base = now or datetime.now(KST)
    if base.tzinfo is None:
        base = base.replace(tzinfo=KST)
    next_day = base + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5=토, 6=일
        next_day += timedelta(days=1)
    return next_day.replace(hour=9, minute=0, second=0, microsecond=0)
