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
    strategy: Literal["A", "B"] = "A"
    ticker: str
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_price: Optional[int] = Field(default=None, ge=0)
    stop_loss: Optional[int] = Field(default=None, ge=0)
    reasoning_summary: Optional[str] = None
    debate_transcript_id: Optional[int] = None
    trading_date: date


class PaperOrderRequest(BaseModel):
    ticker: str
    name: str
    signal: Literal["BUY", "SELL", "HOLD"]
    quantity: int = Field(default=1, ge=1)
    price: int = Field(..., ge=0)
    signal_source: Literal["A", "B", "BLEND"] = "A"
    agent_id: str = "portfolio_manager_agent"
    account_scope: AccountScope = "paper"


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
