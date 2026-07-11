"""
src/api/routers/system_trading_mode.py — trading mode (paper/real) 조회/전환.

UI header 의 토글이 이 endpoint 를 통해 mode 상태를 Redis 에 저장.
KIS credential 결정 지점은 매 요청 시 Redis 값 확인 후 정확한 계좌 선택.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.services.trading_mode import get_current_trading_mode, set_trading_mode

router = APIRouter(prefix="/system", tags=["system"])


class TradingModeResponse(BaseModel):
    mode: Literal["paper", "real"]


class TradingModeRequest(BaseModel):
    mode: Literal["paper", "real"] = Field(
        ..., description="'paper' (모의) 또는 'real' (실계좌)"
    )


@router.get("/trading-mode", response_model=TradingModeResponse)
async def get_trading_mode(
    _: Annotated[dict, Depends(get_current_user)],
) -> TradingModeResponse:
    """현재 활성 trading mode 반환."""
    return TradingModeResponse(mode=await get_current_trading_mode())


@router.post("/trading-mode", response_model=TradingModeResponse)
async def update_trading_mode(
    payload: TradingModeRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> TradingModeResponse:
    """trading mode 전환. Redis 에 저장 즉시 모든 pod 반영."""
    await set_trading_mode(payload.mode)
    return TradingModeResponse(mode=payload.mode)
