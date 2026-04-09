"""src/backtest/engine.py — BacktestEngine 핵심 시뮬레이션.

test 기간 가격 데이터로 매매 시뮬레이션을 실행하고 결과를 반환한다.
인메모리 상태(cash, position_qty, avg_buy_price)를 추적하며,
SignalSource에서 시그널을 받아 CostModel로 비용을 차감한다.
"""

from __future__ import annotations

from datetime import date

from src.backtest.cost_model import CostModel
from src.backtest.metrics import compute_backtest_metrics
from src.backtest.models import (
    BacktestConfig,
    BacktestResult,
    DailySnapshot,
    TradeRecord,
)
from src.backtest.signal_source import SignalSource


class BacktestEngine:
    """백테스트 시뮬레이션 엔진."""

    def __init__(
        self,
        config: BacktestConfig,
        signal_source: SignalSource,
        cost_model: CostModel,
    ) -> None:
        self._config = config
        self._signal = signal_source
        self._cost = cost_model

        # 시뮬레이션 상태 (run() 호출 시 초기화)
        self._cash: float = 0.0
        self._position_qty: int = 0
        self._avg_buy_price: float = 0.0
        self._prev_portfolio_value: float = 0.0

    def run(self, prices: list[float], dates: list[date]) -> BacktestResult:
        """test 기간 데이터로 시뮬레이션 실행."""
        if self._config.train_end >= self._config.test_start:
            raise ValueError(
                f"train_end ({self._config.train_end}) must be before "
                f"test_start ({self._config.test_start})"
            )
        if len(prices) != len(dates):
            raise ValueError("prices and dates must have the same length")

        # 상태 초기화
        self._cash = float(self._config.initial_capital)
        self._position_qty = 0
        self._avg_buy_price = 0.0
        self._prev_portfolio_value = float(self._config.initial_capital)

        trades: list[TradeRecord] = []
        snapshots: list[DailySnapshot] = []
        price_history: list[float] = []

        for dt, close_price in zip(dates, prices):
            price_history.append(close_price)

            signal = self._signal.get_signal(dt, price_history, self._position_qty)
            trade = self._execute_trade(signal, close_price, dt)
            if trade is not None:
                trades.append(trade)

            snapshot = self._take_snapshot(dt, close_price)
            snapshots.append(snapshot)

        metrics = compute_backtest_metrics(snapshots, trades, self._config)
        return BacktestResult(
            config=self._config,
            metrics=metrics,
            trades=trades,
            daily_snapshots=snapshots,
        )

    def _execute_trade(
        self, side: str, price: float, dt: date
    ) -> TradeRecord | None:
        """인메모리 포지션 추적 + 비용 차감."""
        if side == "BUY" and self._position_qty == 0:
            return self._open_position(dt, price)
        if side in ("SELL", "CLOSE") and self._position_qty > 0:
            return self._close_position(dt, price)
        return None

    def _open_position(self, dt: date, price: float) -> TradeRecord | None:
        """가용 현금 전액 매수 (정수 주 단위)."""
        unit_cost = self._cost.calculate("BUY", price, 1)
        effective_price = price + unit_cost.total
        if effective_price <= 0:
            return None

        quantity = int(self._cash // effective_price)
        if quantity <= 0:
            return None

        cost = self._cost.calculate("BUY", price, quantity)
        total_outlay = price * quantity + cost.total
        if total_outlay > self._cash:
            quantity -= 1
            if quantity <= 0:
                return None
            cost = self._cost.calculate("BUY", price, quantity)

        self._cash -= price * quantity + cost.total
        self._avg_buy_price = price
        self._position_qty = quantity

        return TradeRecord(
            date=dt,
            side="BUY",
            ticker=self._config.ticker,
            price=price,
            quantity=quantity,
            commission=cost.commission,
            tax=cost.tax,
            slippage_cost=cost.slippage_cost,
            total_cost=cost.total,
        )

    def _close_position(self, dt: date, price: float) -> TradeRecord:
        """전량 매도, 실현 손익 계산."""
        qty = self._position_qty
        cost = self._cost.calculate("SELL", price, qty)
        pnl = (price - self._avg_buy_price) * qty - cost.total

        self._cash += price * qty - cost.total
        self._position_qty = 0
        self._avg_buy_price = 0.0

        return TradeRecord(
            date=dt,
            side="SELL",
            ticker=self._config.ticker,
            price=price,
            quantity=qty,
            commission=cost.commission,
            tax=cost.tax,
            slippage_cost=cost.slippage_cost,
            total_cost=cost.total,
            pnl=pnl,
        )

    def _take_snapshot(self, dt: date, close_price: float) -> DailySnapshot:
        """일별 스냅샷 생성."""
        position_value = self._position_qty * close_price
        portfolio_value = self._cash + position_value
        daily_return_pct = (
            (portfolio_value - self._prev_portfolio_value)
            / self._prev_portfolio_value
            * 100.0
            if self._prev_portfolio_value > 0
            else 0.0
        )
        self._prev_portfolio_value = portfolio_value

        return DailySnapshot(
            date=dt,
            close_price=close_price,
            cash=self._cash,
            position_qty=self._position_qty,
            position_value=position_value,
            portfolio_value=portfolio_value,
            daily_return_pct=daily_return_pct,
        )
