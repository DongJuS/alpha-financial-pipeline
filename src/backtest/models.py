"""src/backtest/models.py — 백테스트 공통 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class BacktestConfig:
    """백테스트 실행 설정."""

    ticker: str
    strategy: str  # "RL", "A", "B", "BLEND"
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    initial_capital: int = 10_000_000
    commission_rate_pct: float = 0.015
    tax_rate_pct: float = 0.18
    slippage_bps: int = 3


@dataclass
class TradeRecord:
    """개별 매매 기록."""

    date: date
    side: str  # "BUY" | "SELL"
    ticker: str
    price: float
    quantity: int
    commission: float
    tax: float
    slippage_cost: float
    total_cost: float  # commission + tax + slippage
    pnl: float = 0.0  # 실현 손익 (SELL 시)


@dataclass
class DailySnapshot:
    """일별 포트폴리오 스냅샷."""

    date: date
    close_price: float
    cash: float
    position_qty: int
    position_value: float
    portfolio_value: float  # cash + position_value
    daily_return_pct: float


@dataclass(frozen=True)
class BacktestMetrics:
    """백테스트 성과 지표."""

    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    avg_holding_days: float
    baseline_return_pct: float  # buy & hold
    excess_return_pct: float  # total - baseline


@dataclass
class BacktestResult:
    """백테스트 실행 결과."""

    config: BacktestConfig
    metrics: BacktestMetrics
    trades: list[TradeRecord] = field(default_factory=list)
    daily_snapshots: list[DailySnapshot] = field(default_factory=list)
