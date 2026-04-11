"""
test/test_rl_environment.py — TradingEnv 상태 공간, 보상 함수, 에피소드 전이 검증

Gymnasium 호환 트레이딩 환경의 단위 테스트.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from src.agents.rl_environment import (
    TradingEnv,
    TradingEnvConfig,
    ACTION_BUY,
    ACTION_SELL,
    ACTION_HOLD,
    ACTION_CLOSE,
    NUM_ACTIONS,
    action_to_str,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _uptrend_closes(length: int = 60, start: float = 100.0) -> list[float]:
    return [start + i * 1.5 for i in range(length)]


def _downtrend_closes(length: int = 60, start: float = 200.0) -> list[float]:
    return [start - i * 1.5 for i in range(length)]


def _flat_closes(length: int = 60, price: float = 100.0) -> list[float]:
    return [price] * length


def _volatile_closes(length: int = 60) -> list[float]:
    return [100.0 + (10.0 if i % 2 == 0 else -10.0) for i in range(length)]


def _make_config(closes: list[float], **kwargs) -> TradingEnvConfig:
    volumes = kwargs.pop("volumes", [1_000_000] * len(closes))
    return TradingEnvConfig(closes=closes, volumes=volumes, **kwargs)


# ── Config Validation Tests ──────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestTradingEnvConfig:
    """환경 설정 유효성 검증."""

    def test_minimum_data_length(self):
        """lookback + 2 미만 데이터로 환경 생성 시 ValueError."""
        with pytest.raises(ValueError, match="데이터 부족"):
            TradingEnv(TradingEnvConfig(closes=[100.0] * 5, lookback=20))

    def test_valid_minimum_data(self):
        """lookback + 2 이상이면 정상 생성."""
        closes = [100.0] * 22
        env = TradingEnv(_make_config(closes))
        assert env is not None

    def test_default_feature_columns(self):
        config = TradingEnvConfig()
        assert "return" in config.feature_columns
        assert "sma_cross" in config.feature_columns
        assert "rsi_norm" in config.feature_columns
        assert "volatility" in config.feature_columns
        assert "volume_ratio" in config.feature_columns

    def test_custom_lookback(self):
        closes = [100.0] * 50
        config = _make_config(closes, lookback=10)
        env = TradingEnv(config)
        assert env.config.lookback == 10


# ── Action Mapping Tests ────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestActionMapping:
    """액션 매핑 테스트."""

    def test_action_to_str(self):
        assert action_to_str(ACTION_BUY) == "BUY"
        assert action_to_str(ACTION_SELL) == "SELL"
        assert action_to_str(ACTION_HOLD) == "HOLD"
        assert action_to_str(ACTION_CLOSE) == "CLOSE"

    def test_invalid_action_defaults_hold(self):
        assert action_to_str(99) == "HOLD"

    def test_num_actions(self):
        assert NUM_ACTIONS == 4


# ── Reset Tests ──────────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestReset:
    """환경 초기화 테스트."""

    def test_reset_returns_observation_and_info(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        obs, info = env.reset()
        assert isinstance(obs, np.ndarray)
        assert isinstance(info, dict)

    def test_reset_observation_shape(self):
        closes = _uptrend_closes()
        config = _make_config(closes)
        env = TradingEnv(config)
        obs, _ = env.reset()
        # features + position = 5 features + 1 position = 6
        expected_size = len(config.feature_columns) + 1
        assert obs.shape == (expected_size,)

    def test_reset_initial_state(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        info = env._get_info()
        assert info["position"] == 0
        assert info["portfolio_value"] == 1.0
        assert info["total_trades"] == 0

    def test_reset_clears_trade_log(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        assert env._total_trades == 1
        env.reset()
        assert env._total_trades == 0
        assert env._trade_log == []

    def test_reset_with_seed(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        obs1, _ = env.reset(seed=42)
        obs2, _ = env.reset(seed=42)
        np.testing.assert_array_equal(obs1, obs2)


# ── Step / State Transition Tests ────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestStepTransition:
    """스텝 실행 및 상태 전이 테스트."""

    def test_step_returns_five_tuple(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        result = env.step(ACTION_HOLD)
        assert len(result) == 5
        obs, reward, terminated, truncated, info = result
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_buy_action_changes_position(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        assert env._position == 1

    def test_sell_action_short_position(self):
        env = TradingEnv(_make_config(_uptrend_closes(), allow_short=True))
        env.reset()
        env.step(ACTION_SELL)
        assert env._position == -1

    def test_sell_action_no_short(self):
        """공매도 비허용 시 SELL은 포지션 0."""
        env = TradingEnv(_make_config(_uptrend_closes(), allow_short=False))
        env.reset()
        env.step(ACTION_SELL)
        assert env._position == 0

    def test_hold_preserves_position(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        assert env._position == 1
        env.step(ACTION_HOLD)
        assert env._position == 1

    def test_close_flattens_position(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        assert env._position == 1
        env.step(ACTION_CLOSE)
        assert env._position == 0

    def test_step_increments_index(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        initial_idx = env._step_idx
        env.step(ACTION_HOLD)
        assert env._step_idx == initial_idx + 1

    def test_episode_terminates_at_end(self):
        """데이터 끝에 도달하면 terminated=True."""
        closes = _flat_closes(length=25)  # lookback=20, 5 steps left
        env = TradingEnv(_make_config(closes))
        env.reset()

        terminated = False
        for _ in range(10):
            _, _, terminated, _, _ = env.step(ACTION_HOLD)
            if terminated:
                break
        assert terminated


# ── Reward Function Tests ────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRewardFunction:
    """보상 함수 검증."""

    def test_long_position_positive_return(self):
        """롱 포지션 + 상승 → 양의 보상."""
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        _, reward, _, _, _ = env.step(ACTION_BUY)
        assert reward > 0

    def test_long_position_negative_return(self):
        """롱 포지션 + 하락 → 음의 보상 (long_loss_penalty 포함)."""
        env = TradingEnv(_make_config(_downtrend_closes()))
        env.reset()
        _, reward, _, _, _ = env.step(ACTION_BUY)
        assert reward < 0

    def test_flat_position_opportunity_cost(self):
        """포지션 없음 + 상승 → 기회 비용 (음의 보상)."""
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        _, reward, _, _, _ = env.step(ACTION_HOLD)
        # position=0, daily_return>0 → opp = -factor*return < 0
        assert reward < 0

    def test_flat_position_avoidance_bonus(self):
        """포지션 없음 + 하락 → 회피 보너스 (양의 보상)."""
        env = TradingEnv(_make_config(_downtrend_closes()))
        env.reset()
        _, reward, _, _, _ = env.step(ACTION_HOLD)
        # position=0, daily_return<0 → opp = factor*|return| > 0
        assert reward > 0

    def test_trade_cost_deducted(self):
        """포지션 전환 시 거래 비용이 보상에서 차감."""
        closes = _flat_closes()
        env = TradingEnv(_make_config(closes, trade_penalty_bps=10, slippage_bps=5))
        env.reset()
        _, reward_buy, _, _, _ = env.step(ACTION_BUY)
        # 거래비용 = (10 + 5) / 10000 = 0.0015 차감
        assert reward_buy < 0  # flat closes 이므로 position_return ≈ 0, 비용만 차감

    def test_compute_reward_directly(self):
        """_compute_reward 메서드 직접 호출 테스트."""
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()

        # 롱 포지션, 양의 수익률, 거래비용 없음
        reward = env._compute_reward(
            position=1,
            daily_return=0.02,
            trade_cost=0.0,
            prev_position=1,
        )
        assert reward > 0

        # 롱 포지션, 음의 수익률 → long_loss_penalty 적용
        reward_loss = env._compute_reward(
            position=1,
            daily_return=-0.02,
            trade_cost=0.0,
            prev_position=1,
        )
        assert reward_loss < 0

    def test_short_position_on_downtrend(self):
        """숏 포지션 + 하락 → 양의 보상."""
        env = TradingEnv(_make_config(_downtrend_closes(), allow_short=True))
        env.reset()
        _, reward, _, _, _ = env.step(ACTION_SELL)
        # position=-1, daily_return<0 → position_return > 0
        assert reward > 0


# ── Portfolio Value / Drawdown Tests ─────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestPortfolioTracking:
    """포트폴리오 가치 및 낙폭 추적."""

    def test_portfolio_value_increases_on_profit(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        info = env._get_info()
        assert info["portfolio_value"] > 1.0

    def test_portfolio_value_decreases_on_loss(self):
        env = TradingEnv(_make_config(_downtrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        info = env._get_info()
        assert info["portfolio_value"] < 1.0

    def test_drawdown_terminates_episode(self):
        """최대 낙폭 초과 시 에피소드 종료."""
        # 급격한 하락 데이터
        closes = [100.0] * 22 + [100.0 - i * 5 for i in range(20)]
        env = TradingEnv(_make_config(closes, max_drawdown_pct=-30.0))
        env.reset()

        terminated = False
        for _ in range(30):
            _, _, terminated, _, info = env.step(ACTION_BUY)
            if terminated:
                break
        assert terminated

    def test_peak_value_tracking(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        assert env._peak_value >= env._portfolio_value


# ── Observation Tests ────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestObservation:
    """관측값 벡터 검증."""

    def test_observation_dtype(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        obs, _ = env.reset()
        assert obs.dtype == np.float32

    def test_observation_includes_position(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        obs_flat = env._get_observation()
        assert obs_flat[-1] == 0.0  # flat

        env.step(ACTION_BUY)
        obs_long = env._get_observation()
        assert obs_long[-1] == 1.0  # long

    def test_observation_no_nan(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        obs, _ = env.reset()
        assert not np.any(np.isnan(obs))

    def test_observation_after_step(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        obs1, _ = env.reset()
        obs2, _, _, _, _ = env.step(ACTION_HOLD)
        # Observations should differ after a step
        assert not np.array_equal(obs1, obs2)


# ── Episode Summary Tests ────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestEpisodeSummary:
    """에피소드 요약 통계 검증."""

    def test_summary_keys(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)
        summary = env.get_episode_summary()
        expected_keys = {
            "total_return_pct",
            "baseline_return_pct",
            "excess_return_pct",
            "max_drawdown_pct",
            "total_trades",
            "win_rate",
            "steps",
            "final_portfolio_value",
        }
        assert set(summary.keys()) == expected_keys

    def test_summary_total_trades_counted(self):
        env = TradingEnv(_make_config(_uptrend_closes()))
        env.reset()
        env.step(ACTION_BUY)   # trade 1
        env.step(ACTION_CLOSE) # trade 2
        env.step(ACTION_BUY)   # trade 3
        summary = env.get_episode_summary()
        assert summary["total_trades"] == 3

    def test_summary_initial_state(self):
        env = TradingEnv(_make_config(_flat_closes()))
        env.reset()
        summary = env.get_episode_summary()
        assert summary["total_trades"] == 0
        assert summary["steps"] == 0


# ── Utility Function Tests ───────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestUtilities:
    """유틸리티 함수 테스트."""

    def test_rolling_mean(self):
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = TradingEnv._rolling_mean(arr, 3)
        assert result[-1] == pytest.approx(4.0)  # (3+4+5)/3

    def test_rolling_std(self):
        arr = np.array([1.0, 1.0, 1.0, 1.0])
        result = TradingEnv._rolling_std(arr, 3)
        assert result[-1] == 0.0  # 상수 → std=0

    def test_rsi_bounds(self):
        """RSI는 0~100 범위."""
        closes = np.array(_uptrend_closes(100))
        rsi = TradingEnv._compute_rsi_array(closes, 14)
        assert np.all(rsi >= 0)
        assert np.all(rsi <= 100)

    def test_rsi_short_data(self):
        closes = np.array([100.0])
        rsi = TradingEnv._compute_rsi_array(closes, 14)
        assert len(rsi) == 1
        assert rsi[0] == 50.0  # 기본값


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestEnvironmentEdgeCases:
    """환경 에지 케이스."""

    def test_step_after_termination(self):
        """종료 후 step 호출 시 안전하게 처리."""
        closes = _flat_closes(length=23)  # lookback=20, 3 steps
        env = TradingEnv(_make_config(closes))
        env.reset()
        for _ in range(10):
            _, _, terminated, _, _ = env.step(ACTION_HOLD)
            if terminated:
                break
        # 종료 후 추가 step
        obs, reward, term, trunc, info = env.step(ACTION_HOLD)
        assert term is True
        assert reward == 0.0

    def test_empty_volumes(self):
        """빈 volumes로도 환경 생성 가능."""
        closes = _uptrend_closes()
        config = TradingEnvConfig(closes=closes, volumes=[])
        env = TradingEnv(config)
        obs, _ = env.reset()
        assert not np.any(np.isnan(obs))

    def test_constant_price_near_zero_return(self):
        """일정 가격 → 수익률 근접 0 (거래 비용 제외)."""
        env = TradingEnv(_make_config(_flat_closes()))
        env.reset()
        _, _, _, _, info = env.step(ACTION_BUY)
        # BUY 시 거래비용(3bps)이 차감되므로 약간 음의 수익률
        assert abs(info["return_pct"]) < 0.1

    def test_apply_action_all_actions(self):
        """모든 액션 매핑 직접 검증."""
        env = TradingEnv(_make_config(_uptrend_closes()))
        assert env._apply_action(ACTION_BUY, 0) == 1
        assert env._apply_action(ACTION_SELL, 0) == -1  # allow_short=True
        assert env._apply_action(ACTION_HOLD, 1) == 1
        assert env._apply_action(ACTION_HOLD, -1) == -1
        assert env._apply_action(ACTION_CLOSE, 1) == 0
        assert env._apply_action(ACTION_CLOSE, -1) == 0

    def test_full_episode_uptrend(self):
        """상승 추세에서 전체 에피소드 완주 → 양의 수익."""
        env = TradingEnv(_make_config(_uptrend_closes(60)))
        env.reset()
        env.step(ACTION_BUY)
        terminated = False
        while not terminated:
            _, _, terminated, _, _ = env.step(ACTION_HOLD)
        summary = env.get_episode_summary()
        assert summary["total_return_pct"] > 0

    def test_full_episode_downtrend_short(self):
        """하락 추세에서 숏 포지션 → 양의 수익."""
        env = TradingEnv(_make_config(_downtrend_closes(60), allow_short=True))
        env.reset()
        env.step(ACTION_SELL)
        terminated = False
        while not terminated:
            _, _, terminated, _, _ = env.step(ACTION_HOLD)
        summary = env.get_episode_summary()
        assert summary["total_return_pct"] > 0
