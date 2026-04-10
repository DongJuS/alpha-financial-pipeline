"""test/test_backtest_replay.py — Strategy A/B Signal Replay 통합 테스트.

ReplaySignalSource 단위 + BacktestEngine 통합 + _build_replay_signal_source 통합.
DB 없이 fixture CSV + JSON 으로 실행 (CI 호환).
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.backtest.cost_model import CostModel
from src.backtest.engine import BacktestEngine
from src.backtest.models import BacktestConfig
from src.backtest.signal_source import ReplaySignalSource

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "005930_ohlcv_100d.csv"
FIXTURE_SIGNALS = Path(__file__).parent / "fixtures" / "replay_signals.json"
TRAIN_DAYS = 70


def _load_fixture() -> tuple[list[date], list[float]]:
    """fixture CSV → (dates, closes)."""
    dates: list[date] = []
    closes: list[float] = []
    with FIXTURE_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            dates.append(date.fromisoformat(row["traded_at"]))
            closes.append(float(row["close"]))
    return dates, closes


def _load_signals() -> dict[date, str]:
    """fixture JSON → {date: signal}."""
    with FIXTURE_SIGNALS.open() as f:
        data = json.load(f)
    return {date.fromisoformat(k): v for k, v in data["signals"].items()}


# ── 테스트 1: ReplaySignalSource 단위 테스트 ───────────────────────────────


class TestReplaySignalSourceUnit:
    """ReplaySignalSource 의 get_signal 동작 검증."""

    def test_returns_signal_for_known_date(self):
        """시그널이 있는 날짜 → 해당 시그널 반환."""
        signals = {date(2025, 4, 21): "BUY", date(2025, 4, 30): "SELL"}
        source = ReplaySignalSource(signals=signals)
        assert source.get_signal(date(2025, 4, 21), [50000.0], 0) == "BUY"
        assert source.get_signal(date(2025, 4, 30), [51000.0], 1) == "SELL"

    def test_returns_hold_for_unknown_date(self):
        """시그널이 없는 날짜 → HOLD 반환."""
        signals = {date(2025, 4, 21): "BUY"}
        source = ReplaySignalSource(signals=signals)
        assert source.get_signal(date(2025, 5, 1), [50000.0], 0) == "HOLD"

    def test_empty_signals_always_hold(self):
        """빈 signals dict → 모든 날짜 HOLD."""
        source = ReplaySignalSource(signals={})
        for d in [date(2025, 1, 2), date(2025, 6, 1), date(2025, 12, 31)]:
            assert source.get_signal(d, [50000.0], 0) == "HOLD"


# ── 테스트 2: ReplaySignalSource + BacktestEngine 통합 테스트 ─────────────


class TestReplayBacktestIntegration:
    """fixture CSV + 하드코딩 시그널 → BacktestEngine 실행 검증."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        all_dates, all_closes = _load_fixture()
        signals = _load_signals()

        self.test_dates = all_dates[TRAIN_DAYS:]
        self.test_closes = all_closes[TRAIN_DAYS:]

        signal_source = ReplaySignalSource(signals=signals)
        config = BacktestConfig(
            ticker="005930",
            strategy="A",
            train_start=all_dates[0],
            train_end=all_dates[TRAIN_DAYS - 1],
            test_start=self.test_dates[0],
            test_end=self.test_dates[-1],
        )
        engine = BacktestEngine(config, signal_source, CostModel())
        self.result = engine.run(self.test_closes, self.test_dates)

    def test_result_has_trades(self):
        """BUY/SELL 시그널 → 매매가 실행돼야 한다."""
        assert len(self.result.trades) > 0

    def test_buy_sell_pairs(self):
        """BUY와 SELL이 모두 존재해야 한다."""
        sides = {t.side for t in self.result.trades}
        assert "BUY" in sides
        assert "SELL" in sides

    def test_trade_count_matches_signals(self):
        """fixture 시그널 4개(BUY, SELL, BUY, SELL) → 4건 매매."""
        assert len(self.result.trades) == 4

    def test_snapshots_match_test_days(self):
        """daily_snapshots 수가 테스트 기간 거래일 수와 일치."""
        assert len(self.result.daily_snapshots) == len(self.test_dates)

    def test_metrics_not_nan(self):
        """주요 지표가 NaN이 아니어야 한다."""
        m = self.result.metrics
        assert not math.isnan(m.total_return_pct)
        assert not math.isnan(m.sharpe_ratio)
        assert not math.isnan(m.win_rate)

    def test_portfolio_value_positive(self):
        """모든 시점에서 포트폴리오 가치가 양수."""
        for snap in self.result.daily_snapshots:
            assert snap.portfolio_value > 0, f"{snap.date}: portfolio_value <= 0"

    def test_metrics_consistency(self):
        """total_trades == len(trades), drawdown <= 0, win_rate [0, 100]."""
        m = self.result.metrics
        assert m.total_trades == len(self.result.trades)
        assert m.max_drawdown_pct <= 0.0
        assert 0.0 <= m.win_rate <= 100.0


# ── 테스트 3: _build_replay_signal_source 통합 (DB mock) ──────────────────


class TestBuildReplaySignalSource:
    """_build_replay_signal_source() 가 fetch_predictions_for_replay를 호출하여
    ReplaySignalSource를 올바르게 생성하는지 검증."""

    @pytest.mark.asyncio
    async def test_builds_from_predictions(self):
        """fetch_predictions_for_replay 결과 → ReplaySignalSource 생성."""
        mock_predictions = [
            {"trading_date": date(2025, 4, 21), "signal": "BUY"},
            {"trading_date": date(2025, 4, 30), "signal": "SELL"},
        ]

        with patch(
            "src.backtest.repository.fetch_predictions_for_replay",
            new_callable=AsyncMock,
            return_value=mock_predictions,
        ):
            from src.backtest.cli import _build_replay_signal_source

            source = await _build_replay_signal_source(
                ticker="005930",
                strategy="A",
                test_start=date(2025, 4, 17),
                test_end=date(2025, 6, 2),
            )

        assert isinstance(source, ReplaySignalSource)
        assert source.get_signal(date(2025, 4, 21), [], 0) == "BUY"
        assert source.get_signal(date(2025, 4, 30), [], 0) == "SELL"
        assert source.get_signal(date(2025, 5, 1), [], 0) == "HOLD"

    @pytest.mark.asyncio
    async def test_empty_predictions_all_hold(self):
        """predictions가 비어있으면 → 모든 날짜 HOLD."""
        with patch(
            "src.backtest.repository.fetch_predictions_for_replay",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.backtest.cli import _build_replay_signal_source

            source = await _build_replay_signal_source(
                ticker="005930",
                strategy="B",
                test_start=date(2025, 4, 17),
                test_end=date(2025, 6, 2),
            )

        assert isinstance(source, ReplaySignalSource)
        assert source.get_signal(date(2025, 4, 21), [], 0) == "HOLD"
        assert source.get_signal(date(2025, 5, 15), [], 0) == "HOLD"
