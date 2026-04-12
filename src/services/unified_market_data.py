"""
src/services/unified_market_data.py -- 통합 시장 데이터 빌더

일봉(ohlcv_daily) + 분봉(ohlcv_minute) 데이터를 통합하여
RL 학습/추론과 LLM 프롬프트에 제공합니다.

Phase 0: 빌더 + compute_intraday_features()
Phase 1: to_rl_features() -- RL 피처 벡터에 분봉 파생 피처 추가
Phase 2: to_llm_context() -- LLM 프롬프트에 장중 패턴 요약 추가
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class IntradayFeatures:
    """분봉 데이터에서 파생한 장중 피처."""

    vwap_deviation: float = 0.0  # (close - vwap) / vwap, clamp [-1, 1]
    volume_skew: float = 0.0  # am_volume / total_volume - 0.5
    intraday_volatility: float = 0.0  # Phase 3용, 기본 0.0
    tick_intensity: float = 0.0  # Phase 3용, 기본 0.0


@dataclass
class UnifiedMarketData:
    """일봉 + 분봉 통합 데이터."""

    instrument_id: str
    traded_at: date
    # 일봉 데이터
    daily_open: float = 0.0
    daily_high: float = 0.0
    daily_low: float = 0.0
    daily_close: float = 0.0
    daily_volume: int = 0
    daily_change_pct: Optional[float] = None
    # 분봉 파생 피처
    intraday: IntradayFeatures = field(default_factory=IntradayFeatures)
    # 메타
    has_minute_data: bool = False
    minute_bar_count: int = 0


def compute_intraday_features(bars: list[dict]) -> IntradayFeatures:
    """분봉 데이터에서 장중 피처를 계산합니다.

    Args:
        bars: ohlcv_minute 조회 결과 리스트.
              각 dict는 bucket_at, open, high, low, close, volume, vwap 포함.

    Returns:
        IntradayFeatures: 분봉 파생 피처. bars가 비어있으면 모든 값 0.0.
    """
    if not bars:
        return IntradayFeatures()

    total_volume = sum(b["volume"] for b in bars)
    if total_volume <= 0:
        return IntradayFeatures()

    # VWAP deviation: (종가 - 일중 VWAP) / 일중 VWAP
    last_close = bars[-1]["close"]
    daily_vwap = sum(b["vwap"] * b["volume"] for b in bars) / total_volume
    if daily_vwap > 0:
        vwap_deviation = (last_close - daily_vwap) / daily_vwap
        vwap_deviation = max(-1.0, min(1.0, vwap_deviation))
    else:
        vwap_deviation = 0.0

    # Volume skew: 오전 거래량 비율 - 0.5
    am_volume = sum(
        b["volume"] for b in bars if _get_hour(b["bucket_at"]) < 12
    )
    volume_skew = (am_volume / total_volume) - 0.5

    return IntradayFeatures(
        vwap_deviation=vwap_deviation,
        volume_skew=volume_skew,
    )


def _get_hour(bucket_at: object) -> int:
    """bucket_at에서 시간(hour)을 추출합니다. datetime과 다양한 타입 대응."""
    if isinstance(bucket_at, datetime):
        return bucket_at.hour
    if hasattr(bucket_at, "hour"):
        return bucket_at.hour
    return 0


async def build_unified_data(
    instrument_id: str,
    traded_at: date,
    daily_row: Optional[dict] = None,
) -> UnifiedMarketData:
    """일봉 + 분봉 데이터를 통합한 UnifiedMarketData를 빌드합니다.

    Args:
        instrument_id: 종목 ID (예: '005930.KS')
        traded_at: 거래일
        daily_row: 일봉 데이터 dict (없으면 일봉 없이 분봉만 시도)

    Returns:
        UnifiedMarketData
    """
    data = UnifiedMarketData(
        instrument_id=instrument_id,
        traded_at=traded_at,
    )

    # 일봉 데이터 설정
    if daily_row:
        data.daily_open = float(daily_row.get("open", 0))
        data.daily_high = float(daily_row.get("high", 0))
        data.daily_low = float(daily_row.get("low", 0))
        data.daily_close = float(daily_row.get("close", 0))
        data.daily_volume = int(daily_row.get("volume", 0))
        data.daily_change_pct = daily_row.get("change_pct")

    # 분봉 데이터 조회 + 피처 계산 (지연 import — PR 1 순환 의존 방지)
    try:
        from src.db.queries import fetch_minute_bars

        start = datetime(traded_at.year, traded_at.month, traded_at.day, 0, 0, 0)
        end = datetime(traded_at.year, traded_at.month, traded_at.day, 23, 59, 59)
        minute_bars = await fetch_minute_bars(instrument_id, start, end)

        if minute_bars:
            data.intraday = compute_intraday_features(minute_bars)
            data.has_minute_data = True
            data.minute_bar_count = len(minute_bars)
    except Exception as exc:
        logger.warning(
            "분봉 데이터 조회 실패 (%s, %s) -- 일봉 only fallback: %s",
            instrument_id,
            traded_at,
            exc,
        )

    return data
