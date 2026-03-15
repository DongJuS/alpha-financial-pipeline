"""
src/agents/rl_dataset_builder_v2.py — RL 데이터셋 빌더 V2

market/research feature를 통합한 확장 데이터셋 빌더.
기존 RLDatasetBuilder(가격만)에 기술 지표, 매크로, 섹터 컨텍스트를 추가합니다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Literal, Optional

from src.db.models import PredictionSignal
from src.db.queries import fetch_recent_market_data
from src.utils.logging import get_logger
from src.utils.redis_client import (
    KEY_MACRO_CONTEXT,
    KEY_MARKET_INDEX,
    KEY_SECTOR_MAP,
    TTL_MACRO_CONTEXT,
    get_redis,
)

logger = get_logger(__name__)

RLInterval = Literal["daily", "tick"]


# ── Feature 구성 ─────────────────────────────────────────────────────────


@dataclass
class TechnicalFeatures:
    """가격 기반 기술 지표."""

    sma_5: list[float] = field(default_factory=list)
    sma_20: list[float] = field(default_factory=list)
    sma_60: list[float] = field(default_factory=list)
    rsi_14: list[float] = field(default_factory=list)
    volatility_10: list[float] = field(default_factory=list)
    volume_ratio: list[float] = field(default_factory=list)  # vol / sma20_vol
    returns: list[float] = field(default_factory=list)


@dataclass
class MarketContext:
    """매크로/시장 컨텍스트."""

    kospi_change_pct: Optional[float] = None
    kosdaq_change_pct: Optional[float] = None
    usd_krw: Optional[float] = None
    vix: Optional[float] = None
    sector: Optional[str] = None
    sector_avg_change_pct: Optional[float] = None


@dataclass
class EnrichedRLDataset:
    """기술 지표 + 매크로 컨텍스트가 포함된 확장 데이터셋."""

    ticker: str
    closes: list[float]
    volumes: list[float]
    timestamps: list[str]
    technical: TechnicalFeatures
    market_context: MarketContext
    dataset_version: str  # "v2_enriched"
    data_hash: str  # SHA256 first 12 chars
    feature_count: int  # 총 feature 수
    created_at: str

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "closes": self.closes,
            "volumes": self.volumes,
            "timestamps": self.timestamps,
            "technical": asdict(self.technical),
            "market_context": asdict(self.market_context),
            "dataset_version": self.dataset_version,
            "data_hash": self.data_hash,
            "feature_count": self.feature_count,
            "created_at": self.created_at,
        }


# ── Feature 계산 유틸리티 ─────────────────────────────────────────────────


def compute_sma(values: list[float], window: int) -> list[float]:
    """단순 이동 평균. 데이터 부족 구간은 NaN 대신 첫 유효값으로 채움."""
    result: list[float] = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(sum(values[: i + 1]) / (i + 1))
        else:
            result.append(sum(values[i - window + 1 : i + 1]) / window)
    return result


def compute_rsi(closes: list[float], period: int = 14) -> list[float]:
    """RSI (0~100). Wilder smoothing."""
    if len(closes) < 2:
        return [50.0] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0, d) for d in deltas]
    losses = [max(0, -d) for d in deltas]

    rsi_values: list[float] = [50.0]  # 첫 번째 값

    if len(deltas) < period:
        avg_gain = sum(gains) / max(len(gains), 1)
        avg_loss = sum(losses) / max(len(losses), 1)
        for _ in deltas:
            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100.0 - 100.0 / (1.0 + rs))
        return rsi_values

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period):
        rsi_values.append(50.0)  # 초기 구간

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))

    return rsi_values


def compute_volatility(closes: list[float], window: int = 10) -> list[float]:
    """rolling std of returns."""
    if len(closes) < 2:
        return [0.0] * len(closes)
    returns = [0.0] + [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))]
    result: list[float] = []
    for i in range(len(returns)):
        start = max(0, i - window + 1)
        segment = returns[start : i + 1]
        if len(segment) < 2:
            result.append(0.0)
        else:
            mean = sum(segment) / len(segment)
            var = sum((x - mean) ** 2 for x in segment) / (len(segment) - 1)
            result.append(var**0.5)
    return result


def compute_volume_ratio(volumes: list[float], window: int = 20) -> list[float]:
    """현재 거래량 / SMA(거래량)."""
    sma_vol = compute_sma(volumes, window)
    return [
        (v / sv if sv > 0 else 1.0)
        for v, sv in zip(volumes, sma_vol)
    ]


def compute_returns(closes: list[float]) -> list[float]:
    """일간 수익률."""
    if len(closes) < 2:
        return [0.0] * len(closes)
    return [0.0] + [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))]


def compute_data_hash(closes: list[float]) -> str:
    """SHA256 해시 (처음 12자)."""
    raw = json.dumps(closes, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ── 데이터셋 빌더 V2 ─────────────────────────────────────────────────────


class RLDatasetBuilderV2:
    """market/research feature를 통합한 확장 데이터셋 빌더.

    기존 RLDatasetBuilder와 동일한 인터페이스 + 기술 지표/매크로 확장.
    """

    def __init__(
        self,
        min_history_points: int = 40,
        default_interval: RLInterval = "daily",
    ) -> None:
        self.min_history_points = min_history_points
        self.default_interval = default_interval

    async def build_dataset(
        self,
        ticker: str,
        days: int = 120,
        *,
        interval: RLInterval | None = None,
        seconds: int | None = None,
        limit: int | None = None,
        enrich: bool = True,
    ) -> EnrichedRLDataset:
        """확장 데이터셋 구축.

        Args:
            ticker: 종목 코드
            days: 수집 기간 (일)
            interval: "daily" | "tick"
            seconds: tick 간격 시 초 단위 범위
            limit: 최대 row 수
            enrich: True면 기술 지표 + 매크로 컨텍스트 추가
        """
        resolved_interval = interval or self.default_interval
        query_days = days if resolved_interval == "daily" else None
        query_seconds = seconds
        if resolved_interval == "tick" and query_seconds is None and days is not None and limit is None:
            query_seconds = max(1, days * 24 * 60 * 60)
        if resolved_interval == "tick" and query_seconds is None and limit is None:
            limit = 5_000

        rows = await fetch_recent_market_data(
            ticker,
            interval=resolved_interval,
            days=query_days,
            seconds=query_seconds,
            limit=limit,
        )
        ordered_rows = sorted(rows, key=lambda row: row["timestamp_kst"])
        closes = [float(row["close"]) for row in ordered_rows if row.get("close")]
        volumes = [float(row.get("volume", 0)) for row in ordered_rows if row.get("close")]
        timestamps = [str(row["timestamp_kst"]) for row in ordered_rows if row.get("close")]

        if len(closes) < self.min_history_points:
            raise ValueError(
                f"RL 학습 이력 부족: ticker={ticker}, interval={resolved_interval}, "
                f"history={len(closes)}, required={self.min_history_points}"
            )

        # 기술 지표 계산
        technical = self._compute_technical(closes, volumes) if enrich else TechnicalFeatures()

        # 매크로 컨텍스트 수집
        market_context = await self._fetch_market_context(ticker) if enrich else MarketContext()

        feature_count = self._count_features(technical, market_context)

        return EnrichedRLDataset(
            ticker=ticker,
            closes=closes,
            volumes=volumes,
            timestamps=timestamps,
            technical=technical,
            market_context=market_context,
            dataset_version="v2_enriched",
            data_hash=compute_data_hash(closes),
            feature_count=feature_count,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _compute_technical(
        self, closes: list[float], volumes: list[float]
    ) -> TechnicalFeatures:
        """기술 지표 일괄 계산."""
        return TechnicalFeatures(
            sma_5=compute_sma(closes, 5),
            sma_20=compute_sma(closes, 20),
            sma_60=compute_sma(closes, 60),
            rsi_14=compute_rsi(closes, 14),
            volatility_10=compute_volatility(closes, 10),
            volume_ratio=compute_volume_ratio(volumes, 20) if volumes else [],
            returns=compute_returns(closes),
        )

    async def _fetch_market_context(self, ticker: str) -> MarketContext:
        """Redis에서 매크로/시장 컨텍스트 수집."""
        ctx = MarketContext()
        try:
            redis = await get_redis()

            # 시장 지수
            index_raw = await redis.get(KEY_MARKET_INDEX)
            if index_raw:
                index_data = json.loads(index_raw)
                ctx.kospi_change_pct = index_data.get("kospi_change_pct")
                ctx.kosdaq_change_pct = index_data.get("kosdaq_change_pct")

            # 매크로 컨텍스트 (환율, VIX 등)
            macro_raw = await redis.get(KEY_MACRO_CONTEXT)
            if macro_raw:
                macro_data = json.loads(macro_raw)
                ctx.usd_krw = macro_data.get("usd_krw")
                ctx.vix = macro_data.get("vix")

            # 섹터 정보
            sector_raw = await redis.get(KEY_SECTOR_MAP)
            if sector_raw:
                sector_data = json.loads(sector_raw)
                for sector_name, tickers in sector_data.items():
                    if ticker in tickers:
                        ctx.sector = sector_name
                        break

        except Exception as e:
            logger.warning("매크로 컨텍스트 수집 실패 (fallback): %s", e)

        return ctx

    def _count_features(
        self, technical: TechnicalFeatures, market_context: MarketContext
    ) -> int:
        """총 feature 수 계산."""
        tech_count = sum(
            1
            for v in [
                technical.sma_5,
                technical.sma_20,
                technical.sma_60,
                technical.rsi_14,
                technical.volatility_10,
                technical.volume_ratio,
                technical.returns,
            ]
            if v
        )
        ctx_count = sum(
            1
            for v in [
                market_context.kospi_change_pct,
                market_context.kosdaq_change_pct,
                market_context.usd_krw,
                market_context.vix,
                market_context.sector,
            ]
            if v is not None
        )
        return tech_count + ctx_count

    def to_state_vector(
        self, dataset: EnrichedRLDataset, idx: int
    ) -> dict[str, float]:
        """특정 시점의 feature vector를 dict로 반환.

        TabularQTrainerV2 또는 향후 DQN/PPO에서 사용.
        """
        t = dataset.technical
        vector: dict[str, float] = {}

        if t.returns and idx < len(t.returns):
            vector["return"] = t.returns[idx]
        if t.sma_5 and t.sma_20 and idx < len(t.sma_5):
            sma5 = t.sma_5[idx]
            sma20 = t.sma_20[idx]
            vector["sma_cross"] = (sma5 - sma20) / sma20 if sma20 > 0 else 0.0
        if t.sma_5 and t.sma_60 and idx < len(t.sma_60):
            sma5 = t.sma_5[idx]
            sma60 = t.sma_60[idx]
            vector["trend"] = (sma5 - sma60) / sma60 if sma60 > 0 else 0.0
        if t.rsi_14 and idx < len(t.rsi_14):
            vector["rsi"] = t.rsi_14[idx]
        if t.volatility_10 and idx < len(t.volatility_10):
            vector["volatility"] = t.volatility_10[idx]
        if t.volume_ratio and idx < len(t.volume_ratio):
            vector["volume_ratio"] = t.volume_ratio[idx]

        # 매크로 컨텍스트
        mc = dataset.market_context
        if mc.kospi_change_pct is not None:
            vector["kospi_chg"] = mc.kospi_change_pct
        if mc.usd_krw is not None:
            vector["usd_krw"] = mc.usd_krw

        return vector
