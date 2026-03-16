"""
src/gen/server.py — Gen 데이터 REST API 서버

1초마다 자동으로 랜덤 시세를 생성하며,
CollectorAgent가 호출할 수 있는 REST 엔드포인트를 제공합니다.

Usage:
    uvicorn src.gen.server:app --host 0.0.0.0 --port 9999
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from src.gen.generator import MarketDataGenerator
from src.gen.models import (
    GenIndex,
    GenMacro,
    GenOHLCV,
    GenQuote,
    GenStatus,
    GenTick,
    GenTicker,
)

# ── 전역 Generator 인스턴스 ──────────────────────────────────────────────────

_generator = MarketDataGenerator()
_bg_task: Optional[asyncio.Task] = None


async def _tick_loop() -> None:
    """1초마다 모든 종목의 틱 데이터를 자동 생성합니다."""
    while True:
        _generator.generate_tick()
        await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bg_task
    _bg_task = asyncio.create_task(_tick_loop())
    yield
    if _bg_task:
        _bg_task.cancel()
        try:
            await _bg_task
        except asyncio.CancelledError:
            pass


# ── FastAPI 앱 ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Gen Data Server",
    description="수집→저장 파이프라인 테스트용 랜덤 시세 생성 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@app.get("/gen/status", response_model=GenStatus)
async def get_status():
    """Gen 서버 상태를 반환합니다."""
    return _generator.get_status()


@app.get("/gen/tickers", response_model=list[GenTicker])
async def get_tickers():
    """전체 종목 마스터 리스트를 반환합니다. (FDR StockListing 대체)"""
    return _generator.get_tickers()


@app.get("/gen/ohlcv/{ticker}", response_model=list[GenOHLCV])
async def get_ohlcv(
    ticker: str,
    days: int = Query(default=120, ge=1, le=3650, description="과거 N일"),
):
    """특정 종목의 일봉 히스토리를 반환합니다. (FDR DataReader 대체)"""
    return _generator.generate_daily_history(ticker, days=days)


@app.get("/gen/quote/{ticker}", response_model=GenQuote)
async def get_quote(ticker: str):
    """특정 종목의 현재가 스냅샷을 반환합니다. (KIS REST 시세 대체)"""
    quote = _generator.get_quote(ticker)
    if not quote:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"종목 {ticker}을(를) 찾을 수 없습니다.")
    return quote


@app.get("/gen/quotes", response_model=list[GenQuote])
async def get_all_quotes():
    """전체 종목의 현재가 스냅샷을 반환합니다."""
    return _generator.get_all_quotes()


@app.get("/gen/ticks/{ticker}", response_model=list[GenTick])
async def get_ticks(
    ticker: str,
    count: int = Query(default=10, ge=1, le=100, description="최근 N건"),
):
    """특정 종목의 최근 틱 데이터를 반환합니다. (KIS WebSocket 대체)"""
    return _generator.get_ticks(ticker, count=count)


@app.get("/gen/index", response_model=list[GenIndex])
async def get_indices():
    """KOSPI/KOSDAQ 지수를 반환합니다."""
    return _generator.get_indices()


@app.get("/gen/macro", response_model=list[GenMacro])
async def get_macro():
    """매크로 지표 (환율, 금, 유가, 금리, 해외지수)를 반환합니다."""
    return _generator.get_macro()


# ── CLI 실행 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.gen.server:app",
        host="0.0.0.0",
        port=9999,
        reload=False,
        log_level="info",
    )
