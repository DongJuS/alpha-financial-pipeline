"""
src/db/models.py — 코어 에이전트 공통 데이터 모델
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.utils.account_scope import AccountScope
from src.utils.market_data import sanitize_change_pct


class MarketDataPoint(BaseModel):
    """ohlcv_daily 테이블 대응 모델.

    instrument_id: CODE.SUFFIX 형식 (예: 005930.KS)
    traded_at: 거래일 (DATE, timezone 없음)
    가격 필드: float (NUMERIC(15,4))
    adj_close: 수정종가 (optional)

    하위 호환: ticker/timestamp_kst/interval 별칭을 유지합니다.
    """
    instrument_id: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1)
    market: Literal["KOSPI", "KOSDAQ"]
    traded_at: date
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    close: float = Field(..., ge=0)
    volume: int = Field(..., ge=0)
    change_pct: Optional[float] = None
    adj_close: Optional[float] = None

    # ── 하위 호환 프로퍼티 ───────────────────────────────────────────
    @property
    def ticker(self) -> str:
        """instrument_id 의 raw_code 부분 반환 (하위 호환)."""
        return self.instrument_id.split(".")[0] if "." in self.instrument_id else self.instrument_id

    @property
    def timestamp_kst(self) -> datetime:
        """traded_at → datetime 변환 (하위 호환)."""
        return datetime(self.traded_at.year, self.traded_at.month, self.traded_at.day, 15, 30)

    @property
    def interval(self) -> str:
        """ohlcv_daily 전용이므로 항상 'daily' 반환 (하위 호환)."""
        return "daily"

    @field_validator("change_pct", mode="before")
    @classmethod
    def _sanitize_change_pct(cls, value: object) -> Optional[float]:
        return sanitize_change_pct(value)


class PredictionSignal(BaseModel):
    agent_id: str
    llm_model: str
    strategy: Literal["A", "B", "RL", "S", "L", "BLEND"] = "A"
    ticker: str
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_price: Optional[int] = Field(default=None, ge=0)
    stop_loss: Optional[int] = Field(default=None, ge=0)
    reasoning_summary: Optional[str] = None
    debate_transcript_id: Optional[int] = None
    trading_date: date
    is_shadow: bool = False


class PaperOrderRequest(BaseModel):
    ticker: str
    name: str
    signal: Literal["BUY", "SELL", "HOLD"]
    quantity: int = Field(default=1, ge=1)
    price: int = Field(..., ge=0)
    signal_source: Literal["A", "B", "BLEND", "RL", "S", "L", "EXIT", "VIRTUAL"] = "A"
    agent_id: str = "portfolio_manager_agent"
    account_scope: AccountScope = "paper"
    strategy_id: Optional[str] = None
    blend_meta: Optional[dict] = None


class AgentHeartbeatRecord(BaseModel):
    agent_id: str
    status: Literal["healthy", "degraded", "error", "dead"] = "healthy"
    last_action: Optional[str] = None
    metrics: Optional[dict] = None


class NotificationRecord(BaseModel):
    event_type: str
    message: str
    success: bool = True
    error_msg: Optional[str] = None


# ── 마켓플레이스 확장 모델 ─────────────────────────────────────────────────────


class StockMasterRecord(BaseModel):
    """KRX 전종목 마스터 데이터."""
    ticker: str = Field(..., min_length=1, max_length=10)
    name: str = Field(..., min_length=1)
    market: Literal["KOSPI", "KOSDAQ", "KONEX"]
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[int] = None
    listing_date: Optional[date] = None
    is_etf: bool = False
    is_etn: bool = False
    is_active: bool = True
    tier: Literal["core", "extended", "universe"] = "universe"


class MacroIndicator(BaseModel):
    """해외지수/환율/원자재/금리 매크로 지표."""
    category: Literal["index", "currency", "commodity", "rate"]
    symbol: str
    name: str
    value: float
    change_pct: Optional[float] = None
    previous_close: Optional[float] = None
    snapshot_date: date
    source: str = "fdr"


class DailyRanking(BaseModel):
    """일별 사전 계산 랭킹 (시가총액, 거래량, 상승률 등)."""
    ranking_date: date
    ranking_type: Literal[
        "market_cap", "volume", "turnover", "gainer", "loser", "new_high", "new_low"
    ]
    rank: int = Field(..., ge=1)
    ticker: str
    name: str
    value: Optional[float] = None
    change_pct: Optional[float] = None
    extra: Optional[dict] = None


class WatchlistItem(BaseModel):
    """사용자 관심 종목."""
    user_id: str
    group_name: str = "default"
    ticker: str
    name: str
    price_alert_above: Optional[int] = None
    price_alert_below: Optional[int] = None
