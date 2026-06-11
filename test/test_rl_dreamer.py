"""test/test_rl_dreamer.py — DreamerV3 트레이너 end-to-end (소규모) + 정책 추론 통합"""

import os
import tempfile
import types
import unittest

from src.agents.rl_dreamer import (
    DreamerConfig,
    DreamerRLPolicy,
    DreamerV3Trainer,
    save_dreamer_checkpoint,
)
from src.agents.rl_policy_interface import PolicyDecision, policy_from_artifact
from src.agents.rl_trading import RLPolicyArtifact

_N_INTRADAY = 6


def _small_cfg() -> DreamerConfig:
    return DreamerConfig(
        deter_dim=16, stoch_dim=8, hidden_dim=32, horizon=3, seq_len=16,
        batch_size=8, train_iters=8, collect_episodes=3, lookback=10, seed=7,
    )


def _dataset(n: int = 80, with_features: bool = True):
    closes = [100.0 + 5.0 * (i % 11) / 11.0 + (i * 0.05) for i in range(n)]
    feats = None
    if with_features:
        feats = [
            [0.0] * _N_INTRADAY if i < n // 2 else [0.01, 0.005, 0.002, -0.001, 0.1, 1.0]
            for i in range(n)
        ]
    return types.SimpleNamespace(
        ticker="005930.KS",
        closes=closes,
        timestamps=[f"2026-01-{(i % 27) + 1:02d}" for i in range(n)],
        features=feats,
        feature_keys=tuple(f"k{i}" for i in range(_N_INTRADAY)) if with_features else None,
    )


def _artifact(model_path: str) -> RLPolicyArtifact:
    return RLPolicyArtifact.from_dict({
        "policy_id": "dreamer-test", "ticker": "005930.KS", "created_at": "2026-06-12",
        "algorithm": "dreamer_v3", "state_version": "dreamer_v1", "lookback": 10,
        "episodes": 0, "learning_rate": 6e-4, "discount_factor": 0.99,
        "epsilon": 0.0, "trade_penalty_bps": 2,
        "evaluation": {
            "total_return_pct": 0.0, "baseline_return_pct": 0.0, "excess_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "trades": 0, "win_rate": 0.0, "holdout_steps": 0,
            "approved": False,
        },
        "model_path": model_path,
    })


class DreamerTrainTest(unittest.TestCase):
    def test_train_combined_returns_artifact_payload(self) -> None:
        trainer = DreamerV3Trainer(cfg=_small_cfg())
        result = trainer.train(_dataset(80, with_features=True))
        self.assertIn("state_dict", result)
        self.assertIn("world", result["state_dict"])
        self.assertIn("ac", result["state_dict"])
        # combined: obs_dim = 가격특징5 + 포지션1 + 일중6 = 12
        self.assertEqual(result["obs_dim"], 12)
        ev = result["evaluation"]
        for k in ("total_return_pct", "excess_return_pct", "max_drawdown_pct", "approved"):
            self.assertIn(k, ev)

    def test_train_daily_only_smaller_obs(self) -> None:
        trainer = DreamerV3Trainer(cfg=_small_cfg())
        result = trainer.train(_dataset(80, with_features=False))
        self.assertEqual(result["obs_dim"], 6)  # 가격특징5 + 포지션1


class DreamerPolicyInferenceTest(unittest.TestCase):
    def test_checkpoint_save_load_and_act(self) -> None:
        trainer = DreamerV3Trainer(cfg=_small_cfg())
        result = trainer.train(_dataset(80, with_features=True))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dreamer.pt")
            save_dreamer_checkpoint(path, result)
            self.assertTrue(os.path.exists(path))

            policy = policy_from_artifact(_artifact(path))
            self.assertIsInstance(policy, DreamerRLPolicy)
            self.assertEqual(policy.algorithm, "dreamer_v3")

            ds = _dataset(60, with_features=True)
            decision = policy.act(ds.closes, position=0, features=ds.features)
            self.assertIsInstance(decision, PolicyDecision)
            self.assertIn(decision.action, ("BUY", "SELL", "HOLD", "CLOSE"))
            self.assertGreaterEqual(decision.confidence, 0.0)
            self.assertLessEqual(decision.confidence, 1.0)

    def test_missing_model_path_raises(self) -> None:
        art = _artifact("")
        with self.assertRaises(ValueError):
            DreamerRLPolicy(art)


if __name__ == "__main__":
    unittest.main()
