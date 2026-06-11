"""test/test_rl_policy_interface.py — 공통 RL 정책 인터페이스 단위 테스트"""

import unittest

from src.agents.rl_policy_interface import (
    PolicyDecision,
    RLPolicy,
    TabularRLPolicy,
    policy_from_artifact,
)
from src.agents.rl_trading import RLPolicyArtifact
from src.agents.rl_trading_v2 import TabularQTrainerV2

_EVAL = {
    "total_return_pct": 0.0, "baseline_return_pct": 0.0, "excess_return_pct": 0.0,
    "max_drawdown_pct": 0.0, "trades": 0, "win_rate": 0.0, "holdout_steps": 0,
    "approved": True,
}


def _tabular_artifact(q_table=None, algorithm="tabular_q_learning") -> RLPolicyArtifact:
    payload = {
        "policy_id": "test-policy", "ticker": "005930.KS", "created_at": "2026-06-12",
        "algorithm": algorithm, "state_version": "qlearn_v1", "lookback": 6,
        "episodes": 60, "learning_rate": 0.18, "discount_factor": 0.92,
        "epsilon": 0.15, "trade_penalty_bps": 5, "evaluation": _EVAL,
    }
    if q_table is not None:
        payload["q_table"] = q_table
    return RLPolicyArtifact.from_dict(payload)


class TabularPolicyAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.closes = [100.0 + (i % 7) - 3 for i in range(30)]
        self.artifact = _tabular_artifact(q_table={})
        self.trainer = TabularQTrainerV2(lookback=6)

    def test_adapter_matches_direct_inference(self) -> None:
        direct_action, direct_conf, direct_state, _q = self.trainer.infer_action(
            self.artifact, self.closes, current_position=0
        )
        policy = TabularRLPolicy(self.artifact, trainer=self.trainer)
        decision = policy.act(self.closes, position=0)
        self.assertIsInstance(decision, PolicyDecision)
        self.assertEqual(decision.action, direct_action)
        self.assertAlmostEqual(decision.confidence, direct_conf)
        self.assertEqual(decision.meta["state"], direct_state)
        self.assertIn(decision.action, ("BUY", "SELL", "HOLD"))

    def test_features_arg_accepted_and_ignored(self) -> None:
        policy = TabularRLPolicy(self.artifact, trainer=self.trainer)
        a = policy.act(self.closes, position=0)
        b = policy.act(self.closes, position=0, features=[[0.1, 0.2, 0.0, 0.0, 0.0, 1.0]] * 30)
        self.assertEqual(a.action, b.action)  # tabular 은 features 무시 → 동일

    def test_satisfies_protocol(self) -> None:
        policy = TabularRLPolicy(self.artifact, trainer=self.trainer)
        self.assertIsInstance(policy, RLPolicy)  # runtime_checkable Protocol

    def test_missing_qtable_raises(self) -> None:
        with self.assertRaises(ValueError):
            TabularRLPolicy(_tabular_artifact(q_table=None))


class PolicyFactoryTest(unittest.TestCase):
    def test_factory_returns_tabular(self) -> None:
        policy = policy_from_artifact(_tabular_artifact(q_table={}))
        self.assertIsInstance(policy, TabularRLPolicy)
        self.assertEqual(policy.algorithm, "tabular_q_learning")

    def test_factory_unsupported_algorithm_raises(self) -> None:
        # q_table 없고 algorithm 이 미지원 → ValueError
        art = _tabular_artifact(q_table=None, algorithm="dreamer_v3")
        with self.assertRaises(ValueError):
            policy_from_artifact(art)


if __name__ == "__main__":
    unittest.main()
