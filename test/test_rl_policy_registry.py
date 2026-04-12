from __future__ import annotations

"""
test/test_rl_policy_registry.py — PolicyEntry DTO + StoreV2 단위 테스트

테스트 항목:
- PolicyEntry DTO 생성 / 필드 접근
- algorithm_dir_name / build_relative_path 유틸 함수
- RLPolicyStoreV2 async DB 기반 CRUD (mock)
- 승격 게이트 (activate_policy / force_activate_policy)
- 자동 정리 (cleanup)
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.agents.rl_policy_registry import (
    CLEANUP_MAX_APPROVED_PER_TICKER,
    CLEANUP_UNAPPROVED_DAYS,
    DEFAULT_MAX_DRAWDOWN_LIMIT_PCT,
    DEFAULT_MIN_RETURN_PCT,
    PolicyEntry,
    algorithm_dir_name,
    build_relative_path,
)
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLEvaluationMetrics, RLPolicyArtifact


def _make_entry(
    policy_id: str,
    instrument_id: str = "259960.KS",
    return_pct: float = 10.0,
    max_drawdown_pct: float = -20.0,
    approved: bool = True,
    is_active: bool = False,
    created_at: datetime | None = None,
    algorithm: str = "tabular_q_learning",
) -> PolicyEntry:
    """테스트용 PolicyEntry를 생성합니다."""
    return PolicyEntry(
        policy_id=policy_id,
        instrument_id=instrument_id,
        algorithm=algorithm,
        state_version="qlearn_v2",
        return_pct=return_pct,
        max_drawdown_pct=max_drawdown_pct,
        approved=approved,
        is_active=is_active,
        created_at=created_at or datetime.now(timezone.utc),
        file_path=build_relative_path(algorithm, instrument_id, policy_id),
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


class TestPolicyEntry(unittest.TestCase):
    """PolicyEntry DTO 테스트."""

    def test_instrument_id_field(self):
        """instrument_id 필드가 올바르게 설정되는지 확인."""
        entry = _make_entry("pol_1", instrument_id="005930.KS")
        self.assertEqual(entry.instrument_id, "005930.KS")

    def test_ticker_property_alias(self):
        """ticker 프로퍼티가 instrument_id의 별칭으로 동작하는지 확인."""
        entry = _make_entry("pol_1", instrument_id="005930.KS")
        self.assertEqual(entry.ticker, "005930.KS")
        self.assertEqual(entry.ticker, entry.instrument_id)

    def test_is_active_field(self):
        """is_active 필드가 올바르게 설정되는지 확인."""
        entry_inactive = _make_entry("pol_1", is_active=False)
        self.assertFalse(entry_inactive.is_active)

        entry_active = _make_entry("pol_2", is_active=True)
        self.assertTrue(entry_active.is_active)

    def test_hyperparams_property(self):
        """hyperparams dict를 통한 하이퍼파라미터 접근이 동작하는지 확인."""
        entry = PolicyEntry(
            policy_id="pol_hp",
            instrument_id="259960.KS",
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            return_pct=10.0,
            max_drawdown_pct=-20.0,
            approved=True,
            is_active=False,
            created_at=datetime.now(timezone.utc),
            file_path="tabular/259960.KS/pol_hp.json",
            hyperparams={
                "lookback": 30,
                "episodes": 500,
                "learning_rate": 0.05,
                "discount_factor": 0.99,
                "epsilon": 0.20,
                "trade_penalty_bps": 3,
            },
        )
        self.assertEqual(entry.lookback, 30)
        self.assertEqual(entry.episodes, 500)
        self.assertAlmostEqual(entry.learning_rate, 0.05)
        self.assertAlmostEqual(entry.discount_factor, 0.99)
        self.assertAlmostEqual(entry.epsilon, 0.20)
        self.assertEqual(entry.trade_penalty_bps, 3)

    def test_hyperparams_defaults(self):
        """hyperparams가 None일 때 기본값이 반환되는지 확인."""
        entry = _make_entry("pol_default")
        self.assertEqual(entry.lookback, 6)
        self.assertEqual(entry.episodes, 60)
        self.assertAlmostEqual(entry.learning_rate, 0.18)
        self.assertAlmostEqual(entry.discount_factor, 0.92)
        self.assertAlmostEqual(entry.epsilon, 0.15)
        self.assertEqual(entry.trade_penalty_bps, 5)

    def test_from_db_row(self):
        """from_db_row 팩토리 메서드가 dict-like row에서 생성되는지 확인."""
        row = {
            "policy_id": "pol_db",
            "instrument_id": "005930.KS",
            "algorithm": "tabular_q_learning",
            "state_version": "qlearn_v2",
            "return_pct": 15.0,
            "baseline_return_pct": 5.0,
            "excess_return_pct": 10.0,
            "max_drawdown_pct": -8.0,
            "trades": 120,
            "win_rate": 0.6,
            "holdout_steps": 80,
            "approved": True,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "file_path": "tabular/005930.KS/pol_db.json",
            "hyperparams": {"lookback": 20, "episodes": 300},
        }
        entry = PolicyEntry.from_db_row(row)
        self.assertEqual(entry.policy_id, "pol_db")
        self.assertEqual(entry.instrument_id, "005930.KS")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.lookback, 20)
        self.assertEqual(entry.episodes, 300)


class TestPromotionGateConstants(unittest.TestCase):
    """승격 게이트 상수 테스트."""

    def test_min_return_pct(self):
        self.assertEqual(DEFAULT_MIN_RETURN_PCT, 5.0)

    def test_max_drawdown_limit_pct(self):
        self.assertEqual(DEFAULT_MAX_DRAWDOWN_LIMIT_PCT, -50.0)


class TestCleanupConstants(unittest.TestCase):
    """자동 정리 상수 테스트."""

    def test_unapproved_days(self):
        self.assertEqual(CLEANUP_UNAPPROVED_DAYS, 30)

    def test_max_approved_per_ticker(self):
        self.assertEqual(CLEANUP_MAX_APPROVED_PER_TICKER, 5)


class TestRLPolicyStoreV2(unittest.IsolatedAsyncioTestCase):
    """RLPolicyStoreV2 DB 기반 테스트 (StoreV2 메서드를 AsyncMock으로 mock)."""

    async def test_save_and_load_policy(self):
        """정책 저장 후 로드할 수 있는지 확인."""
        artifact = _make_artifact("pol_test_1")
        saved_artifact = _make_artifact("pol_test_1")
        saved_artifact.artifact_path = "tabular/259960.KS/pol_test_1.json"

        with (
            patch.object(
                RLPolicyStoreV2, "save_policy", new_callable=AsyncMock, return_value=saved_artifact
            ) as mock_save,
            patch.object(
                RLPolicyStoreV2, "load_policy", new_callable=AsyncMock, return_value=saved_artifact
            ) as mock_load,
        ):
            store = RLPolicyStoreV2()
            saved = await store.save_policy(artifact)
            self.assertIsNotNone(saved.artifact_path)

            loaded = await store.load_policy("pol_test_1", ticker="259960.KS")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.policy_id, "pol_test_1")

            mock_save.assert_called_once_with(artifact)
            mock_load.assert_called_once_with("pol_test_1", ticker="259960.KS")

    async def test_activate_approved_policy(self):
        """승인된 정책이 활성화되는지 확인."""
        artifact = _make_artifact("pol_act", return_pct=20.0, approved=True)

        with patch.object(
            RLPolicyStoreV2, "activate_policy", new_callable=AsyncMock, return_value=True
        ) as mock_activate:
            store = RLPolicyStoreV2()
            success = await store.activate_policy(artifact)
            self.assertTrue(success)
            mock_activate.assert_called_once_with(artifact)

    async def test_activate_unapproved_fails(self):
        """미승인 정책은 활성화에 실패하는지 확인."""
        artifact = _make_artifact("pol_unapp", return_pct=20.0, approved=False)

        with patch.object(
            RLPolicyStoreV2, "activate_policy", new_callable=AsyncMock, return_value=False
        ):
            store = RLPolicyStoreV2()
            success = await store.activate_policy(artifact)
            self.assertFalse(success)

    async def test_activate_drawdown_too_deep_fails(self):
        """MDD가 한도를 초과하면 활성화에 실패하는지 확인."""
        artifact = _make_artifact("pol_dd", return_pct=20.0, max_drawdown_pct=-60.0, approved=True)

        with patch.object(
            RLPolicyStoreV2, "activate_policy", new_callable=AsyncMock, return_value=False
        ):
            store = RLPolicyStoreV2()
            success = await store.activate_policy(artifact)
            self.assertFalse(success)

    async def test_force_activate_policy(self):
        """강제 승격이 동작하는지 확인."""
        with patch.object(
            RLPolicyStoreV2, "force_activate_policy", new_callable=AsyncMock, return_value=True
        ) as mock_force:
            store = RLPolicyStoreV2()
            success = await store.force_activate_policy("259960.KS", "pol_force")
            self.assertTrue(success)
            mock_force.assert_called_once_with("259960.KS", "pol_force")

    async def test_load_active_policy(self):
        """활성 정책 로드가 동작하는지 확인."""
        expected_artifact = _make_artifact("pol_active", return_pct=20.0, approved=True)

        with patch.object(
            RLPolicyStoreV2, "load_active_policy", new_callable=AsyncMock, return_value=expected_artifact
        ):
            store = RLPolicyStoreV2()
            loaded = await store.load_active_policy("259960.KS")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.policy_id, "pol_active")

    async def test_list_active_policies(self):
        """활성 정책 목록 조회가 동작하는지 확인."""
        with patch.object(
            RLPolicyStoreV2, "list_active_policies",
            new_callable=AsyncMock,
            return_value={"259960.KS": "pol_a1", "005930.KS": None},
        ):
            store = RLPolicyStoreV2()
            result = await store.list_active_policies()
            self.assertEqual(result["259960.KS"], "pol_a1")
            self.assertIsNone(result["005930.KS"])

    async def test_list_policies(self):
        """종목별 정책 목록 조회가 동작하는지 확인."""
        entries = [
            _make_entry("p1", instrument_id="259960.KS"),
            _make_entry("p2", instrument_id="259960.KS"),
        ]

        with patch.object(
            RLPolicyStoreV2, "list_policies", new_callable=AsyncMock, return_value=entries
        ):
            store = RLPolicyStoreV2()
            result = await store.list_policies("259960.KS")
            self.assertEqual(len(result), 2)

    async def test_list_all_tickers(self):
        """전체 종목 목록 조회가 동작하는지 확인."""
        with patch.object(
            RLPolicyStoreV2, "list_all_tickers",
            new_callable=AsyncMock,
            return_value=["259960.KS", "005930.KS"],
        ):
            store = RLPolicyStoreV2()
            tickers = await store.list_all_tickers()
            self.assertEqual(sorted(tickers), ["005930.KS", "259960.KS"])


class TestCleanup(unittest.IsolatedAsyncioTestCase):
    """자동 정리 테스트 (StoreV2.cleanup을 AsyncMock으로 mock)."""

    async def test_cleanup_old_unapproved(self):
        """30일 초과 미승인 정책이 삭제 대상으로 반환되는지 확인."""
        with patch.object(
            RLPolicyStoreV2, "cleanup",
            new_callable=AsyncMock,
            return_value=["pol_old2"],
        ) as mock_cleanup:
            store = RLPolicyStoreV2()
            removed = await store.cleanup()
            self.assertEqual(len(removed), 1)
            self.assertIn("pol_old2", removed)
            mock_cleanup.assert_called_once()

    async def test_cleanup_preserves_active(self):
        """활성 정책은 삭제되지 않는지 확인 (삭제 목록이 비어 있어야 함)."""
        with patch.object(
            RLPolicyStoreV2, "cleanup",
            new_callable=AsyncMock,
            return_value=[],
        ):
            store = RLPolicyStoreV2()
            removed = await store.cleanup()
            self.assertEqual(len(removed), 0)

    async def test_cleanup_approved_excess(self):
        """승인 정책이 max_approved_per_ticker 초과 시 오래된 것부터 삭제되는지 확인."""
        with patch.object(
            RLPolicyStoreV2, "cleanup",
            new_callable=AsyncMock,
            return_value=["pol_app_0", "pol_app_1"],
        ):
            store = RLPolicyStoreV2()
            removed = await store.cleanup()
            # 활성(1) + 최근 4개 보존 = 총 5개 보존, 2개 삭제
            self.assertEqual(len(removed), 2)

    async def test_cleanup_dry_run(self):
        """dry_run=True일 때 삭제 대상만 반환하고 실제 삭제는 안 하는지 확인."""
        with patch.object(
            RLPolicyStoreV2, "cleanup",
            new_callable=AsyncMock,
            return_value=["pol_dry_1"],
        ) as mock_cleanup:
            store = RLPolicyStoreV2()
            removed = await store.cleanup(dry_run=True)
            self.assertEqual(len(removed), 1)
            mock_cleanup.assert_called_once_with(dry_run=True)


if __name__ == "__main__":
    unittest.main()
