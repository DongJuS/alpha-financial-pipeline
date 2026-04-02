"""
src/utils/ticker.py — 티커 정규화 유틸리티

모든 종목 코드를 `CODE.SUFFIX` 형식(예: 005930.KS)으로 통일합니다.
- 한국 KOSPI: .KS
- 한국 KOSDAQ: .KQ
- 미국: .US
- 원자재: .CM
- 통화: .FX
- 금리: .RT

사용 예:
    from src.utils.ticker import normalize, to_raw, to_yahoo

    normalize("005930")         # → "005930.KS"  (DB 조회로 market 확인)
    normalize("005930.KS")      # → "005930.KS"  (이미 정규화됨)
    to_raw("005930.KS")         # → "005930"
    to_yahoo("005930.KS")       # → "005930.KS"  (Yahoo Finance는 동일 형식)
"""

from __future__ import annotations

import re
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)

# ── 시장 → 접미사 매핑 ────────────────────────────────────────────────────
MARKET_SUFFIX_MAP: dict[str, str] = {
    "KOSPI": "KS",
    "KOSDAQ": "KQ",
    "KONEX": "KN",
    "NYSE": "US",
    "NASDAQ": "US",
    "AMEX": "US",
    "COMMODITY": "CM",
    "CURRENCY": "FX",
    "RATE": "RT",
}

# ── 접미사 → 시장 역매핑 ──────────────────────────────────────────────────
SUFFIX_MARKET_MAP: dict[str, str] = {
    "KS": "KOSPI",
    "KQ": "KOSDAQ",
    "KN": "KONEX",
    "US": "NYSE",
    "CM": "COMMODITY",
    "FX": "CURRENCY",
    "RT": "RATE",
}

# 정규화된 티커 패턴: CODE.SUFFIX
_CANONICAL_PATTERN = re.compile(r"^[A-Za-z0-9]+\.[A-Z]{2}$")

# ── 인메모리 캐시 (DB 조회 결과) ──────────────────────────────────────────
_cache: dict[str, str] = {}


def is_canonical(ticker: str) -> bool:
    """이미 정규화된 형식(CODE.SUFFIX)인지 확인합니다."""
    return bool(_CANONICAL_PATTERN.match(ticker))


def to_raw(canonical: str) -> str:
    """정규화된 티커에서 접미사를 제거합니다.

    >>> to_raw("005930.KS")
    '005930'
    >>> to_raw("005930")
    '005930'
    """
    if "." in canonical:
        return canonical.rsplit(".", 1)[0]
    return canonical


def suffix_of(canonical: str) -> Optional[str]:
    """정규화된 티커에서 접미사를 추출합니다.

    >>> suffix_of("005930.KS")
    'KS'
    """
    if "." in canonical:
        return canonical.rsplit(".", 1)[1]
    return None


def market_of(canonical: str) -> Optional[str]:
    """정규화된 티커에서 시장명을 반환합니다.

    >>> market_of("005930.KS")
    'KOSPI'
    """
    sfx = suffix_of(canonical)
    return SUFFIX_MARKET_MAP.get(sfx, None) if sfx else None


def from_raw(raw_code: str, market: str) -> str:
    """raw 코드와 시장명으로 정규화된 티커를 생성합니다.

    >>> from_raw("005930", "KOSPI")
    '005930.KS'
    """
    suffix = MARKET_SUFFIX_MAP.get(market.upper())
    if suffix is None:
        logger.warning("알 수 없는 시장: %s (ticker=%s), 기본 KS 사용", market, raw_code)
        suffix = "KS"
    return f"{raw_code}.{suffix}"


def normalize(ticker: str, market: Optional[str] = None) -> str:
    """티커를 정규화합니다.

    이미 정규화된 형식이면 그대로 반환합니다.
    raw 코드만 있으면 market 인자 또는 인메모리 캐시를 사용합니다.

    Args:
        ticker: 정규화할 티커 (e.g., "005930" 또는 "005930.KS")
        market: 시장명 (e.g., "KOSPI"). None이면 캐시/DB 조회.

    Returns:
        정규화된 티커 (e.g., "005930.KS")
    """
    ticker = ticker.strip()

    # 이미 정규화된 형식이면 그대로 반환
    if is_canonical(ticker):
        return ticker

    # market이 주어지면 바로 생성
    if market:
        canonical = from_raw(ticker, market)
        _cache[ticker] = canonical
        return canonical

    # 캐시 확인
    if ticker in _cache:
        return _cache[ticker]

    # 한국 주식 코드 패턴 (6자리 숫자) → 기본 KOSPI
    if re.match(r"^\d{6}$", ticker):
        canonical = f"{ticker}.KS"
        _cache[ticker] = canonical
        logger.debug("normalize: %s → %s (기본 KOSPI 추정)", ticker, canonical)
        return canonical

    # 그 외: 접미사 없이 반환 (경고)
    logger.warning("normalize: 티커 '%s'의 시장 정보를 확인할 수 없습니다.", ticker)
    return ticker


def normalize_list(tickers: list[str], market: Optional[str] = None) -> list[str]:
    """티커 목록을 일괄 정규화합니다."""
    return [normalize(t, market) for t in tickers]


async def normalize_with_db(ticker: str) -> str:
    """DB의 instruments 테이블을 조회하여 정규화합니다.

    instruments에 없으면 stock_master를 폴백으로 조회합니다.
    """
    ticker = ticker.strip()

    if is_canonical(ticker):
        return ticker

    if ticker in _cache:
        return _cache[ticker]

    try:
        from src.utils.db_client import fetchrow

        # instruments 테이블 우선 조회 (raw_code → instrument_id)
        row = await fetchrow(
            "SELECT instrument_id FROM instruments WHERE raw_code = $1 AND is_active = TRUE",
            ticker,
        )
        if row:
            canonical = row["instrument_id"]
            _cache[ticker] = canonical
            return canonical

        # 폴백: stock_master에서 market 조회
        row = await fetchrow(
            "SELECT ticker, market FROM stock_master WHERE ticker = $1",
            ticker,
        )
        if row:
            canonical = from_raw(row["ticker"], row["market"])
            _cache[ticker] = canonical
            return canonical
    except Exception as e:
        logger.debug("normalize_with_db: DB 조회 실패 (%s), 인메모리 정규화 사용", e)

    return normalize(ticker)


def build_cache(mappings: list[tuple[str, str]]) -> None:
    """(raw_code, canonical) 쌍 목록으로 캐시를 구축합니다.

    서버 시작 시 instruments 전체를 로드하여 캐시를 워밍업합니다.
    """
    for raw_code, canonical in mappings:
        _cache[raw_code] = canonical
    logger.info("ticker 캐시 구축 완료: %d건", len(mappings))


def clear_cache() -> None:
    """캐시를 비웁니다 (테스트용)."""
    _cache.clear()


# ── 양방향 매칭 헬퍼 ─────────────────────────────────────────────────────

def matches(ticker_a: str, ticker_b: str) -> bool:
    """두 티커가 같은 종목인지 비교합니다.

    형식이 다르더라도 (005930 vs 005930.KS) 매칭됩니다.

    >>> matches("005930", "005930.KS")
    True
    >>> matches("005930.KS", "005930.KS")
    True
    >>> matches("005930", "000660")
    False
    """
    return to_raw(ticker_a) == to_raw(ticker_b)


def find_in_map(
    ticker: str,
    lookup: dict[str, str],
) -> Optional[str]:
    """딕셔너리에서 티커를 찾습니다. 정규화/raw 양쪽 모두 시도합니다.

    RLRunner에서 active_map 조회 시 유용합니다.

    >>> find_in_map("005930", {"005930.KS": "policy_123"})
    'policy_123'
    >>> find_in_map("005930.KS", {"005930": "policy_123"})
    'policy_123'
    """
    # 직접 매칭 (None이 아닌 값만)
    if ticker in lookup and lookup[ticker] is not None:
        return lookup[ticker]

    # 정규화 후 매칭
    canonical = normalize(ticker)
    if canonical in lookup and lookup[canonical] is not None:
        return lookup[canonical]

    # raw 코드로 매칭
    raw = to_raw(ticker)
    if raw in lookup and lookup[raw] is not None:
        return lookup[raw]

    # 딕셔너리 키를 raw로 변환하여 비교
    for key, value in lookup.items():
        if to_raw(key) == raw:
            return value

    return None
