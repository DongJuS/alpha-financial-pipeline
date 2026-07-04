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
        result = trainer._train_core(_dataset(80, with_features=True))
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
        result = trainer._train_core(_dataset(80, with_features=False))
        self.assertEqual(result["obs_dim"], 6)  # 가격특징5 + 포지션1


class DreamerPolicyInferenceTest(unittest.TestCase):
    def test_checkpoint_save_load_and_act(self) -> None:
        trainer = DreamerV3Trainer(cfg=_small_cfg())
        result = trainer._train_core(_dataset(80, with_features=True))
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

    def test_act_auto_masks_features_when_omitted(self) -> None:
        # combined 로 학습된 정책 (obs_dim=12) 이 있어도 호출자가 features 를 안
        # 넘기면 shape mismatch 로 폭발했었다. 이제 어댑터가 학습된 obs_dim 과
        # DEFAULT_DAILY_OBS_DIM 을 비교해 부족한 차원만큼 zero-mask 로 채우고,
        # 그 결과 정상 PolicyDecision 을 반환해야 한다. (Option A 안전망)
        trainer = DreamerV3Trainer(cfg=_small_cfg())
        result = trainer._train_core(_dataset(80, with_features=True))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dreamer_combined.pt")
            save_dreamer_checkpoint(path, result)
            policy = policy_from_artifact(_artifact(path))

            closes = _dataset(60, with_features=False).closes
            # features 인자를 아예 안 넘김 — Runner 가 combined-aware 이지 않을
            # 때의 호출 패턴 시뮬레이션.
            decision = policy.act(closes, position=0)
            self.assertIsInstance(decision, PolicyDecision)
            self.assertIn(decision.action, ("BUY", "SELL", "HOLD", "CLOSE"))


class DreamerTrainerContractTest(unittest.TestCase):
    """RLContinuousImprover 계약(train_with_metadata/evaluate) 적합성."""

    def test_train_with_metadata_returns_artifact_and_split(self) -> None:
        from src.agents.rl_trading import RLEvaluationMetrics, RLSplitMetadata

        trainer = DreamerV3Trainer(cfg=_small_cfg())
        artifact, split = trainer.train_with_metadata(_dataset(80, True), train_ratio=0.7)
        try:
            self.assertEqual(artifact.algorithm, "dreamer_v3")
            self.assertIsNone(artifact.q_table)
            self.assertTrue(artifact.model_path and os.path.exists(artifact.model_path))
            self.assertIsInstance(artifact.evaluation, RLEvaluationMetrics)
            self.assertIsInstance(split, RLSplitMetadata)
            self.assertEqual(split.train_size + split.test_size, 80)

            # 팩토리로 정책 생성 → 추론
            policy = policy_from_artifact(artifact)
            self.assertIsInstance(policy, DreamerRLPolicy)
            ds = _dataset(60, True)
            decision = policy.act(ds.closes, position=0, features=ds.features)
            self.assertIn(decision.action, ("BUY", "SELL", "HOLD", "CLOSE"))
            # 주: evaluate()는 walk-forward 의 daily 경로 전용(obs_dim 일치).
            # combined 모델의 평가는 _train_core 의 홀드아웃에서 수행됨.
        finally:
            if artifact.model_path and os.path.exists(artifact.model_path):
                os.remove(artifact.model_path)

    def test_evaluate_adapter_arg_order(self) -> None:
        trainer = DreamerV3Trainer(cfg=_small_cfg())
        artifact, _ = trainer.train_with_metadata(_dataset(80, False), train_ratio=0.7)
        try:
            closes = _dataset(40, False).closes
            # 두 인자 순서 모두 동작
            m1 = trainer.evaluate(artifact.model_path, closes)
            m2 = trainer.evaluate(closes, artifact.model_path)
            self.assertEqual(m1.holdout_steps, m2.holdout_steps)
        finally:
            if artifact.model_path and os.path.exists(artifact.model_path):
                os.remove(artifact.model_path)


class RLEvaluationMetricsCoerceTest(unittest.TestCase):
    """SB3 / Dreamer 학습 결과가 numpy/torch 스칼라로 들어와도 json.dumps 통과."""

    def test_numpy_scalars_coerced_to_native(self) -> None:
        import json

        import numpy as np

        from src.agents.rl_trading import RLEvaluationMetrics

        m = RLEvaluationMetrics(
            total_return_pct=np.float64(12.34),
            baseline_return_pct=np.float32(5.67),
            excess_return_pct=np.float64(6.67),
            max_drawdown_pct=np.float64(-4.5),
            trades=np.int64(3),
            win_rate=np.float64(0.66),
            holdout_steps=np.int32(10),
            approved=np.bool_(True),
        )
        self.assertIs(type(m.approved), bool)
        self.assertIs(type(m.total_return_pct), float)
        self.assertIs(type(m.trades), int)
        # 실제 저장 경로 (json.dumps) 성공 여부까지 검증
        payload = {
            "approved": m.approved,
            "total_return_pct": m.total_return_pct,
            "trades": m.trades,
        }
        json.dumps(payload)  # 예외 안 나야 함


if __name__ == "__main__":
    unittest.main()
