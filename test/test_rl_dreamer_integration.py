"""test/test_rl_dreamer_integration.py — Dreamer 프로파일 라우팅·opt-out·walk-forward 통합"""

import os
import unittest

from src.agents.rl_continuous_improver import (
    RLContinuousImprover,
    _WalkForwardDreamerAdapter,
    _default_profile_ids,
)
from src.agents.rl_dreamer import DreamerConfig, DreamerV3Trainer
from src.agents.rl_experiment_manager import RLExperimentManager


def _closes(n: int = 80) -> list[float]:
    return [100.0 + 5.0 * (i % 11) / 11.0 + i * 0.05 for i in range(n)]


class DreamerProfileRoutingTest(unittest.TestCase):
    def test_dreamer_excluded_from_default_profiles(self) -> None:
        ids = _default_profile_ids()
        # 운영 안전: dreamer 는 default_enabled=false 라 야간 자동 학습에서 제외
        self.assertNotIn("dreamer_v3", ids)
        # 기존 프로파일은 여전히 포함
        self.assertTrue(any("tabular" in p for p in ids), ids)

    def test_dreamer_profile_loadable(self) -> None:
        profile = RLExperimentManager().load_profile("dreamer_v3")
        self.assertEqual(profile["algorithm"], "dreamer_v3")
        self.assertFalse(profile.get("default_enabled", True))
        self.assertEqual(profile["dataset"]["data_scope"], "combined")

    def test_trainer_for_profile_routes_dreamer(self) -> None:
        profile = RLExperimentManager().load_profile("dreamer_v3")
        improver = RLContinuousImprover()
        trainer = improver._trainer_for_profile(profile)
        self.assertIsInstance(trainer, DreamerV3Trainer)
        self.assertEqual(trainer.algorithm, "dreamer_v3")
        # trainer_params 가 DreamerConfig 로 필터링·반영됨
        self.assertEqual(trainer.cfg.deter_dim, 64)
        self.assertEqual(trainer.cfg.lookback, 20)


class DreamerWalkForwardAdapterTest(unittest.TestCase):
    def test_adapter_train_returns_model_path_and_evaluates(self) -> None:
        cfg = DreamerConfig(
            deter_dim=16, stoch_dim=8, hidden_dim=32, horizon=3, seq_len=16,
            batch_size=8, train_iters=6, collect_episodes=3, lookback=10, seed=3,
        )
        trainer = DreamerV3Trainer(cfg=cfg)
        adapter = _WalkForwardDreamerAdapter("005930.KS", trainer)
        model_path = adapter.train(_closes(80))
        try:
            self.assertTrue(model_path and os.path.exists(model_path))
            metrics = adapter.evaluate(model_path, _closes(40))
            self.assertTrue(hasattr(metrics, "total_return_pct"))
            self.assertTrue(hasattr(metrics, "excess_return_pct"))
        finally:
            if model_path and os.path.exists(model_path):
                os.remove(model_path)


if __name__ == "__main__":
    unittest.main()
