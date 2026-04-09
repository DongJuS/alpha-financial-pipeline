"""
src/backtest/cost_model.py — 매매 비용 계산

한국 KOSPI/KOSDAQ 기준:
- 수수료: 매수/매도 양방향 0.015 %
- 증권거래세: 매도 시에만 0.18 %
- 슬리피지: 고정 bps (재현성 확보)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.constants import (
    BACKTEST_COMMISSION_RATE_PCT,
    BACKTEST_SLIPPAGE_BPS,
    BACKTEST_TAX_RATE_PCT,
)


@dataclass(frozen=True)
class TradeCost:
    """매매 1건의 비용 내역."""

    commission: float
    tax: float
    slippage_cost: float
    total: float


class CostModel:
    """한국 시장 매매 비용 모델."""

    def __init__(
        self,
        commission_rate_pct: float = BACKTEST_COMMISSION_RATE_PCT,
        tax_rate_pct: float = BACKTEST_TAX_RATE_PCT,
        slippage_bps: int = BACKTEST_SLIPPAGE_BPS,
    ) -> None:
        self._commission_rate = commission_rate_pct / 100  # pct → ratio
        self._tax_rate = tax_rate_pct / 100
        self._slippage_rate = slippage_bps / 10_000  # bps → ratio

    def calculate(self, side: str, price: float, quantity: int) -> TradeCost:
        """매매 비용을 산출한다.

        Args:
            side: ``"BUY"`` 또는 ``"SELL"``.
            price: 체결 단가.
            quantity: 체결 수량.

        Returns:
            TradeCost: commission, tax, slippage_cost, total.
        """
        notional = price * quantity
        commission = notional * self._commission_rate
        tax = notional * self._tax_rate if side == "SELL" else 0.0
        slippage_cost = notional * self._slippage_rate
        return TradeCost(
            commission=commission,
            tax=tax,
            slippage_cost=slippage_cost,
            total=commission + tax + slippage_cost,
        )
