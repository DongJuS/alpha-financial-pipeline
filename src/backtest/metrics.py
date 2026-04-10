"""src/backtest/metrics.py — 백테스트 성과 지표 계산.

일별 스냅샷 + 매매 기록으로 포트폴리오 기반 성과 지표를 산출한다.
"""

from __future__ import annotations

from src.backtest.models import BacktestConfig, BacktestMetrics, DailySnapshot, TradeRecord

TRADING_DAYS_PER_YEAR = 252


def compute_backtest_metrics(
    snapshots: list[DailySnapshot],
    trades: list[TradeRecord],
    config: BacktestConfig,
) -> BacktestMetrics:
    """일별 스냅샷 + 매매 기록으로 성과 지표 산출."""
    if not snapshots:
        return BacktestMetrics(
            total_return_pct=0.0,
            annual_return_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            total_trades=0,
            avg_holding_days=0.0,
            baseline_return_pct=0.0,
            excess_return_pct=0.0,
        )

    initial = float(config.initial_capital)
    final = snapshots[-1].portfolio_value

    # ── 수익률 ──────────────────────────────────────────────────────────
    total_return = (final - initial) / initial
    total_return_pct = total_return * 100.0

    # ── 연환산 수익률 ───────────────────────────────────────────────────
    n_days = len(snapshots)
    if n_days > 1 and total_return > -1.0:
        annual_return_pct = ((1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0) * 100.0
    else:
        annual_return_pct = 0.0

    # ── 샤프 비율 ───────────────────────────────────────────────────────
    daily_returns = [s.daily_return_pct / 100.0 for s in snapshots]
    sharpe_ratio = _compute_sharpe(daily_returns)

    # ── MDD ──────────────────────────────────────────────────────────────
    max_drawdown_pct = _compute_mdd(snapshots)

    # ── 승률 ─────────────────────────────────────────────────────────────
    sell_trades = [t for t in trades if t.side == "SELL"]
    if sell_trades:
        win_count = sum(1 for t in sell_trades if t.pnl > 0)
        win_rate = (win_count / len(sell_trades)) * 100.0
    else:
        win_rate = 0.0

    # ── 평균 보유 기간 ───────────────────────────────────────────────────
    avg_holding_days = _compute_avg_holding_days(trades)

    # ── baseline (buy & hold) ────────────────────────────────────────────
    first_price = snapshots[0].close_price
    last_price = snapshots[-1].close_price
    baseline_return_pct = ((last_price / first_price) - 1.0) * 100.0 if first_price > 0 else 0.0

    excess_return_pct = total_return_pct - baseline_return_pct

    return BacktestMetrics(
        total_return_pct=round(total_return_pct, 4),
        annual_return_pct=round(annual_return_pct, 4),
        sharpe_ratio=round(sharpe_ratio, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        win_rate=round(win_rate, 4),
        total_trades=len(trades),
        avg_holding_days=round(avg_holding_days, 1),
        baseline_return_pct=round(baseline_return_pct, 4),
        excess_return_pct=round(excess_return_pct, 4),
    )


def _compute_sharpe(daily_returns: list[float]) -> float:
    """샤프 비율: mean / std × sqrt(252). 무위험이자율 0 가정."""
    if len(daily_returns) < 2:
        return 0.0
    mean_r = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std_r = variance**0.5
    if std_r <= 0:
        return 0.0
    return (mean_r / std_r) * (TRADING_DAYS_PER_YEAR**0.5)


def _compute_mdd(snapshots: list[DailySnapshot]) -> float:
    """최대 낙폭(MDD): peak-to-trough 기준 %."""
    peak = snapshots[0].portfolio_value
    mdd = 0.0
    for s in snapshots:
        if s.portfolio_value > peak:
            peak = s.portfolio_value
        dd = ((s.portfolio_value - peak) / peak) * 100.0
        if dd < mdd:
            mdd = dd
    return mdd


def _compute_avg_holding_days(trades: list[TradeRecord]) -> float:
    """BUY-SELL 쌍에서 평균 보유 기간 산출."""
    buy_dates: list = []
    total_holding = 0
    matched = 0
    for t in trades:
        if t.side == "BUY":
            buy_dates.append(t.date)
        elif t.side == "SELL" and buy_dates:
            buy_dt = buy_dates.pop(0)
            holding = (t.date - buy_dt).days
            total_holding += max(holding, 0)
            matched += 1
    return total_holding / matched if matched else 0.0
