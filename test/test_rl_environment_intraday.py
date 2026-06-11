"""test/test_rl_environment_intraday.py — TradingEnv 일중 특징 관측 통합 테스트"""

import types
import unittest


from src.agents.rl_environment import (
    NUM_ACTIONS,
    TradingEnv,
    TradingEnvConfig,
    env_config_from_dataset,
)

_N_INTRADAY = 6  # INTRADAY_OBS_KEYS 차원 (5 특징 + has_intraday)
_BASE_FEATURES = ["return", "sma_cross", "rsi_norm", "volatility", "volume_ratio"]


def _closes(n: int = 60) -> list[float]:
    return [100.0 + (i % 9) - 4 for i in range(n)]


def _intraday(n: int = 60) -> list[list[float]]:
    # 앞 절반은 마스킹(0), 뒤 절반은 값 + has_intraday=1
    rows = []
    for i in range(n):
        if i < n // 2:
            rows.append([0.0] * _N_INTRADAY)
        else:
            rows.append([0.01, 0.005, 0.002, -0.001, 0.1, 1.0])
    return rows


class EnvIntradayObsTest(unittest.TestCase):
    def test_backward_compat_no_intraday(self) -> None:
        env = TradingEnv(TradingEnvConfig(closes=_closes(), lookback=20))
        obs, _ = env.reset()
        self.assertEqual(obs.shape[0], len(_BASE_FEATURES) + 1)  # +position

    def test_obs_dim_includes_intraday(self) -> None:
        env = TradingEnv(
            TradingEnvConfig(closes=_closes(), intraday_features=_intraday(), lookback=20)
        )
        obs, _ = env.reset()
        self.assertEqual(obs.shape[0], len(_BASE_FEATURES) + 1 + _N_INTRADAY)

    def test_intraday_values_present_in_obs(self) -> None:
        env = TradingEnv(
            TradingEnvConfig(closes=_closes(), intraday_features=_intraday(), lookback=20)
        )
        env.reset()
        # 뒷부분 스텝까지 진행 → has_intraday=1 구간 관측
        obs = None
        for _ in range(40):
            obs, _r, term, _t, _i = env.step(2)  # HOLD
            if term:
                break
        self.assertIsNotNone(obs)
        # 마지막 차원 = has_intraday, 뒤 절반 구간이면 1.0
        self.assertIn(obs[-1], (0.0, 1.0))

    def test_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            TradingEnv(
                TradingEnvConfig(
                    closes=_closes(60), intraday_features=_intraday(50), lookback=20
                )
            )

    def test_full_episode_runs_with_intraday(self) -> None:
        env = TradingEnv(
            TradingEnvConfig(closes=_closes(), intraday_features=_intraday(), lookback=20)
        )
        env.reset()
        steps = 0
        terminated = False
        while not terminated and steps < 100:
            action = steps % NUM_ACTIONS
            _obs, _r, terminated, _t, _info = env.step(action)
            steps += 1
        self.assertGreater(steps, 0)
        summary = env.get_episode_summary()
        self.assertIn("total_return_pct", summary)


class EnvConfigFromDatasetTest(unittest.TestCase):
    def _dataset(self, with_features: bool):
        return types.SimpleNamespace(
            ticker="005930.KS",
            closes=_closes(60),
            timestamps=[f"2026-{1 + i % 9:02d}-01" for i in range(60)],
            features=_intraday(60) if with_features else None,
            feature_keys=tuple(f"k{i}" for i in range(_N_INTRADAY)) if with_features else None,
        )

    def test_combined_dataset_includes_intraday(self) -> None:
        cfg = env_config_from_dataset(self._dataset(True), lookback=20)
        self.assertIsNotNone(cfg.intraday_features)
        env = TradingEnv(cfg)
        obs, _ = env.reset()
        self.assertEqual(obs.shape[0], len(_BASE_FEATURES) + 1 + _N_INTRADAY)

    def test_daily_dataset_no_intraday(self) -> None:
        cfg = env_config_from_dataset(self._dataset(False), lookback=20)
        self.assertIsNone(cfg.intraday_features)
        env = TradingEnv(cfg)
        obs, _ = env.reset()
        self.assertEqual(obs.shape[0], len(_BASE_FEATURES) + 1)


if __name__ == "__main__":
    unittest.main()
