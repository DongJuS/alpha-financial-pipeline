"""
src/gen/models.py — Gen 데이터 생성용 Pydantic 모델

기존 MarketDataPoint / MacroIndicator 등과 호환되는
REST 응답 모델을 정의합니다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GenTicker(BaseModel):
    """종목 마스터 정보 (FDR StockListing 대체)."""
    ticker: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    sector: Optional[str] = None
    base_price: int = Field(..., ge=100, description="기준가 (랜덤 변동의 anchor)")


class GenOHLCV(BaseModel):
    """일봉 OHLCV 한 행."""
    ticker: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    date: str  # YYYY-MM-DD
    open: int
    high: int
    low: int
    close: int
    volume: int
    change_pct: float


class GenQuote(BaseModel):
    """현재가 스냅샷 (KIS REST 시세 대체)."""
    ticker: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    current_price: int
    open: int
    high: int
    low: int
    volume: int
    change_pct: float
    updated_at: str  # ISO-8601


class GenTick(BaseModel):
    """실시간 틱 1건 (KIS WebSocket 대체)."""
    ticker: str
    name: str
    price: int
    volume: int
    timestamp: str  # ISO-8601


class GenIndex(BaseModel):
    """지수 데이터 (KOSPI/KOSDAQ 지수)."""
    symbol: str
    name: str
    value: float
    change_pct: float
    updated_at: str


class GenMacro(BaseModel):
    """매크로 지표 (환율, 금, 유가 등)."""
    category: Literal["index", "currency", "commodity", "rate"]
    symbol: str
    name: str
    value: float
    change_pct: float
    previous_close: float
    snapshot_date: str


class GenStatus(BaseModel):
    """Gen 서버 상태."""
    running: bool
    tick_count: int
    tickers_count: int
    uptime_seconds: float
    last_generated_at: Optional[str] = None
