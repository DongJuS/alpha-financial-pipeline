"""
src/db/models.py — 코어 에이전트 공통 데이터 모델
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.utils.account_scope import AccountScope


class MarketDataPoint(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    name: str = Field(..., min_length=1)
    market: Literal["KOSPI", "KOSDAQ"]
    timestamp_kst: datetime
    interval: Literal["daily", "tick"] = "daily"
    open: int = Field(..., ge=0)
    high: int = Field(..., ge=0)
    low: int = Field(..., ge=0)
    close: int = Field(..., ge=0)
    volume: int = Field(..., ge=0)
    change_pct: Optional[float] = None
    market_cap: Optional[int] = None
    foreigner_ratio: Optional[float] = None


class PredictionSignal(BaseModel):
    agent_id: str
    llm_model: str
    strategy: Literal["A", "B", "RL", "S", "L"] = "A"
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
