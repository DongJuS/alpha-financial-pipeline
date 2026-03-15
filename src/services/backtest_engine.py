"""
src/services/backtest_engine.py — 전략 백테스트 엔진

S3 Data Lake의 히스토리컬 데이터를 사용하여
과거 예측 시그널이 실제 시장에서 어떤 성과를 냈는지 시뮬레이션합니다.

핵심 흐름:
    1. datalake_reader로 daily_bars + predictions 로드
    2. 날짜순으로 시그널을 재생하며 가상 포트폴리오 시뮬레이션
    3. 일별 수익률, MDD, Sharpe, 거래 빈도 등 성과 지표 산출
    4. 전략 간 비교 (A vs B vs RL) 가능

사용 예:
    result = await run_backtest(
        start=date(2026,1,1), end=date(2026,3,1),
        strategy="A", initial_capital=100_000_000,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    """개별 거래 기록."""
    date: str
    ticker: str
    side: str  # BUY or SELL
    price: float
    quantity: int
    signal_confidence: float = 0.0
    strategy: str = ""


@dataclass
class BacktestResult:
    """백테스트 결과 요약."""
    strategy: str
    period_start: str
    period_end: str
    initial_capital: int
    final_equity: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    win_rate: float
    total_trades: int
    avg_holding_days: float
    profit_factor: float | None
    daily_returns: list[dict[str, Any]] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    benchmark_return_pct: float = 0.0  # KOSPI 비교용


@dataclass
class _Position:
    """내부 포지션 추적."""
    ticker: str
    quantity: int
    avg_cost: float
    entry_date: str


class BacktestSimulator:
    """가상 포트폴리오 기반 백테스트 시뮬레이터."""

    def __init__(
        self,
        initial_capital: int = 100_000_000,
        max_position_pct: float = 0.20,
        trade_fee_pct: float = 0.0015,
        slippage_pct: float = 0.001,
    ) -> None:
        self.initial_capital = initial_capital
        self.max_position_pct = max_position_pct
        self.trade_fee_pct = trade_fee_pct
        self.slippage_pct = slippage_pct

        # 상태
        self.cash: float = float(initial_capital)
        self.positions: dict[str, _Position] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[tuple[str, float]] = []
        self._holding_days: list[int] = []
        self._trade_pnls: list[float] = []

    def _current_equity(self, price_map: dict[str, float]) -> float:
        """현재 총 자산 평가."""
        position_value = sum(
            pos.quantity * price_map.get(pos.ticker, pos.avg_cost)
            for pos in self.positions.values()
        )
        return self.cash + position_value

    def _execute_buy(
        self,
        ticker: str,
        price: float,
        dt: str,
        confidence: float,
        strategy: str,
        price_map: dict[str, float],
    ) -> None:
        """매수 실행."""
        equity = self._current_equity(price_map)
        max_amount = equity * self.max_position_pct

        # 기존 포지션 금액 차감
        if ticker in self.positions:
            existing_value = self.positions[ticker].quantity * price
            max_amount -= existing_value

        if max_amount <= 0:
            return

        # 슬리피지 적용
        exec_price = price * (1 + self.slippage_pct)
        fee_adj = exec_price * (1 + self.trade_fee_pct)
        quantity = int(max_amount / fee_adj)

        if quantity <= 0:
            return

        cost = quantity * exec_price * (1 + self.trade_fee_pct)
        if cost > self.cash:
            quantity = int(self.cash / fee_adj)
            cost = quantity * exec_price * (1 + self.trade_fee_pct)

        if quantity <= 0:
            return

        self.cash -= cost

        if ticker in self.positions:
            pos = self.positions[ticker]
            total_qty = pos.quantity + quantity
            pos.avg_cost = (pos.avg_cost * pos.quantity + exec_price * quantity) / total_qty
            pos.quantity = total_qty
        else:
            self.positions[ticker] = _Position(
                ticker=ticker, quantity=quantity,
                avg_cost=exec_price, entry_date=dt,
            )

        self.trades.append(BacktestTrade(
            date=dt, ticker=ticker, side="BUY",
            price=exec_price, quantity=quantity,
            signal_confidence=confidence, strategy=strategy,
        ))

    def _execute_sell(
        self,
        ticker: str,
        price: float,
        dt: str,
        confidence: float,
        strategy: str,
    ) -> None:
        """매도 실행."""
        if ticker not in self.positions:
            return

        pos = self.positions[ticker]
        exec_price = price * (1 - self.slippage_pct)
        proceeds = pos.quantity * exec_price * (1 - self.trade_fee_pct)

        # P&L 계산
        cost_basis = pos.quantity * pos.avg_cost
        pnl = proceeds - cost_basis
        self._trade_pnls.append(pnl)

        # 보유 기간 계산
        try:
            entry = date.fromisoformat(pos.entry_date)
            exit_d = date.fromisoformat(dt)
            self._holding_days.append((exit_d - entry).days)
        except (ValueError, TypeError):
            pass

        self.cash += proceeds
        self.trades.append(BacktestTrade(
            date=dt, ticker=ticker, side="SELL",
            price=exec_price, quantity=pos.quantity,
            signal_confidence=confidence, strategy=strategy,
        ))
        del self.positions[ticker]

    def process_signals(
        self,
        signals_by_date: dict[str, list[dict[str, Any]]],
        bars_by_ticker_date: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        """날짜순으로 시그널을 처리합니다."""
        sorted_dates = sorted(signals_by_date.keys())

        for dt in sorted_dates:
            signals = signals_by_date[dt]

            # 현재 가격 맵 구축
            price_map: dict[str, float] = {}
            for ticker, dates_map in bars_by_ticker_date.items():
                bar = dates_map.get(dt)
                if bar:
                    price_map[ticker] = float(bar.get("close", 0))

            # 매도 시그널 먼저 처리 (자금 확보)
            for sig in sorted(signals, key=lambda s: 0 if s.get("signal") == "SELL" else 1):
                ticker = sig.get("ticker", "")
                signal = str(sig.get("signal", "HOLD")).upper()
                confidence = float(sig.get("confidence", 0.5))
                strategy = str(sig.get("strategy", ""))
                price = price_map.get(ticker)

                if not price or price <= 0:
                    continue

                if signal == "BUY":
                    self._execute_buy(ticker, price, dt, confidence, strategy, price_map)
                elif signal == "SELL":
                    self._execute_sell(ticker, price, dt, confidence, strategy)
                # HOLD: 무행동

            # 일별 에쿼티 기록
            equity = self._current_equity(price_map)
            self.equity_curve.append((dt, equity))

    def get_result(self, strategy: str) -> BacktestResult:
        """백테스트 결과를 산출합니다."""
        if not self.equity_curve:
            return BacktestResult(
                strategy=strategy,
                period_start="", period_end="",
                initial_capital=self.initial_capital,
                final_equity=float(self.initial_capital),
                total_return_pct=0.0, annualized_return_pct=0.0,
                max_drawdown_pct=0.0, sharpe_ratio=None,
                win_rate=0.0, total_trades=0,
                avg_holding_days=0.0, profit_factor=None,
            )

        final = self.equity_curve[-1][1]
        total_return = ((final - self.initial_capital) / self.initial_capital) * 100

        # 연환산 수익률
        period_start = self.equity_curve[0][0]
        period_end = self.equity_curve[-1][0]
        try:
            days = (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days
            if days > 0:
                annualized = ((final / self.initial_capital) ** (365 / days) - 1) * 100
            else:
                annualized = 0.0
        except (ValueError, TypeError):
            days = len(self.equity_curve)
            annualized = 0.0

        # MDD 계산
        peak = self.equity_curve[0][1]
        max_dd = 0.0
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = ((equity - peak) / peak) * 100
            if dd < max_dd:
                max_dd = dd

        # 일별 수익률
        daily_returns: list[dict[str, Any]] = []
        for i in range(1, len(self.equity_curve)):
            prev = self.equity_curve[i - 1][1]
            curr = self.equity_curve[i][1]
            ret = ((curr - prev) / prev) * 100 if prev > 0 else 0.0
            daily_returns.append({
                "date": self.equity_curve[i][0],
                "equity": round(curr),
                "return_pct": round(ret, 4),
            })

        # Sharpe ratio
        rets = [d["return_pct"] for d in daily_returns]
        sharpe = None
        if len(rets) >= 5:
            mean_r = sum(rets) / len(rets)
            var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
            std = math.sqrt(var) if var > 0 else 0.0
            if std > 0:
                sharpe = round((mean_r / std) * math.sqrt(252), 3)

        # 승률 / profit factor
        wins = [p for p in self._trade_pnls if p > 0]
        losses = [p for p in self._trade_pnls if p < 0]
        win_rate = len(wins) / len(self._trade_pnls) if self._trade_pnls else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

        avg_hold = sum(self._holding_days) / len(self._holding_days) if self._holding_days else 0.0

        return BacktestResult(
            strategy=strategy,
            period_start=period_start,
            period_end=period_end,
            initial_capital=self.initial_capital,
            final_equity=round(final),
            total_return_pct=round(total_return, 2),
            annualized_return_pct=round(annualized, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=sharpe,
            win_rate=round(win_rate, 4),
            total_trades=len(self.trades),
            avg_holding_days=round(avg_hold, 1),
            profit_factor=profit_factor,
            daily_returns=daily_returns,
            trades=self.trades,
        )


async def run_backtest(
    start: date,
    end: date,
    strategy: str | None = None,
    initial_capital: int = 100_000_000,
    max_position_pct: float = 0.20,
) -> BacktestResult:
    """S3 Data Lake 데이터로 백테스트를 실행합니다.

    Args:
        start: 백테스트 시작일
        end: 백테스트 종료일
        strategy: 전략 필터 (None이면 전체)
        initial_capital: 초기 자본금 (원)
        max_position_pct: 종목당 최대 비중

    Returns:
        BacktestResult
    """
    from src.services.datalake_reader import load_records
    from src.services.datalake import DataType

    # 1. 예측 시그널 로드
    predictions = await load_records(DataType.PREDICTIONS, start, end)
    if strategy:
        predictions = [p for p in predictions if p.get("strategy") == strategy]

    if not predictions:
        logger.warning("백테스트 데이터 없음: predictions %s [%s~%s]", strategy, start, end)
        return BacktestSimulator(initial_capital).get_result(strategy or "all")

    # 2. 일봉 데이터 로드 (예측에 나오는 종목들)
    tickers = list({p.get("ticker", "") for p in predictions if p.get("ticker")})
    bars_all: list[dict[str, Any]] = []
    for ticker in tickers:
        bars = await load_records(DataType.DAILY_BARS, start, end, ticker=ticker)
        bars_all.extend(bars)

    # 3. 인덱스 구축
    # signals_by_date: date_str → list[signal]
    signals_by_date: dict[str, list[dict[str, Any]]] = {}
    for pred in predictions:
        ts = pred.get("timestamp")
        if ts is None:
            continue
        if hasattr(ts, "date"):
            pred_date = ts.date().isoformat()
        elif isinstance(ts, str):
            pred_date = ts[:10]
        else:
            pred_date = str(ts)
        signals_by_date.setdefault(pred_date, []).append(pred)

    # bars_by_ticker_date: ticker → date_str → bar
    bars_by_ticker_date: dict[str, dict[str, dict[str, Any]]] = {}
    for bar in bars_all:
        ticker = bar.get("ticker", "")
        bar_date = str(bar.get("date", ""))
        bars_by_ticker_date.setdefault(ticker, {})[bar_date] = bar

    # 4. 시뮬레이션
    sim = BacktestSimulator(
        initial_capital=initial_capital,
        max_position_pct=max_position_pct,
    )
    sim.process_signals(signals_by_date, bars_by_ticker_date)

    return sim.get_result(strategy or "all")


async def compare_strategies(
    start: date,
    end: date,
    strategies: list[str] | None = None,
    initial_capital: int = 100_000_000,
) -> dict[str, Any]:
    """여러 전략의 백테스트 결과를 비교합니다.

    Args:
        strategies: 비교할 전략 리스트 (None이면 ["A", "B", "RL"])

    Returns:
        {"strategies": {name: BacktestResult}, "ranking": [...]}
    """
    if strategies is None:
        strategies = ["A", "B", "RL"]

    results: dict[str, dict[str, Any]] = {}
    for s in strategies:
        bt = await run_backtest(start, end, strategy=s, initial_capital=initial_capital)
        results[s] = {
            "total_return_pct": bt.total_return_pct,
            "annualized_return_pct": bt.annualized_return_pct,
            "max_drawdown_pct": bt.max_drawdown_pct,
            "sharpe_ratio": bt.sharpe_ratio,
            "win_rate": bt.win_rate,
            "total_trades": bt.total_trades,
            "profit_factor": bt.profit_factor,
        }

    # 수익률 기준 랭킹
    ranking = sorted(results.keys(), key=lambda s: results[s]["total_return_pct"], reverse=True)

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "initial_capital": initial_capital,
        "strategies": results,
        "ranking": ranking,
    }
