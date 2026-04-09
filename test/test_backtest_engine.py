"""test/test_backtest_engine.py — BacktestEngine 단위 테스트."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.backtest.cost_model import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.models import BacktestConfig


# ── 테스트 헬퍼 ─────────────────────────────────────────────────────────────


class ListSignalSource:
    """테스트용: 미리 정한 시그널 리스트를 순서대로 반환."""

    def __init__(self, signals: list[str]) -> None:
        self._signals = signals
        self._idx = 0

    def get_signal(self, dt: date, prices: list[float], position: int) -> str:
        if self._idx < len(self._signals):
            signal = self._signals[self._idx]
            self._idx += 1
            return signal
        return "HOLD"


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


def _make_dates(n: int, start: date = date(2025, 7, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


# ── 1. 매수 → 가격 상승 → 매도 → 수익 확인 ─────────────────────────────────


class TestBuySellProfit:
    def test_buy_then_sell_at_higher_price(self):
        """1회 매수 후 10% 상승 시 매도 → 양의 수익."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 55_000.0]
        dates = _make_dates(2)
        signals = ListSignalSource(["BUY", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.trades) == 2
        assert result.trades[0].side == "BUY"
        assert result.trades[1].side == "SELL"
        assert result.trades[1].pnl > 0
        assert result.metrics.total_return_pct > 0

    def test_buy_then_sell_at_lower_price(self):
        """1회 매수 후 10% 하락 시 매도 → 음의 수익."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 45_000.0]
        dates = _make_dates(2)
        signals = ListSignalSource(["BUY", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert result.trades[1].pnl < 0
        assert result.metrics.total_return_pct < 0


# ── 2. 비용 차감 확인 ──────────────────────────────────────────────────────


class TestCostDeduction:
    def test_buy_deducts_cost_from_cash(self):
        """매수 후 cash = initial - notional - cost."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 50_000.0]
        dates = _make_dates(2)
        signals = ListSignalSource(["BUY", "HOLD"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        buy_trade = result.trades[0]
        notional = buy_trade.price * buy_trade.quantity
        expected_cash = 10_000_000 - notional - buy_trade.total_cost

        # day 1 snapshot (after BUY)
        assert result.daily_snapshots[0].cash == pytest.approx(expected_cash, abs=0.01)
        assert buy_trade.total_cost > 0
        assert buy_trade.tax == 0.0  # BUY에는 세금 없음

    def test_sell_includes_tax(self):
        """매도 비용에 세금 포함 확인."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 55_000.0]
        dates = _make_dates(2)
        signals = ListSignalSource(["BUY", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        sell_trade = result.trades[1]
        assert sell_trade.tax > 0  # SELL에는 세금 부과
        assert sell_trade.commission > 0
        assert sell_trade.slippage_cost > 0
        assert sell_trade.total_cost == pytest.approx(
            sell_trade.commission + sell_trade.tax + sell_trade.slippage_cost,
            abs=0.01,
        )

    def test_cost_example_samsung(self):
        """삼성전자 60,000원 × 100주 BUY → commission = 900원."""
        config = _make_config(initial_capital=100_000_000)
        prices = [60_000.0]
        dates = _make_dates(1)
        signals = ListSignalSource(["BUY"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        buy_trade = result.trades[0]
        # 60,000 * qty * 0.00015 = commission
        expected_commission = 60_000 * buy_trade.quantity * 0.00015
        assert buy_trade.commission == pytest.approx(expected_commission, abs=0.01)


# ── 3. 포지션 없을 때 SELL 무시 ─────────────────────────────────────────────


class TestSellWithoutPosition:
    def test_sell_ignored_when_no_position(self):
        """포지션이 없으면 SELL 시그널 무시."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 55_000.0]
        dates = _make_dates(2)
        signals = ListSignalSource(["SELL", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.trades) == 0
        assert result.daily_snapshots[-1].cash == 10_000_000

    def test_close_ignored_when_no_position(self):
        """포지션이 없으면 CLOSE 시그널도 무시."""
        config = _make_config()
        prices = [50_000.0]
        dates = _make_dates(1)
        signals = ListSignalSource(["CLOSE"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.trades) == 0


# ── 4. 현금 부족 시 BUY 무시 ────────────────────────────────────────────────


class TestInsufficientCash:
    def test_buy_ignored_when_insufficient_cash(self):
        """현금이 1주도 못 살 만큼 부족하면 BUY 무시."""
        config = _make_config(initial_capital=100)  # 100원으로는 50,000원 주식 못 삼
        prices = [50_000.0]
        dates = _make_dates(1)
        signals = ListSignalSource(["BUY"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.trades) == 0
        assert result.daily_snapshots[0].cash == 100

    def test_second_buy_ignored_while_holding(self):
        """이미 포지션 보유 중이면 추가 BUY 무시."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 50_000.0, 55_000.0]
        dates = _make_dates(3)
        signals = ListSignalSource(["BUY", "BUY", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        buy_trades = [t for t in result.trades if t.side == "BUY"]
        assert len(buy_trades) == 1  # 두 번째 BUY 무시


# ── 5. train/test 기간 겹침 에러 ────────────────────────────────────────────


class TestPeriodOverlap:
    def test_overlap_raises_error(self):
        """train_end >= test_start → ValueError."""
        config = _make_config(
            train_end=date(2025, 7, 15),
            test_start=date(2025, 7, 1),
        )
        signals = ListSignalSource(["HOLD"])
        cost = CostModel()
        engine = BacktestEngine(config, signals, cost)

        with pytest.raises(ValueError, match="train_end.*must be before.*test_start"):
            engine.run([50_000.0], _make_dates(1))

    def test_same_day_raises_error(self):
        """train_end == test_start → ValueError."""
        same_day = date(2025, 7, 1)
        config = _make_config(train_end=same_day, test_start=same_day)
        signals = ListSignalSource(["HOLD"])
        cost = CostModel()
        engine = BacktestEngine(config, signals, cost)

        with pytest.raises(ValueError):
            engine.run([50_000.0], _make_dates(1))


# ── 6. 전부 HOLD → 수익률 0%, 거래 0 ──────────────────────────────────────


class TestAllHold:
    def test_all_hold_zero_return(self):
        """전부 HOLD → 거래 0, 수익률 0%."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0] * 10
        dates = _make_dates(10)
        signals = ListSignalSource(["HOLD"] * 10)
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.trades) == 0
        assert result.metrics.total_return_pct == 0.0
        assert result.metrics.total_trades == 0
        assert result.daily_snapshots[-1].portfolio_value == 10_000_000

    def test_all_hold_varying_prices(self):
        """HOLD만 하면 가격이 변해도 cash만 보유 → 수익률 0%."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 55_000.0, 45_000.0, 60_000.0]
        dates = _make_dates(4)
        signals = ListSignalSource(["HOLD"] * 4)
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.trades) == 0
        # 포지션 없으므로 가격 변동 무관, cash만 보유
        for snap in result.daily_snapshots:
            assert snap.position_qty == 0
            assert snap.portfolio_value == 10_000_000


# ── 추가: 스냅샷 정합성 ────────────────────────────────────────────────────


class TestSnapshotConsistency:
    def test_snapshot_count_equals_data_length(self):
        """스냅샷 수 == 입력 데이터 길이."""
        config = _make_config()
        n = 5
        prices = [50_000.0] * n
        dates = _make_dates(n)
        signals = ListSignalSource(["HOLD"] * n)
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        assert len(result.daily_snapshots) == n

    def test_portfolio_value_equals_cash_plus_position(self):
        """매 스냅샷마다 portfolio_value == cash + position_value."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 52_000.0, 48_000.0, 51_000.0]
        dates = _make_dates(4)
        signals = ListSignalSource(["BUY", "HOLD", "HOLD", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        for snap in result.daily_snapshots:
            expected = snap.cash + snap.position_qty * snap.close_price
            assert snap.portfolio_value == pytest.approx(expected, abs=0.01)

    def test_empty_data(self):
        """빈 데이터 → 빈 결과."""
        config = _make_config()
        signals = ListSignalSource([])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run([], [])

        assert len(result.trades) == 0
        assert len(result.daily_snapshots) == 0
        assert result.metrics.total_return_pct == 0.0


class TestMultipleRoundTrips:
    def test_two_round_trips(self):
        """2회 왕복 매매: BUY→SELL→BUY→SELL."""
        config = _make_config(initial_capital=10_000_000)
        prices = [50_000.0, 55_000.0, 53_000.0, 58_000.0]
        dates = _make_dates(4)
        signals = ListSignalSource(["BUY", "SELL", "BUY", "SELL"])
        cost = CostModel()

        engine = BacktestEngine(config, signals, cost)
        result = engine.run(prices, dates)

        buy_trades = [t for t in result.trades if t.side == "BUY"]
        sell_trades = [t for t in result.trades if t.side == "SELL"]
        assert len(buy_trades) == 2
        assert len(sell_trades) == 2
        # 두 번 모두 가격 상승 시 매도 → 양의 PnL
        assert sell_trades[0].pnl > 0
        assert sell_trades[1].pnl > 0

    def test_prices_dates_length_mismatch(self):
        """prices와 dates 길이 불일치 → ValueError."""
        config = _make_config()
        signals = ListSignalSource(["HOLD"])
        cost = CostModel()
        engine = BacktestEngine(config, signals, cost)

        with pytest.raises(ValueError, match="same length"):
            engine.run([50_000.0, 55_000.0], _make_dates(1))
