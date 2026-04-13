"""test/test_backtest_metrics.py — 성과 지표 단위 테스트."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.backtest.metrics import (
    TRADING_DAYS_PER_YEAR,
    _compute_avg_holding_days,
    _compute_mdd,
    _compute_sharpe,
    compute_backtest_metrics,
)
from src.backtest.models import BacktestConfig, DailySnapshot, TradeRecord


# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def _make_config(**overrides) -> BacktestConfig:
    defaults = dict(
        ticker="005930",
        strategy="RL",
        train_start=date(2024, 1, 1),
        train_end=date(2025, 6, 30),
        test_start=date(2025, 7, 1),
        test_end=date(2025, 12, 31),
        initial_capital=10_000_000,
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def _make_snapshot(
    day: date,
    close_price: float,
    portfolio_value: float,
    daily_return_pct: float,
    cash: float = 0.0,
    position_qty: int = 100,
) -> DailySnapshot:
    position_value = position_qty * close_price
    return DailySnapshot(
        date=day,
        close_price=close_price,
        cash=cash,
        position_qty=position_qty,
        position_value=position_value,
        portfolio_value=portfolio_value,
        daily_return_pct=daily_return_pct,
    )


def _make_trade(
    day: date,
    side: str,
    price: float,
    quantity: int = 100,
    pnl: float = 0.0,
) -> TradeRecord:
    return TradeRecord(
        date=day,
        side=side,
        ticker="005930",
        price=price,
        quantity=quantity,
        commission=price * quantity * 0.00015,
        tax=price * quantity * 0.0018 if side == "SELL" else 0.0,
        slippage_cost=price * quantity * 0.0003,
        total_cost=0.0,
        pnl=pnl,
    )


# ── 전체 compute_backtest_metrics 검증 ──────────────────────────────────────


class TestComputeBacktestMetrics:
    def test_steady_1pct_daily_increase(self):
        """10 거래일 매일 +1% → 총 수익률 ~10.46%, MDD 0%."""
        config = _make_config(initial_capital=10_000_000)
        base_price = 10000.0
        snapshots = []
        portfolio = 10_000_000.0

        for i in range(11):  # day 0 ~ day 10
            price = base_price * (1.01**i)
            ret_pct = 1.0 if i > 0 else 0.0
            if i > 0:
                portfolio *= 1.01
            snapshots.append(
                _make_snapshot(
                    day=date(2025, 7, 1) + timedelta(days=i),
                    close_price=price,
                    portfolio_value=portfolio,
                    daily_return_pct=ret_pct,
                )
            )

        trades = [
            _make_trade(date(2025, 7, 1), "BUY", base_price, 1000),
        ]

        m = compute_backtest_metrics(snapshots, trades, config)

        # (1.01^10 - 1) * 100 = 10.4622%
        assert abs(m.total_return_pct - 10.4622) < 0.01
        assert m.max_drawdown_pct == 0.0  # 지속 상승 → MDD 없음
        assert m.baseline_return_pct == pytest.approx(10.4622, abs=0.01)
        assert m.total_trades == 1
        assert m.win_rate == 0.0  # SELL 없음

    def test_5_up_5_down_mdd(self):
        """5일 +2% 후 5일 -2% → MDD 검증."""
        config = _make_config(initial_capital=10_000_000)
        snapshots = []
        portfolio = 10_000_000.0
        price = 10000.0

        # day 0: base
        snapshots.append(
            _make_snapshot(
                day=date(2025, 7, 1),
                close_price=price,
                portfolio_value=portfolio,
                daily_return_pct=0.0,
            )
        )
        # day 1-5: +2%
        for i in range(1, 6):
            price *= 1.02
            portfolio *= 1.02
            snapshots.append(
                _make_snapshot(
                    day=date(2025, 7, 1) + timedelta(days=i),
                    close_price=price,
                    portfolio_value=portfolio,
                    daily_return_pct=2.0,
                )
            )
        # day 6-10: -2%
        for i in range(6, 11):
            price *= 0.98
            portfolio *= 0.98
            snapshots.append(
                _make_snapshot(
                    day=date(2025, 7, 1) + timedelta(days=i),
                    close_price=price,
                    portfolio_value=portfolio,
                    daily_return_pct=-2.0,
                )
            )

        m = compute_backtest_metrics(snapshots, [], config)

        # peak at day 5: 1.02^5 = 1.10408
        # trough at day 10: 1.10408 * 0.98^5 = 1.10408 * 0.90392 ≈ 0.998
        # MDD = (0.998 - 1.10408) / 1.10408 * 100 ≈ -9.606%
        assert m.max_drawdown_pct < 0
        assert abs(m.max_drawdown_pct - (-9.6059)) < 0.01

    def test_no_trades_edge_case(self):
        """거래 없을 때 → win_rate 0, total_trades 0."""
        config = _make_config(initial_capital=10_000_000)
        snapshots = [
            _make_snapshot(
                day=date(2025, 7, 1) + timedelta(days=i),
                close_price=10000.0,
                portfolio_value=10_000_000.0,
                daily_return_pct=0.0,
            )
            for i in range(5)
        ]

        m = compute_backtest_metrics(snapshots, [], config)

        assert m.total_trades == 0
        assert m.win_rate == 0.0
        assert m.total_return_pct == 0.0
        assert m.sharpe_ratio == 0.0  # std = 0
        assert m.avg_holding_days == 0.0

    def test_empty_snapshots(self):
        """스냅샷 없을 때 → 모든 지표 0."""
        config = _make_config()
        m = compute_backtest_metrics([], [], config)

        assert m.total_return_pct == 0.0
        assert m.annual_return_pct == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.max_drawdown_pct == 0.0
        assert m.total_trades == 0

    def test_win_rate_with_sells(self):
        """매도 3건 중 2건 수익 → win_rate ≈ 0.6667."""
        config = _make_config(initial_capital=10_000_000)
        snapshots = [
            _make_snapshot(
                day=date(2025, 7, 1),
                close_price=10000.0,
                portfolio_value=10_000_000.0,
                daily_return_pct=0.0,
            ),
        ]
        trades = [
            _make_trade(date(2025, 7, 1), "SELL", 10500, pnl=50000),
            _make_trade(date(2025, 7, 2), "SELL", 10200, pnl=20000),
            _make_trade(date(2025, 7, 3), "SELL", 9500, pnl=-50000),
        ]

        m = compute_backtest_metrics(snapshots, trades, config)

        assert abs(m.win_rate - 66.6667) < 0.01
        assert m.total_trades == 3

    def test_excess_return(self):
        """포트폴리오 수익률 > baseline → excess_return > 0."""
        config = _make_config(initial_capital=10_000_000)
        # 포트폴리오: +20%, baseline price: 10000 → 11000 (+10%)
        snapshots = [
            _make_snapshot(
                day=date(2025, 7, 1),
                close_price=10000.0,
                portfolio_value=10_000_000.0,
                daily_return_pct=0.0,
            ),
            _make_snapshot(
                day=date(2025, 7, 2),
                close_price=11000.0,
                portfolio_value=12_000_000.0,
                daily_return_pct=20.0,
            ),
        ]

        m = compute_backtest_metrics(snapshots, [], config)

        assert m.total_return_pct == 20.0
        assert abs(m.baseline_return_pct - 10.0) < 0.001
        assert abs(m.excess_return_pct - 10.0) < 0.001

    def test_annual_return_calculation(self):
        """연환산 수익률: 126 거래일(반년) 10% → 연환산 ~21%."""
        config = _make_config(initial_capital=10_000_000)
        n_days = 126
        total_return = 0.10
        snapshots = []
        daily_ret = (1 + total_return) ** (1.0 / n_days) - 1.0
        current = 10_000_000.0
        price = 10000.0
        for i in range(n_days + 1):
            if i == 0:
                snapshots.append(
                    _make_snapshot(
                        day=date(2025, 7, 1) + timedelta(days=i),
                        close_price=price,
                        portfolio_value=current,
                        daily_return_pct=0.0,
                    )
                )
            else:
                current *= 1 + daily_ret
                price *= 1 + daily_ret
                snapshots.append(
                    _make_snapshot(
                        day=date(2025, 7, 1) + timedelta(days=i),
                        close_price=price,
                        portfolio_value=current,
                        daily_return_pct=daily_ret * 100,
                    )
                )

        m = compute_backtest_metrics(snapshots, [], config)

        # (1.10)^(252/127) - 1 ≈ 0.2100 = 21.00%
        expected_annual = ((1 + total_return) ** (TRADING_DAYS_PER_YEAR / (n_days + 1)) - 1) * 100
        assert abs(m.annual_return_pct - expected_annual) < 0.1


# ── 개별 함수 검증 ──────────────────────────────────────────────────────────


class TestComputeSharpe:
    def test_positive_returns(self):
        # 다양한 양수 수익률
        returns = [0.01, 0.02, 0.005, 0.015, 0.01]
        sharpe = _compute_sharpe(returns)
        assert sharpe > 0

    def test_zero_std_returns_zero(self):
        # 모든 수익률 동일 → std=0 → sharpe=0
        returns = [0.01, 0.01, 0.01, 0.01]
        assert _compute_sharpe(returns) == 0.0

    def test_single_return(self):
        assert _compute_sharpe([0.01]) == 0.0

    def test_empty_returns(self):
        assert _compute_sharpe([]) == 0.0

    def test_negative_mean(self):
        returns = [-0.01, -0.02, -0.005, -0.015]
        sharpe = _compute_sharpe(returns)
        assert sharpe < 0


class TestComputeMDD:
    def test_monotone_increase_zero_mdd(self):
        snapshots = [
            _make_snapshot(date(2025, 7, 1) + timedelta(days=i), 100 + i, 10_000_000 + i * 100_000, 1.0)
            for i in range(5)
        ]
        assert _compute_mdd(snapshots) == 0.0

    def test_single_drop(self):
        snapshots = [
            _make_snapshot(date(2025, 7, 1), 100, 10_000_000, 0.0),
            _make_snapshot(date(2025, 7, 2), 110, 11_000_000, 10.0),
            _make_snapshot(date(2025, 7, 3), 99, 9_900_000, -10.0),  # peak 11M → 9.9M
        ]
        mdd = _compute_mdd(snapshots)
        # (9.9M - 11M) / 11M * 100 = -10.0%
        assert abs(mdd - (-10.0)) < 0.001


class TestAvgHoldingDays:
    def test_single_round_trip(self):
        trades = [
            _make_trade(date(2025, 7, 1), "BUY", 10000),
            _make_trade(date(2025, 7, 6), "SELL", 10500, pnl=50000),
        ]
        assert _compute_avg_holding_days(trades) == 5.0

    def test_multiple_round_trips(self):
        trades = [
            _make_trade(date(2025, 7, 1), "BUY", 10000),
            _make_trade(date(2025, 7, 4), "SELL", 10500, pnl=50000),  # 3일
            _make_trade(date(2025, 7, 5), "BUY", 10200),
            _make_trade(date(2025, 7, 12), "SELL", 10700, pnl=50000),  # 7일
        ]
        assert _compute_avg_holding_days(trades) == 5.0  # (3+7)/2

    def test_no_trades(self):
        assert _compute_avg_holding_days([]) == 0.0

    def test_only_buys(self):
        trades = [_make_trade(date(2025, 7, 1), "BUY", 10000)]
        assert _compute_avg_holding_days(trades) == 0.0
