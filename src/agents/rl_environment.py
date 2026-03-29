"""
src/agents/rl_environment.py — Gymnasium 호환 트레이딩 환경

Gymnasium 인터페이스를 준수하는 주식 트레이딩 환경.
기존 TabularQTrainer의 내부 시뮬레이션을 독립 환경으로 분리하여
향후 DQN/PPO (stable-baselines3) 연동을 준비합니다.

Usage:
    env = TradingEnv(config=TradingEnvConfig(closes=closes, volumes=volumes))
    obs, info = env.reset()
    while not done:
        action = agent.predict(obs)
        obs, reward, terminated, truncated, info = env.step(action)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Gymnasium은 optional import (설치 안 되어있으면 자체 프로토콜 사용)
try:
    import gymnasium as gym
    from gymnasium import spaces

    HAS_GYMNASIUM = True
except ImportError:
    HAS_GYMNASIUM = False


# ── 환경 설정 ─────────────────────────────────────────────────────────────


@dataclass
class TradingEnvConfig:
    """트레이딩 환경 설정."""

    closes: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)

    # Feature 관련
    lookback: int = 20  # observation에 포함할 과거 바 수
    feature_columns: list[str] = field(
        default_factory=lambda: [
            "return",
            "sma_cross",
            "rsi_norm",
            "volatility",
            "volume_ratio",
        ]
    )

    # 거래 비용
    trade_penalty_bps: int = 2  # 편도 거래 비용 (bps)
    slippage_bps: int = 1  # 슬리피지 (bps)

    # 리스크 관리
    max_drawdown_pct: float = -50.0  # 최대 낙폭 한도 (%)
    max_position: int = 1  # 최대 포지션 (1=long only, -1~1=long-short)
    allow_short: bool = True  # 공매도 허용

    # 보상 함수 파라미터
    opportunity_cost_factor: float = 0.5
    long_loss_penalty: float = 0.9


# ── Action / Position 정의 ────────────────────────────────────────────────

ACTION_BUY = 0
ACTION_SELL = 1
ACTION_HOLD = 2
ACTION_CLOSE = 3  # 포지션 청산 (flat으로)
NUM_ACTIONS = 4


def action_to_str(action: int) -> str:
    """Action index → 문자열."""
    return {ACTION_BUY: "BUY", ACTION_SELL: "SELL", ACTION_HOLD: "HOLD", ACTION_CLOSE: "CLOSE"}.get(
        action, "HOLD"
    )


# ── 트레이딩 환경 ─────────────────────────────────────────────────────────


class TradingEnv:
    """Gymnasium 호환 트레이딩 시뮬레이터.

    Gymnasium이 설치된 경우 gym.Env를 상속하여 SB3 호환.
    설치되지 않은 경우에도 동일한 step/reset API를 제공.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(self, config: TradingEnvConfig) -> None:
        self.config = config
        self.closes = np.array(config.closes, dtype=np.float64)
        self.volumes = np.array(config.volumes, dtype=np.float64) if config.volumes else np.zeros(
            len(config.closes), dtype=np.float64
        )

        if len(self.closes) < config.lookback + 2:
            raise ValueError(
                f"데이터 부족: closes={len(self.closes)}, 최소 필요={config.lookback + 2}"
            )

        # 수익률 사전 계산
        self.returns = np.zeros(len(self.closes))
        self.returns[1:] = np.diff(self.closes) / self.closes[:-1]

        # SMA 사전 계산
        self._sma5 = self._rolling_mean(self.closes, 5)
        self._sma20 = self._rolling_mean(self.closes, 20)

        # RSI 사전 계산
        self._rsi = self._compute_rsi_array(self.closes, 14)

        # 변동성 사전 계산
        self._vol = self._rolling_std(self.returns, 10)

        # 거래량 비율 사전 계산
        vol_sma = self._rolling_mean(self.volumes, 20)
        self._vol_ratio = np.where(vol_sma > 0, self.volumes / vol_sma, 1.0)

        # 환경 상태
        self._step_idx = 0
        self._position = 0  # -1, 0, 1
        self._entry_price = 0.0
        self._portfolio_value = 1.0  # 정규화 (1.0 = 초기)
        self._peak_value = 1.0
        self._total_trades = 0
        self._trade_log: list[dict] = []

        # Gymnasium spaces
        n_features = len(config.feature_columns) + 1  # +1 for position
        if HAS_GYMNASIUM:
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(n_features,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(NUM_ACTIONS)

    def reset(
        self, *, seed: int | None = None, options: dict | None = None
    ) -> tuple[np.ndarray, dict]:
        """환경 초기화."""
        if seed is not None and HAS_GYMNASIUM:
            np.random.seed(seed)

        self._step_idx = self.config.lookback
        self._position = 0
        self._entry_price = 0.0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._total_trades = 0
        self._trade_log = []

        obs = self._get_observation()
        info = self._get_info()
        return obs, info

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """한 스텝 실행.

        Returns:
            obs, reward, terminated, truncated, info
        """
        if self._step_idx >= len(self.closes) - 1:
            return self._get_observation(), 0.0, True, False, self._get_info()

        prev_position = self._position
        prev_price = self.closes[self._step_idx]

        # 포지션 전환
        new_position = self._apply_action(action, prev_position)

        # 다음 스텝으로 이동
        self._step_idx += 1
        next_price = self.closes[self._step_idx]
        daily_return = (next_price - prev_price) / prev_price

        # 거래 비용
        trade_cost = 0.0
        if new_position != prev_position:
            self._total_trades += 1
            trade_cost_bps = self.config.trade_penalty_bps + self.config.slippage_bps
            trade_cost = trade_cost_bps / 10_000
            self._trade_log.append(
                {
                    "step": self._step_idx,
                    "action": action_to_str(action),
                    "prev_pos": prev_position,
                    "new_pos": new_position,
                    "price": next_price,
                }
            )

        # 보상 계산
        reward = self._compute_reward(
            new_position, daily_return, trade_cost, prev_position
        )

        # 포트폴리오 가치 업데이트
        position_pnl = new_position * daily_return - trade_cost
        self._portfolio_value *= 1 + position_pnl
        self._peak_value = max(self._peak_value, self._portfolio_value)
        self._position = new_position

        if new_position != 0:
            self._entry_price = next_price

        # 종료 조건
        drawdown_pct = (
            (self._portfolio_value / self._peak_value - 1.0) * 100
            if self._peak_value > 0
            else 0.0
        )
        terminated = False
        if drawdown_pct <= self.config.max_drawdown_pct:
            terminated = True
        if self._step_idx >= len(self.closes) - 1:
            terminated = True

        obs = self._get_observation()
        info = self._get_info()

        return obs, reward, terminated, False, info

    def _apply_action(self, action: int, current_pos: int) -> int:
        """액션을 포지션으로 변환."""
        if action == ACTION_BUY:
            return 1
        elif action == ACTION_SELL:
            return -1 if self.config.allow_short else 0
        elif action == ACTION_CLOSE:
            return 0
        else:  # HOLD
            return current_pos

    def _compute_reward(
        self,
        position: int,
        daily_return: float,
        trade_cost: float,
        prev_position: int,
    ) -> float:
        """보상 함수 (V2 호환).

        - position_return = position × daily_return
        - opportunity_cost: flat일 때 놓친 기회 또는 회피 보너스
        - long_loss_penalty: long 포지션 손실 가중
        - trade_cost: 거래 비용
        """
        position_return = position * daily_return

        # 기회 비용 / 보너스
        opp = 0.0
        if position == 0:
            if daily_return > 0:
                opp = -self.config.opportunity_cost_factor * daily_return
            else:
                opp = self.config.opportunity_cost_factor * abs(daily_return)

        # Long 손실 가중 페널티
        loss_penalty = 0.0
        if position == 1 and daily_return < 0:
            loss_penalty = -self.config.long_loss_penalty * abs(daily_return)

        reward = position_return + opp + loss_penalty - trade_cost
        return float(reward)

    def _get_observation(self) -> np.ndarray:
        """현재 관측값 벡터."""
        idx = self._step_idx
        features: list[float] = []

        for col in self.config.feature_columns:
            if col == "return":
                features.append(float(self.returns[idx]))
            elif col == "sma_cross":
                sma5 = self._sma5[idx]
                sma20 = self._sma20[idx]
                features.append(float((sma5 - sma20) / sma20) if sma20 > 0 else 0.0)
            elif col == "rsi_norm":
                features.append(float((self._rsi[idx] - 50.0) / 50.0))  # -1 ~ 1
            elif col == "volatility":
                features.append(float(self._vol[idx]))
            elif col == "volume_ratio":
                features.append(float(self._vol_ratio[idx]) - 1.0)  # 중심 0

        # 포지션 추가
        features.append(float(self._position))

        return np.array(features, dtype=np.float32)

    def _get_info(self) -> dict[str, Any]:
        """현재 환경 정보."""
        return_pct = (self._portfolio_value - 1.0) * 100
        drawdown_pct = (
            (self._portfolio_value / self._peak_value - 1.0) * 100
            if self._peak_value > 0
            else 0.0
        )
        return {
            "step": self._step_idx,
            "position": self._position,
            "portfolio_value": self._portfolio_value,
            "return_pct": return_pct,
            "drawdown_pct": drawdown_pct,
            "total_trades": self._total_trades,
            "price": float(self.closes[self._step_idx]),
        }

    # ── 유틸리티 ──────────────────────────────────────────────────────────

    @staticmethod
    def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
        """Rolling mean (edge-padded)."""
        result = np.zeros_like(arr)
        cumsum = np.cumsum(arr)
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            count = i - start + 1
            if start == 0:
                result[i] = cumsum[i] / count
            else:
                result[i] = (cumsum[i] - cumsum[start - 1]) / count
        return result

    @staticmethod
    def _rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
        """Rolling std."""
        result = np.zeros_like(arr)
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            segment = arr[start : i + 1]
            if len(segment) < 2:
                result[i] = 0.0
            else:
                result[i] = float(np.std(segment, ddof=1))
        return result

    @staticmethod
    def _compute_rsi_array(closes: np.ndarray, period: int = 14) -> np.ndarray:
        """RSI 배열 계산."""
        rsi = np.full(len(closes), 50.0)
        if len(closes) < 2:
            return rsi

        deltas = np.diff(closes)
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)

        if len(deltas) < period:
            return rsi

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)

        return rsi

    def get_episode_summary(self) -> dict[str, Any]:
        """에피소드 종료 후 요약 통계."""
        return_pct = (self._portfolio_value - 1.0) * 100
        baseline_return = (
            (float(self.closes[-1]) / float(self.closes[self.config.lookback]) - 1.0) * 100
            if len(self.closes) > self.config.lookback
            else 0.0
        )
        drawdown_pct = (
            (self._portfolio_value / self._peak_value - 1.0) * 100
            if self._peak_value > 0
            else 0.0
        )

        # 승률 계산
        wins = sum(1 for t in self._trade_log if t.get("pnl", 0) > 0)
        total = len(self._trade_log) or 1

        return {
            "total_return_pct": round(return_pct, 4),
            "baseline_return_pct": round(baseline_return, 4),
            "excess_return_pct": round(return_pct - baseline_return, 4),
            "max_drawdown_pct": round(drawdown_pct, 4),
            "total_trades": self._total_trades,
            "win_rate": round(wins / total, 4),
            "steps": self._step_idx - self.config.lookback,
            "final_portfolio_value": round(self._portfolio_value, 6),
        }


# ── Gymnasium 등록 (선택적) ────────────────────────────────────────────────

if HAS_GYMNASIUM:

    class GymTradingEnv(gym.Env, TradingEnv):
        """Gymnasium 정식 등록용 래퍼."""

        def __init__(self, config: TradingEnvConfig) -> None:
            TradingEnv.__init__(self, config)
