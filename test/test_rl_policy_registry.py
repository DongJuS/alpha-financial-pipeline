from __future__ import annotations

"""
test/test_rl_policy_registry.py — PolicyRegistry 단위 테스트

테스트 항목:
- PolicyRegistry CRUD (등록, 조회, 활성 정책)
- 승격 게이트 (return_pct, max_drawdown, approved 조건)
- 자동 정리 (미승인 30일, 승인 5개 제한, 활성 보호)
- RLPolicyStoreV2 저장/로드
- 파일 경로 생성
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.agents.rl_policy_registry import (
    CleanupPolicy,
    PolicyEntry,
    PolicyRegistry,
    PromotionGate,
    TickerPolicies,
    algorithm_dir_name,
    build_relative_path,
)
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLEvaluationMetrics, RLPolicyArtifact


def _make_entry(
    policy_id: str,
    ticker: str = "259960.KS",
    return_pct: float = 10.0,
    max_drawdown_pct: float = -20.0,
    approved: bool = True,
    created_at: datetime | None = None,
    algorithm: str = "tabular_q_learning",
) -> PolicyEntry:
    """테스트용 PolicyEntry를 생성합니다."""
    return PolicyEntry(
        policy_id=policy_id,
        ticker=ticker,
        algorithm=algorithm,
        state_version="qlearn_v2",
        return_pct=return_pct,
        max_drawdown_pct=max_drawdown_pct,
        approved=approved,
        created_at=created_at or datetime.now(timezone.utc),
        file_path=build_relative_path(algorithm, ticker, policy_id),
    )


def _make_artifact(
    policy_id: str,
    ticker: str = "259960.KS",
    return_pct: float = 10.0,
    max_drawdown_pct: float = -20.0,
    approved: bool = True,
) -> RLPolicyArtifact:
    """테스트용 RLPolicyArtifact를 생성합니다."""
    return RLPolicyArtifact(
        policy_id=policy_id,
        ticker=ticker,
        created_at=datetime.now(timezone.utc).isoformat(),
        algorithm="tabular_q_learning",
        state_version="qlearn_v2",
        lookback=20,
        episodes=300,
        learning_rate=0.10,
        discount_factor=0.95,
        epsilon=0.30,
        trade_penalty_bps=2,
        q_table={"p0|s0|l0|m0|v0": {"BUY": 0.1, "SELL": -0.1, "HOLD": 0.0, "CLOSE": 0.0}},
        evaluation=RLEvaluationMetrics(
            total_return_pct=return_pct,
            baseline_return_pct=-10.0,
            excess_return_pct=return_pct + 10.0,
            max_drawdown_pct=max_drawdown_pct,
            trades=100,
            win_rate=0.52,
            holdout_steps=50,
            approved=approved,
        ),
    )


class TestAlgorithmDirName(unittest.TestCase):
    """algorithm_dir_name 함수 테스트."""

    def test_tabular(self):
        self.assertEqual(algorithm_dir_name("tabular_q_learning"), "tabular")

    def test_dqn(self):
        self.assertEqual(algorithm_dir_name("dqn"), "dqn")

    def test_ppo(self):
        self.assertEqual(algorithm_dir_name("ppo"), "ppo")

    def test_unknown(self):
        self.assertEqual(algorithm_dir_name("sac_v2"), "sac")


class TestBuildRelativePath(unittest.TestCase):
    """build_relative_path 함수 테스트."""

    def test_tabular_path(self):
        result = build_relative_path("tabular_q_learning", "259960.KS", "rl_259960.KS_test")
        self.assertEqual(result, "tabular/259960.KS/rl_259960.KS_test.json")

    def test_dqn_path(self):
        result = build_relative_path("dqn", "005930", "rl_005930_test")
        self.assertEqual(result, "dqn/005930/rl_005930_test.json")


class TestTickerPolicies(unittest.TestCase):
    """TickerPolicies 모델 테스트."""

    def test_add_and_get_policy(self):
        tp = TickerPolicies()
        entry = _make_entry("pol_1")
        tp.add_policy(entry)
        self.assertEqual(len(tp.policies), 1)
        self.assertEqual(tp.get_policy("pol_1"), entry)

    def test_add_duplicate_replaces(self):
        tp = TickerPolicies()
        entry1 = _make_entry("pol_1", return_pct=10.0)
        entry2 = _make_entry("pol_1", return_pct=20.0)
        tp.add_policy(entry1)
        tp.add_policy(entry2)
        self.assertEqual(len(tp.policies), 1)
        self.assertEqual(tp.policies[0].return_pct, 20.0)

    def test_remove_policy(self):
        tp = TickerPolicies()
        tp.add_policy(_make_entry("pol_1"))
        tp.add_policy(_make_entry("pol_2"))
        removed = tp.remove_policy("pol_1")
        self.assertIsNotNone(removed)
        self.assertEqual(len(tp.policies), 1)

    def test_remove_active_policy_blocked(self):
        tp = TickerPolicies()
        tp.add_policy(_make_entry("pol_1"))
        tp.active_policy_id = "pol_1"
        removed = tp.remove_policy("pol_1")
        self.assertIsNone(removed)
        self.assertEqual(len(tp.policies), 1)

    def test_get_active_policy(self):
        tp = TickerPolicies()
        entry = _make_entry("pol_1")
        tp.add_policy(entry)
        tp.active_policy_id = "pol_1"
        self.assertEqual(tp.get_active_policy(), entry)

    def test_get_active_policy_none(self):
        tp = TickerPolicies()
        self.assertIsNone(tp.get_active_policy())


class TestPolicyRegistry(unittest.TestCase):
    """PolicyRegistry 모델 테스트."""

    def test_register_policy(self):
        registry = PolicyRegistry()
        entry = _make_entry("pol_1")
        registry.register_policy(entry)
        self.assertEqual(registry.total_policy_count(), 1)
        self.assertEqual(registry.get_active_policy("259960.KS"), None)

    def test_promote_policy_approved(self):
        registry = PolicyRegistry()
        entry = _make_entry("pol_1", return_pct=20.0, approved=True)
        registry.register_policy(entry)
        success = registry.promote_policy("259960.KS", "pol_1")
        self.assertTrue(success)
        self.assertEqual(registry.get_active_policy("259960.KS"), entry)

    def test_promote_policy_unapproved_fails(self):
        registry = PolicyRegistry()
        entry = _make_entry("pol_1", return_pct=20.0, approved=False)
        registry.register_policy(entry)
        success = registry.promote_policy("259960.KS", "pol_1")
        self.assertFalse(success)

    def test_promote_policy_lower_return_fails(self):
        registry = PolicyRegistry()
        entry1 = _make_entry("pol_1", return_pct=30.0, approved=True)
        entry2 = _make_entry("pol_2", return_pct=20.0, approved=True)
        registry.register_policy(entry1)
        registry.promote_policy("259960.KS", "pol_1")
        registry.register_policy(entry2)
        success = registry.promote_policy("259960.KS", "pol_2")
        self.assertFalse(success)

    def test_promote_policy_higher_return_succeeds(self):
        registry = PolicyRegistry()
        entry1 = _make_entry("pol_1", return_pct=20.0, approved=True)
        entry2 = _make_entry("pol_2", return_pct=30.0, approved=True)
        registry.register_policy(entry1)
        registry.promote_policy("259960.KS", "pol_1")
        registry.register_policy(entry2)
        success = registry.promote_policy("259960.KS", "pol_2")
        self.assertTrue(success)

    def test_promote_policy_drawdown_too_deep_fails(self):
        registry = PolicyRegistry()
        entry = _make_entry("pol_1", return_pct=20.0, max_drawdown_pct=-60.0, approved=True)
        registry.register_policy(entry)
        success = registry.promote_policy("259960.KS", "pol_1")
        self.assertFalse(success)

    def test_force_promote(self):
        registry = PolicyRegistry()
        entry = _make_entry("pol_1", return_pct=2.0, approved=False)
        registry.register_policy(entry)
        success = registry.promote_policy("259960.KS", "pol_1", force=True)
        self.assertTrue(success)

    def test_list_all_tickers(self):
        registry = PolicyRegistry()
        registry.register_policy(_make_entry("pol_1", ticker="A"))
        registry.register_policy(_make_entry("pol_2", ticker="B"))
        self.assertEqual(sorted(registry.list_all_tickers()), ["A", "B"])


class TestRLPolicyStoreV2(unittest.TestCase):
    """RLPolicyStoreV2 저장/로드 테스트."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.store = RLPolicyStoreV2(models_dir=self.tmp_dir, auto_save_registry=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_load_policy(self):
        artifact = _make_artifact("pol_test_1")
        saved = self.store.save_policy(artifact)
        self.assertIsNotNone(saved.artifact_path)

        loaded = self.store.load_policy("pol_test_1", ticker="259960.KS")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.policy_id, "pol_test_1")

    def test_save_creates_correct_directory(self):
        artifact = _make_artifact("pol_test_dir")
        self.store.save_policy(artifact)
        expected = self.tmp_dir / "tabular" / "259960.KS" / "pol_test_dir.json"
        self.assertTrue(expected.exists())

    def test_registry_json_created(self):
        artifact = _make_artifact("pol_reg")
        self.store.save_policy(artifact)
        self.assertTrue((self.tmp_dir / "registry.json").exists())

    def test_activate_policy(self):
        artifact = _make_artifact("pol_act", return_pct=20.0, approved=True)
        self.store.save_policy(artifact)
        success = self.store.activate_policy(artifact)
        self.assertTrue(success)
        active = self.store.load_active_policy("259960.KS")
        self.assertIsNotNone(active)
        self.assertEqual(active.policy_id, "pol_act")

    def test_activate_unapproved_fails(self):
        artifact = _make_artifact("pol_unapp", return_pct=20.0, approved=False)
        self.store.save_policy(artifact)
        success = self.store.activate_policy(artifact)
        self.assertFalse(success)

    def test_list_active_policies(self):
        art1 = _make_artifact("pol_a1", return_pct=20.0, approved=True)
        self.store.save_policy(art1)
        self.store.activate_policy(art1)
        result = self.store.list_active_policies()
        self.assertEqual(result["259960.KS"], "pol_a1")

    def test_list_policies(self):
        self.store.save_policy(_make_artifact("p1"))
        self.store.save_policy(_make_artifact("p2"))
        entries = self.store.list_policies("259960.KS")
        self.assertEqual(len(entries), 2)


class TestCleanup(unittest.TestCase):
    """자동 정리 테스트."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.store = RLPolicyStoreV2(models_dir=self.tmp_dir, auto_save_registry=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_cleanup_old_unapproved(self):
        """30일 이상 된 미승인 정책이 삭제되는지 확인."""
        old = _make_artifact("pol_old", approved=False)
        self.store.save_policy(old)

        # 레지스트리의 created_at을 40일 전으로 조작
        registry = self.store.load_registry()
        tp = registry.get_ticker("259960.KS")
        tp.policies[0].created_at = datetime.now(timezone.utc) - timedelta(days=40)
        self.store.save_registry()

        # keep_latest_failed 때문에 최근 1개는 보존. 2개 넣고 1개 삭제 확인.
        old2 = _make_artifact("pol_old2", approved=False)
        self.store.save_policy(old2)
        registry = self.store.load_registry()
        tp = registry.get_ticker("259960.KS")
        for p in tp.policies:
            if p.policy_id == "pol_old2":
                p.created_at = datetime.now(timezone.utc) - timedelta(days=45)
        self.store.save_registry()

        removed = self.store.cleanup()
        self.assertEqual(len(removed), 1)
        self.assertIn("pol_old2", removed)

    def test_cleanup_preserves_active(self):
        """활성 정책은 삭제되지 않는지 확인."""
        art = _make_artifact("pol_active", return_pct=20.0, approved=True)
        self.store.save_policy(art)
        self.store.activate_policy(art)

        removed = self.store.cleanup()
        self.assertEqual(len(removed), 0)

    def test_cleanup_approved_excess(self):
        """승인 정책이 5개 초과 시 오래된 것부터 삭제되는지 확인."""
        # 활성 1개 + 승인 6개 = 초과분 2개 삭제 예상
        artifacts = []
        for i in range(7):
            art = _make_artifact(
                f"pol_app_{i}",
                return_pct=10.0 + i * 5,
                approved=True,
            )
            self.store.save_policy(art)
            artifacts.append(art)

        # 최고 수익 정책을 활성화
        self.store.activate_policy(artifacts[-1])

        # created_at을 i일 전으로 설정 (pol_app_0이 가장 오래됨)
        registry = self.store.load_registry()
        tp = registry.get_ticker("259960.KS")
        for j, p in enumerate(tp.policies):
            p.created_at = datetime.now(timezone.utc) - timedelta(days=j)
        self.store.save_registry()

        removed = self.store.cleanup()
        # 활성(1) + 최근 4개 보존 = 총 5개 보존, 2개 삭제
        self.assertEqual(len(removed), 2)


class TestRegistrySerialization(unittest.TestCase):
    """registry.json 직렬화/역직렬화 테스트."""

    def test_roundtrip(self):
        registry = PolicyRegistry()
        entry = _make_entry("pol_ser")
        registry.register_policy(entry)
        registry.promote_policy("259960.KS", "pol_ser")

        # 직렬화
        payload = registry.model_dump(mode="json")
        json_str = json.dumps(payload, default=str)

        # 역직렬화
        loaded = PolicyRegistry.model_validate(json.loads(json_str))
        self.assertEqual(loaded.total_policy_count(), 1)
        self.assertEqual(loaded.get_active_policy("259960.KS").policy_id, "pol_ser")


if __name__ == "__main__":
    unittest.main()
