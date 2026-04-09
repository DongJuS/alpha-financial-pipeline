"""src/backtest/signal_source.py — 백테스트 시그널 소스.

SignalSource 프로토콜과 구현체:
- RLSignalSource: 학습된 Q-table 기반 시그널 (V1/V2)
- ReplaySignalSource: predictions DB 과거 시그널 재생
"""

from __future__ import annotations

from datetime import date
from typing import Protocol


class SignalSource(Protocol):
    """매매 시그널 생성 인터페이스."""

    def get_signal(self, dt: date, prices: list[float], position: int) -> str:
        """BUY / SELL / HOLD / CLOSE 반환."""
        ...


# ── V1 state_key 로직 (TabularQTrainer._state_key 재구현) ──────────────────


def _bucket(value: float, threshold: float) -> int:
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _state_key_v1(closes: list[float], position: int) -> str:
    if len(closes) < 2:
        return f"p{position}|s0|l0"
    short_return = (closes[-1] / closes[-2]) - 1.0
    window = closes[-5:] if len(closes) >= 5 else closes
    moving_avg = sum(window) / len(window)
    long_return = ((closes[-1] / moving_avg) - 1.0) if moving_avg else 0.0
    short_bucket = _bucket(short_return, threshold=0.004)
    long_bucket = _bucket(long_return, threshold=0.008)
    return f"p{position}|s{short_bucket}|l{long_bucket}"


# ── V2 state_key 로직 (TabularQTrainerV2._state_key 재구현) ────────────────


def _bucket5(value: float, small_th: float, large_th: float) -> int:
    if value > large_th:
        return 2
    if value > small_th:
        return 1
    if value < -large_th:
        return -2
    if value < -small_th:
        return -1
    return 0


def _state_key_v2(closes: list[float], position: int) -> str:
    if len(closes) < 2:
        return f"p{position}|s0|l0|m0|v0"

    short_return = (closes[-1] / closes[-2]) - 1.0

    sma5_window = closes[-5:] if len(closes) >= 5 else closes
    sma5 = sum(sma5_window) / len(sma5_window)
    long_return = ((closes[-1] / sma5) - 1.0) if sma5 else 0.0

    sma20_window = closes[-20:] if len(closes) >= 20 else closes
    sma20 = sum(sma20_window) / len(sma20_window)
    momentum = 0
    if sma5 > sma20 * 1.002:
        momentum = 1
    elif sma5 < sma20 * 0.998:
        momentum = -1

    vol_bucket = 0
    if len(closes) >= 10:
        recent = closes[-10:]
        returns = [(recent[i] / recent[i - 1]) - 1.0 for i in range(1, len(recent))]
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        vol = variance**0.5
        if vol > 0.025:
            vol_bucket = 2
        elif vol > 0.012:
            vol_bucket = 1

    short_bucket = _bucket5(short_return, small_th=0.002, large_th=0.008)
    long_bucket = _bucket5(long_return, small_th=0.004, large_th=0.015)
    return f"p{position}|s{short_bucket}|l{long_bucket}|m{momentum}|v{vol_bucket}"


# ── 시그널 소스 구현체 ──────────────────────────────────────────────────────


class RLSignalSource:
    """학습된 RL Q-table 기반 시그널.

    Parameters:
        q_table: {state_key: {action: q_value}} 형태의 Q-테이블
        algorithm: "qlearn_v1" 또는 "qlearn_v2"
        lookback: state 계산에 사용할 가격 이력 수
    """

    def __init__(self, q_table: dict[str, dict[str, float]], algorithm: str, lookback: int) -> None:
        self.q_table = q_table
        self.algorithm = algorithm
        self.lookback = lookback

    def get_signal(self, dt: date, prices: list[float], position: int) -> str:
        if self.algorithm == "qlearn_v2":
            state = _state_key_v2(prices, position)
        else:
            state = _state_key_v1(prices, position)

        q_values = self.q_table.get(state)
        if q_values is None:
            return "HOLD"

        # argmax: 최고 Q-value, 동점 시 알파벳 순 (기존 Trainer와 동일)
        return sorted(q_values.items(), key=lambda item: (-item[1], item[0]))[0][0]


class ReplaySignalSource:
    """predictions DB에서 과거 시그널 재생.

    Parameters:
        signals: {date: signal_str} 매핑. 해당 날짜에 시그널이 없으면 HOLD.
    """

    def __init__(self, signals: dict[date, str]) -> None:
        self.signals = signals

    def get_signal(self, dt: date, prices: list[float], position: int) -> str:
        return self.signals.get(dt, "HOLD")
