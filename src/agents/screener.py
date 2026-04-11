"""
src/agents/screener.py — 일봉 기반 종목 스크리너

100종목 일봉 데이터에서 거래량 급등·가격 변동률 기준으로
전략 실행 대상을 최대 10종목까지 필터링한다.
LLM 호출 비용 절감이 핵심 목적.
"""

from __future__ import annotations

import asyncio

from src.constants import (
    MAX_SCREENED_TICKERS,
    SCREENER_CHANGE_PCT_THRESHOLD,
    SCREENER_VOLUME_SURGE_RATIO,
)
from src.db.queries import fetch_recent_market_data
from src.utils.logging import get_logger

logger = get_logger(__name__)

_MIN_DATA_DAYS = 5


def _score_ticker(
    bars: list[dict],
    vol_threshold: float,
    pct_threshold: float,
) -> tuple[bool, float]:
    """최근 바 1개(오늘) + 나머지(과거 20일)로 통과 여부·점수를 계산한다."""
    today = bars[0]
    past = bars[1:]

    avg_volume = sum(b["volume"] for b in past) / len(past) if past else 0
    volume_ratio = today["volume"] / avg_volume if avg_volume > 0 else 0.0
    change_pct = abs(today.get("change_pct") or 0.0)

    passes = volume_ratio >= vol_threshold or change_pct >= pct_threshold
    score = (volume_ratio / vol_threshold) + (change_pct / pct_threshold)
    return passes, score


async def screen_tickers(
    tickers: list[str],
    *,
    volume_surge_ratio: float | None = None,
    change_pct_threshold: float | None = None,
    max_results: int | None = None,
) -> list[str]:
    """일봉 기반으로 전략 실행 대상 종목을 필터링한다.

    Parameters
    ----------
    tickers : 후보 종목 코드 리스트
    volume_surge_ratio : 20일 평균 대비 거래량 급등 배수 기준
    change_pct_threshold : 가격 변동률(±%) 기준
    max_results : 반환할 최대 종목 수

    Returns
    -------
    필터를 통과한 종목 코드 리스트 (점수 내림차순)
    """
    vol_thresh = volume_surge_ratio or SCREENER_VOLUME_SURGE_RATIO
    pct_thresh = change_pct_threshold or SCREENER_CHANGE_PCT_THRESHOLD
    cap = max_results or MAX_SCREENED_TICKERS

    async def _evaluate(ticker: str) -> tuple[str, bool, float]:
        try:
            bars = await fetch_recent_market_data(ticker, days=21)
        except Exception:
            logger.warning("screener: %s 데이터 조회 실패 — 건너뜀", ticker)
            return ticker, False, 0.0

        if len(bars) < _MIN_DATA_DAYS:
            logger.warning(
                "screener: %s 데이터 부족 (%d일) — 건너뜀", ticker, len(bars)
            )
            return ticker, False, 0.0

        passes, score = _score_ticker(bars, vol_thresh, pct_thresh)
        return ticker, passes, score

    results = await asyncio.gather(*(_evaluate(t) for t in tickers))

    passed = [(t, s) for t, ok, s in results if ok]
    passed.sort(key=lambda x: x[1], reverse=True)

    selected = [t for t, _ in passed[:cap]]
    logger.info(
        "screener: %d/%d 종목 통과 (vol>=%.1f OR chg>=%.1f%%)",
        len(selected),
        len(tickers),
        vol_thresh,
        pct_thresh,
    )
    return selected
