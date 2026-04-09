"""test/test_backtest_signal_source.py — 시그널 소스 단위 테스트."""

from __future__ import annotations

from datetime import date

import pytest

from src.backtest.signal_source import (
    RLSignalSource,
    ReplaySignalSource,
    _bucket,
    _bucket5,
    _state_key_v1,
    _state_key_v2,
)


# ── V1 state_key 검증 ───────────────────────────────────────────────────────


class TestStateKeyV1:
    def test_short_prices_returns_default(self):
        assert _state_key_v1([100.0], position=0) == "p0|s0|l0"

    def test_flat_prices_neutral(self):
        # 변동 없는 가격 → 모든 bucket 0
        prices = [100.0, 100.0, 100.0, 100.0, 100.0]
        assert _state_key_v1(prices, position=0) == "p0|s0|l0"

    def test_positive_short_return(self):
        # 직전 대비 +1% (> 0.004 threshold) → short_bucket=1
        prices = [100.0, 100.0, 100.0, 100.0, 101.0]
        result = _state_key_v1(prices, position=1)
        assert result.startswith("p1|s1|")

    def test_negative_short_return(self):
        # 직전 대비 -1% (< -0.004 threshold) → short_bucket=-1
        prices = [100.0, 100.0, 100.0, 100.0, 99.0]
        result = _state_key_v1(prices, position=0)
        assert result.startswith("p0|s-1|")

    def test_position_reflected(self):
        prices = [100.0, 100.0]
        assert _state_key_v1(prices, position=0).startswith("p0|")
        assert _state_key_v1(prices, position=1).startswith("p1|")

    def test_matches_original_trainer(self):
        """기존 TabularQTrainer._state_key와 동일한 결과를 반환하는지 검증."""
        from src.agents.rl_trading import TabularQTrainer

        trainer = TabularQTrainer()
        prices_cases = [
            [100.0],
            [100.0, 101.0],
            [100.0, 99.0, 98.0, 97.0, 96.0, 100.0],
            [100.0, 102.0, 104.0, 103.0, 105.0, 107.0, 106.0],
        ]
        for prices in prices_cases:
            for pos in (0, 1):
                expected = trainer._state_key(prices, pos)
                actual = _state_key_v1(prices, pos)
                assert actual == expected, f"V1 mismatch: prices={prices}, pos={pos}"


# ── V2 state_key 검증 ───────────────────────────────────────────────────────


class TestStateKeyV2:
    def test_short_prices_returns_default(self):
        assert _state_key_v2([100.0], position=0) == "p0|s0|l0|m0|v0"

    def test_flat_prices_neutral(self):
        prices = [100.0] * 25
        result = _state_key_v2(prices, position=0)
        assert result == "p0|s0|l0|m0|v0"

    def test_3_positions(self):
        prices = [100.0, 100.0]
        assert _state_key_v2(prices, position=-1).startswith("p-1|")
        assert _state_key_v2(prices, position=0).startswith("p0|")
        assert _state_key_v2(prices, position=1).startswith("p1|")

    def test_matches_original_trainer_v2(self):
        """기존 TabularQTrainerV2._state_key와 동일한 결과를 반환하는지 검증."""
        from src.agents.rl_trading_v2 import TabularQTrainerV2

        trainer = TabularQTrainerV2()
        prices_cases = [
            [100.0],
            [100.0, 101.0],
            [float(100 + i * 0.5) for i in range(25)],  # 점진적 상승
            [float(100 - i * 0.3) for i in range(25)],  # 점진적 하락
        ]
        for prices in prices_cases:
            for pos in (-1, 0, 1):
                expected = trainer._state_key(prices, pos)
                actual = _state_key_v2(prices, pos)
                assert actual == expected, f"V2 mismatch: prices={prices[:5]}..., pos={pos}"


# ── bucket 함수 검증 ─────────────────────────────────────────────────────────


class TestBucket:
    def test_bucket_positive(self):
        assert _bucket(0.005, threshold=0.004) == 1

    def test_bucket_negative(self):
        assert _bucket(-0.005, threshold=0.004) == -1

    def test_bucket_neutral(self):
        assert _bucket(0.002, threshold=0.004) == 0
        assert _bucket(-0.002, threshold=0.004) == 0

    def test_bucket5_strong_up(self):
        assert _bucket5(0.01, small_th=0.002, large_th=0.008) == 2

    def test_bucket5_up(self):
        assert _bucket5(0.005, small_th=0.002, large_th=0.008) == 1

    def test_bucket5_neutral(self):
        assert _bucket5(0.001, small_th=0.002, large_th=0.008) == 0

    def test_bucket5_down(self):
        assert _bucket5(-0.005, small_th=0.002, large_th=0.008) == -1

    def test_bucket5_strong_down(self):
        assert _bucket5(-0.01, small_th=0.002, large_th=0.008) == -2


# ── RLSignalSource 검증 ─────────────────────────────────────────────────────


class TestRLSignalSource:
    def test_v1_known_state_returns_best_action(self):
        # position=0, flat prices → state "p0|s0|l0"
        q_table = {
            "p0|s0|l0": {"BUY": 0.5, "SELL": -0.2, "HOLD": 0.1},
        }
        source = RLSignalSource(q_table=q_table, algorithm="qlearn_v1", lookback=6)
        signal = source.get_signal(date(2025, 7, 1), [100.0, 100.0, 100.0, 100.0, 100.0], position=0)
        assert signal == "BUY"

    def test_v1_unknown_state_returns_hold(self):
        q_table = {"p0|s0|l0": {"BUY": 0.5, "SELL": -0.2, "HOLD": 0.1}}
        source = RLSignalSource(q_table=q_table, algorithm="qlearn_v1", lookback=6)
        # position=1이면 state가 "p1|s0|l0" → Q-table에 없음
        signal = source.get_signal(date(2025, 7, 1), [100.0, 100.0, 100.0, 100.0, 100.0], position=1)
        assert signal == "HOLD"

    def test_v1_tie_breaks_alphabetically(self):
        q_table = {
            "p0|s0|l0": {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0},
        }
        source = RLSignalSource(q_table=q_table, algorithm="qlearn_v1", lookback=6)
        signal = source.get_signal(date(2025, 7, 1), [100.0, 100.0], position=0)
        # 동점 시 알파벳 순: BUY < HOLD < SELL
        assert signal == "BUY"

    def test_v2_known_state_returns_best_action(self):
        # flat prices, position=0, lookback >= 20
        prices = [100.0] * 25
        state = _state_key_v2(prices, position=0)
        q_table = {
            state: {"BUY": 0.1, "SELL": -0.3, "HOLD": 0.05, "CLOSE": -0.1},
        }
        source = RLSignalSource(q_table=q_table, algorithm="qlearn_v2", lookback=20)
        signal = source.get_signal(date(2025, 7, 1), prices, position=0)
        assert signal == "BUY"

    def test_v2_close_action(self):
        prices = [100.0] * 25
        state = _state_key_v2(prices, position=1)
        q_table = {
            state: {"BUY": -0.1, "SELL": -0.2, "HOLD": -0.05, "CLOSE": 0.3},
        }
        source = RLSignalSource(q_table=q_table, algorithm="qlearn_v2", lookback=20)
        signal = source.get_signal(date(2025, 7, 1), prices, position=1)
        assert signal == "CLOSE"

    def test_sell_signal_highest(self):
        q_table = {
            "p1|s-1|l-1": {"BUY": -0.5, "SELL": 0.8, "HOLD": 0.1},
        }
        source = RLSignalSource(q_table=q_table, algorithm="qlearn_v1", lookback=6)
        # prices that produce state "p1|s-1|l-1"
        prices = [100.0, 100.0, 100.0, 100.0, 98.0]
        signal = source.get_signal(date(2025, 7, 1), prices, position=1)
        assert signal == "SELL"


# ── ReplaySignalSource 검증 ─────────────────────────────────────────────────


class TestReplaySignalSource:
    def test_known_date_returns_signal(self):
        signals = {
            date(2025, 7, 1): "BUY",
            date(2025, 7, 2): "SELL",
            date(2025, 7, 3): "HOLD",
        }
        source = ReplaySignalSource(signals)
        assert source.get_signal(date(2025, 7, 1), [], 0) == "BUY"
        assert source.get_signal(date(2025, 7, 2), [], 1) == "SELL"
        assert source.get_signal(date(2025, 7, 3), [], 0) == "HOLD"

    def test_unknown_date_returns_hold(self):
        signals = {date(2025, 7, 1): "BUY"}
        source = ReplaySignalSource(signals)
        assert source.get_signal(date(2025, 7, 2), [], 0) == "HOLD"

    def test_empty_signals(self):
        source = ReplaySignalSource({})
        assert source.get_signal(date(2025, 7, 1), [], 0) == "HOLD"

    def test_prices_and_position_ignored(self):
        """ReplaySignalSource는 prices/position을 무시하고 날짜만 참조."""
        signals = {date(2025, 7, 1): "SELL"}
        source = ReplaySignalSource(signals)
        assert source.get_signal(date(2025, 7, 1), [100.0, 200.0], 1) == "SELL"
        assert source.get_signal(date(2025, 7, 1), [], 0) == "SELL"
