"""
scripts/fetch_krx_holidays.py — KRX 휴장일 캘린더 수집 및 Redis 저장

사용법:
    python scripts/fetch_krx_holidays.py           # 올해 휴장일 수집
    python scripts/fetch_krx_holidays.py --year 2026  # 특정 연도 수집

KRX 공식 REST API (data.krx.co.kr) 를 사용합니다.
CollectorAgent는 매 작업 전에 Redis `krx:holidays:{year}` 키를 확인합니다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.logging import setup_logging
from src.utils.redis_client import KEY_KRX_HOLIDAYS, TTL_KRX_HOLIDAYS, close_redis, get_redis

setup_logging()
logger = logging.getLogger(__name__)

# KRX 데이터 포털 공개 REST API
KRX_HOLIDAY_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_HOLIDAY_PARAMS_BASE = {
    "bld": "dbms/MDC/STAT/standard/MDCSTAT01601",
    "locale": "ko_KR",
    "mktTpCd": "T",   # 전체 시장
    "trdDd": "",      # 조회 기준일 (YYYYMMDD)
    "money": "1",
    "csvxls_isNo": "false",
}


def _make_year_dates(year: int) -> tuple[str, str]:
    """연도를 받아 시작일/종료일 문자열을 반환합니다."""
    return f"{year}0101", f"{year}1231"


async def fetch_holidays_from_krx(year: int) -> list[str]:
    """
    KRX 공식 REST API에서 휴장일 목록을 가져옵니다.

    Returns:
        'YYYY-MM-DD' 형식의 휴장일 문자열 목록
    """
    from_dt, to_dt = _make_year_dates(year)

    params = {
        **KRX_HOLIDAY_PARAMS_BASE,
        "trdDd": from_dt,
        "fromdate": from_dt,
        "todate": to_dt,
    }

    logger.info("%d년 KRX 휴장일 조회 중...", year)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(KRX_HOLIDAY_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error("KRX API 호출 실패: %s", e)
        return _get_fallback_holidays(year)

    # KRX API 응답 구조: {"block1": [{"calDd": "20260101", "dyTp": "01", ...}, ...]}
    holidays: list[str] = []
    for item in data.get("block1", []):
        cal_dd = item.get("calDd", "")
        # dyTp: "01" = 토요일, "02" = 일요일, "03" = 공휴일, "04" = 임시 휴장
        dy_tp = item.get("dyTp", "")
        if dy_tp in ("03", "04") and len(cal_dd) == 8:
            formatted = f"{cal_dd[:4]}-{cal_dd[4:6]}-{cal_dd[6:]}"
            holidays.append(formatted)

    logger.info("  → %d개 공휴일/임시휴장 수집", len(holidays))

    if not holidays:
        logger.warning("KRX API 응답이 비어있습니다. 폴백 공휴일 목록을 사용합니다.")
        return _get_fallback_holidays(year)

    return sorted(set(holidays))


def _get_fallback_holidays(year: int) -> list[str]:
    """
    KRX API 실패 시 사용하는 한국 법정공휴일 폴백 목록.
    매년 고정된 공휴일만 포함합니다 (임시 공휴일 제외).
    """
    fixed = [
        f"{year}-01-01",  # 신정
        f"{year}-03-01",  # 3.1절
        f"{year}-05-05",  # 어린이날
        f"{year}-06-06",  # 현충일
        f"{year}-08-15",  # 광복절
        f"{year}-10-03",  # 개천절
        f"{year}-10-09",  # 한글날
        f"{year}-12-25",  # 성탄절
    ]
    logger.info("폴백 공휴일 %d개 사용", len(fixed))
    return fixed


def is_trading_day(check_date: date, holidays: list[str]) -> bool:
    """주어진 날짜가 거래일인지 확인합니다."""
    if check_date.weekday() >= 5:  # 토(5), 일(6)
        return False
    return check_date.isoformat() not in holidays


async def store_holidays_to_redis(year: int, holidays: list[str]) -> None:
    """휴장일 목록을 Redis에 저장합니다 (TTL 24시간)."""
    redis = await get_redis()
    key = KEY_KRX_HOLIDAYS.format(year=year)
    await redis.set(key, json.dumps(holidays), ex=TTL_KRX_HOLIDAYS)
    logger.info("Redis 저장 완료: %s (TTL %dh) — %d개 휴장일", key, TTL_KRX_HOLIDAYS // 3600, len(holidays))


async def get_holidays_from_redis(year: int) -> list[str] | None:
    """Redis에서 휴장일 목록을 가져옵니다."""
    redis = await get_redis()
    key = KEY_KRX_HOLIDAYS.format(year=year)
    raw = await redis.get(key)
    if raw:
        return json.loads(raw)
    return None


async def ensure_holidays_cached(year: int | None = None) -> list[str]:
    """
    Redis 캐시를 확인하고 없으면 KRX에서 가져옵니다.
    CollectorAgent에서 호출하는 헬퍼 함수입니다.
    """
    target_year = year or datetime.now().year
    cached = await get_holidays_from_redis(target_year)
    if cached:
        logger.debug("%d년 휴장일 캐시 히트 (%d개)", target_year, len(cached))
        return cached

    holidays = await fetch_holidays_from_krx(target_year)
    await store_holidays_to_redis(target_year, holidays)
    return holidays


async def main_async(year: int) -> None:
    try:
        holidays = await fetch_holidays_from_krx(year)
        await store_holidays_to_redis(year, holidays)

        logger.info("─── %d년 KRX 휴장일 목록 ────────────────", year)
        for h in holidays:
            logger.info("  %s", h)
    finally:
        await close_redis()


def main() -> None:
    parser = argparse.ArgumentParser(description="KRX 휴장일 캘린더 수집")
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="수집할 연도 (기본값: 올해)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.year))


if __name__ == "__main__":
    main()
