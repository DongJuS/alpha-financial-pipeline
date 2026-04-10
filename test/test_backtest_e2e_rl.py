"""test/test_backtest_e2e_rl.py — 실데이터 RL 백테스트 E2E

fixture(005930 100일) → Q-learning 학습(seed 42) →
BacktestEngine 실행 → 성과 지표 검증

DB 없이 fixture CSV만으로 실행 (CI 호환).
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date
from pathlib import Path

import pytest

from src.agents.rl_trading import RLDataset, TabularQTrainer
from src.backtest.cost_model import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.models import BacktestConfig
from src.backtest.signal_source import RLSignalSource

FIXTURE = Path(__file__).parent / "fixtures" / "005930_ohlcv_100d.csv"
TRAIN_DAYS = 70
SEED = 42


def _load_fixture() -> tuple[list[date], list[float]]:
    """fixture CSV를 읽어 (dates, closes) 반환."""
    dates: list[date] = []
    closes: list[float] = []
    with FIXTURE.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            dates.append(date.fromisoformat(row["traded_at"]))
            closes.append(float(row["close"]))
    return dates, closes


class TestRLBacktestE2E:
    """실데이터 RL 백테스트 E2E 테스트."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        random.seed(SEED)
        self.dates, self.closes = _load_fixture()
        assert len(self.dates) == 100, f"fixture 거래일 수 불일치: {len(self.dates)}"

        # train/test 분할
        self.train_dates = self.dates[:TRAIN_DAYS]
        self.train_closes = self.closes[:TRAIN_DAYS]
        self.test_dates = self.dates[TRAIN_DAYS:]
        self.test_closes = self.closes[TRAIN_DAYS:]

        # Q-learning 학습
        dataset = RLDataset(
            ticker="005930",
            closes=self.train_closes,
            timestamps=[str(d) for d in self.train_dates],
        )
        trainer = TabularQTrainer(random_seed=SEED)
        self.artifact = trainer.train(dataset, train_ratio=0.99)

        # 백테스트 실행
        signal_source = RLSignalSource(
            q_table=self.artifact.q_table,
            algorithm=self.artifact.state_version,
            lookback=self.artifact.lookback,
        )
        config = BacktestConfig(
            ticker="005930",
            strategy="RL",
            train_start=self.train_dates[0],
            train_end=self.train_dates[-1],
            test_start=self.test_dates[0],
            test_end=self.test_dates[-1],
        )
        engine = BacktestEngine(config, signal_source, CostModel())
        self.result = engine.run(self.test_closes, self.test_dates)

    def test_trades_exist(self):
        """학습 후 백테스트가 매매 시그널을 생성해야 한다."""
        assert len(self.result.trades) > 0

    def test_buy_sell_mixed(self):
        """BUY/SELL 시그널이 모두 존재해야 한다."""
        sides = {t.side for t in self.result.trades}
        assert "BUY" in sides, "BUY 시그널 없음"
        assert "SELL" in sides, "SELL 시그널 없음"

    def test_total_return_not_nan(self):
        """total_return이 NaN이 아니어야 한다."""
        assert not math.isnan(self.result.metrics.total_return_pct)

    def test_snapshots_match_test_days(self):
        """daily_snapshots 수가 테스트 기간 거래일 수와 일치해야 한다."""
        expected = len(self.test_dates)
        actual = len(self.result.daily_snapshots)
        assert actual == expected, f"snapshots {actual} != test_days {expected}"

    def test_metrics_consistency(self):
        """성과 지표가 논리적으로 일관돼야 한다."""
        m = self.result.metrics
        assert m.total_trades == len(self.result.trades)
        assert not math.isnan(m.sharpe_ratio)
        assert m.max_drawdown_pct <= 0.0
        assert 0.0 <= m.win_rate <= 100.0

    def test_portfolio_value_positive(self):
        """모든 시점에서 포트폴리오 가치가 양수여야 한다."""
        for snap in self.result.daily_snapshots:
            assert snap.portfolio_value > 0, f"{snap.date}: portfolio_value <= 0"

    def test_trade_costs_applied(self):
        """매매에 수수료/세금/슬리피지가 적용돼야 한다."""
        for trade in self.result.trades:
            assert trade.commission > 0, f"{trade.date} {trade.side}: commission == 0"
            assert trade.slippage_cost > 0, f"{trade.date} {trade.side}: slippage == 0"
            if trade.side == "SELL":
                assert trade.tax > 0, f"{trade.date}: SELL인데 tax == 0"

    def test_seed_reproducibility(self):
        """동일 seed로 동일 결과가 나와야 한다."""
        random.seed(SEED)
        dataset = RLDataset(
            ticker="005930",
            closes=self.train_closes,
            timestamps=[str(d) for d in self.train_dates],
        )
        trainer = TabularQTrainer(random_seed=SEED)
        artifact2 = trainer.train(dataset, train_ratio=0.99)

        signal2 = RLSignalSource(
            q_table=artifact2.q_table,
            algorithm=artifact2.state_version,
            lookback=artifact2.lookback,
        )
        config2 = BacktestConfig(
            ticker="005930",
            strategy="RL",
            train_start=self.train_dates[0],
            train_end=self.train_dates[-1],
            test_start=self.test_dates[0],
            test_end=self.test_dates[-1],
        )
        engine2 = BacktestEngine(config2, signal2, CostModel())
        result2 = engine2.run(self.test_closes, self.test_dates)

        assert len(result2.trades) == len(self.result.trades)
        assert result2.metrics.total_return_pct == self.result.metrics.total_return_pct

    def test_buy_sell_alternation(self):
        """BUY→SELL 순서가 교대로 나타나야 한다 (중복 BUY/SELL 없음)."""
        trades = self.result.trades
        if len(trades) < 2:
            pytest.skip("거래 2건 미만")
        for i in range(1, len(trades)):
            assert trades[i].side != trades[i - 1].side, (
                f"trades[{i-1}]={trades[i-1].side}, trades[{i}]={trades[i].side}: 연속 동일 side"
            )
