"""
src/agents/rl_intraday_features.py — 일봉 백본에 분봉(ohlcv_minute) 유래 일중 특징 join

RL 학습용 데이터셋에서 풍부한 일봉(ohlcv_daily) 시계열을 백본으로 두고,
각 거래일에 그날의 분봉에서 집계한 '일중 특징'을 컬럼으로 덧붙인다.
분봉이 없는 과거 거래일은 중립값(0.0) + has_intraday=0.0 으로 채운다(마스킹).

왜 이렇게: 일봉은 ~수개월~수년 있지만 분봉은 실시간 수집 이후(수주)만 있다.
가격 그래프(종가)는 일봉 연속을 그대로 유지하고, 일중 특징만 '있는 날에만' 채워
가짜 데이터를 합성하지 않는다(마스킹 방식). has_intraday 플래그로 모델이
'일중 정보 없음'을 명시적으로 구분할 수 있게 한다.

이 모듈은 순수 함수만 제공한다(DB 접근 없음) — 단위 테스트 용이.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

# RL 관측 벡터에 추가될 일중 특징 키 (순서 고정 — 관측 차원 안정성 보장)
INTRADAY_FEATURE_KEYS: tuple[str, ...] = (
    "intraday_range_pct",
    "intraday_return",
    "intraday_volatility",
    "vwap_dev",
    "volume_skew",
)

# 분봉 없는 날 채울 중립값 (정규화 기준 0 = '평균/정보 없음')
NEUTRAL_INTRADAY: dict[str, float] = {k: 0.0 for k in INTRADAY_FEATURE_KEYS}

# has_intraday 까지 포함한 전체 추가 키 (관측 벡터 확장 차원)
INTRADAY_OBS_KEYS: tuple[str, ...] = INTRADAY_FEATURE_KEYS + ("has_intraday",)


def _as_date(value: Any) -> date | None:
    """date / datetime / ISO 문자열을 date 로 정규화한다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return datetime.fromisoformat(text[:19].replace("Z", "")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return var ** 0.5


def _vwap(bars: list[dict]) -> float:
    """거래량 가중 평균가. vwap 컬럼이 있으면 거래량가중, 없으면 close 사용."""
    num = 0.0
    den = 0.0
    for b in bars:
        vol = float(b.get("volume") or 0.0)
        price = b.get("vwap")
        price = float(price) if price is not None else float(b["close"])
        num += price * vol
        den += vol
    if den <= 0:
        closes = [float(b["close"]) for b in bars]
        return sum(closes) / len(closes) if closes else 0.0
    return num / den


def _volume_skew(volumes: list[float]) -> float:
    """전반부 vs 후반부 거래량 편중 (장초반 집중 프록시). 범위 약 [-1, 1]."""
    total = sum(volumes)
    if total <= 0 or len(volumes) < 2:
        return 0.0
    half = len(volumes) // 2
    first = sum(volumes[:half])
    second = sum(volumes[half:])
    return (first - second) / total


def compute_day_intraday_features(minute_bars: list[dict]) -> dict[str, float]:
    """하루치 분봉 리스트에서 일중 특징을 계산한다.

    Parameters
    ----------
    minute_bars : [{open, high, low, close, volume, vwap?, bucket_at?}, ...]
        시간 정렬은 내부에서 처리한다.

    Returns
    -------
    INTRADAY_FEATURE_KEYS 에 대응하는 float dict. 데이터가 비거나 불충분하면 중립값.
    """
    bars = [b for b in minute_bars if b.get("close") is not None]
    if not bars:
        return dict(NEUTRAL_INTRADAY)

    bars = sorted(bars, key=lambda b: (b.get("bucket_at") is None, b.get("bucket_at")))
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars if b.get("high") is not None]
    lows = [float(b["low"]) for b in bars if b.get("low") is not None]
    volumes = [float(b.get("volume") or 0.0) for b in bars]

    first_open = float(bars[0].get("open") or closes[0])
    last_close = closes[-1]
    day_high = max(highs) if highs else max(closes)
    day_low = min(lows) if lows else min(closes)

    intraday_range_pct = (day_high - day_low) / last_close if last_close else 0.0
    intraday_return = (last_close / first_open - 1.0) if first_open else 0.0
    rets = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(1, len(closes))
        if closes[i - 1]
    ]
    intraday_volatility = _std(rets)
    vwap_day = _vwap(bars)
    vwap_dev = (last_close / vwap_day - 1.0) if vwap_day else 0.0
    volume_skew = _volume_skew(volumes)

    return {
        "intraday_range_pct": intraday_range_pct,
        "intraday_return": intraday_return,
        "intraday_volatility": intraday_volatility,
        "vwap_dev": vwap_dev,
        "volume_skew": volume_skew,
    }


def join_daily_with_intraday(
    daily_rows: list[dict],
    minute_rows: list[dict],
) -> list[dict]:
    """일봉 행에 그날의 일중 특징을 left join 한다.

    Parameters
    ----------
    daily_rows : ohlcv_daily 행 [{traded_at, open, high, low, close, ...}, ...]
    minute_rows : ohlcv_minute 행 [{bucket_at, open, high, low, close, volume, vwap}, ...]

    Returns
    -------
    각 일봉 행에 INTRADAY_FEATURE_KEYS + 'has_intraday' 가 추가된 dict 리스트.
    분봉 없는 날은 중립값 + has_intraday=0.0 (가격 백본은 일봉 그대로 — 합성 없음).
    """
    by_day: dict[date, list[dict]] = defaultdict(list)
    for m in minute_rows:
        d = _as_date(m.get("bucket_at"))
        if d is not None:
            by_day[d].append(m)

    enriched: list[dict] = []
    for row in daily_rows:
        d = _as_date(row.get("traded_at"))
        out = dict(row)
        day_bars = by_day.get(d) if d is not None else None
        if day_bars:
            out.update(compute_day_intraday_features(day_bars))
            out["has_intraday"] = 1.0
        else:
            out.update(NEUTRAL_INTRADAY)
            out["has_intraday"] = 0.0
        enriched.append(out)
    return enriched


def intraday_obs_vector(row: dict) -> list[float]:
    """일중 특징 + has_intraday 를 고정 순서 float 벡터로 추출한다 (관측 벡터 확장용)."""
    return [float(row.get(k, 0.0)) for k in INTRADAY_OBS_KEYS]
