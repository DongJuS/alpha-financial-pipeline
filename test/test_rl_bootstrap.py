"""
test/test_rl_bootstrap.py — RL 부트스트랩 파이프라인 테스트

DB/FDR 의존 없이 mock으로 부트스트랩 전체 흐름을 검증합니다.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.rl_continuous_improver import RLContinuousImprover, RetrainOutcome
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLDataset, RLEvaluationMetrics, RLPolicyArtifact


def _make_dataset(ticker: str, length: int = 200) -> RLDataset:
    """테스트용 더미 데이터셋 생성."""
    closes = [100.0 + i * 0.5 for i in range(length)]
    timestamps = [f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(length)]
    return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


def _make_artifact(
    ticker: str,
    policy_id: str,
    approved: bool = True,
    total_return_pct: float = 10.0,
) -> RLPolicyArtifact:
    """테스트용 더미 아티팩트 생성."""
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
            total_return_pct=total_return_pct,
            baseline_return_pct=5.0,
            excess_return_pct=total_return_pct - 5.0,
            max_drawdown_pct=-10.0,
            trades=50,
            win_rate=0.55,
            holdout_steps=100,
            approved=approved,
        ),
    )


class TestSeedFdrHistory(unittest.IsolatedAsyncioTestCase):
    """seed_fdr_history 단위 테스트."""

    async def test_skip_when_db_has_enough_data(self):
        """DB에 데이터가 충분하면 시딩을 스킵합니다."""
        from scripts.rl_bootstrap import seed_fdr_history

        mock_rows = [{"close": 100 + i, "timestamp_kst": f"2024-01-{i+1:02d}"} for i in range(500)]

        with patch("scripts.rl_bootstrap.fetch_recent_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_rows
            result = await seed_fdr_history("005930", days=720)

        self.assertTrue(result.success)
        self.assertEqual(result.source, "db_existing")
        self.assertEqual(result.rows, 500)

    async def test_seed_via_fdr_fallback(self):
        """DB 데이터 부족 시 FDR 폴백으로 시딩합니다."""
        from scripts.rl_bootstrap import seed_fdr_history

        dataset = _make_dataset("005930", length=500)

        with (
            patch("scripts.rl_bootstrap.fetch_recent_market_data", new_callable=AsyncMock) as mock_fetch,
            patch.object(
                RLDataset, "__init__", return_value=None,
            ),
        ):
            mock_fetch.return_value = []  # DB 비어있음

            mock_builder = AsyncMock()
            mock_builder.build_dataset.return_value = dataset

            with patch("scripts.rl_bootstrap.RLDatasetBuilder", return_value=mock_builder):
                result = await seed_fdr_history("005930", days=720)

        self.assertTrue(result.success)
        self.assertEqual(result.rows, 500)

    async def test_seed_failure_returns_error(self):
        """시딩 실패 시 에러 결과를 반환합니다."""
        from scripts.rl_bootstrap import seed_fdr_history

        with (
            patch("scripts.rl_bootstrap.fetch_recent_market_data", new_callable=AsyncMock) as mock_fetch,
            patch("scripts.rl_bootstrap.RLDatasetBuilder") as mock_builder_cls,
        ):
            mock_fetch.return_value = []
            mock_builder = AsyncMock()
            mock_builder.build_dataset.side_effect = ValueError("데이터 부족")
            mock_builder_cls.return_value = mock_builder

            result = await seed_fdr_history("005930", days=720)

        self.assertFalse(result.success)
        self.assertIn("데이터 부족", result.error)


class TestBootstrapTicker(unittest.IsolatedAsyncioTestCase):
    """bootstrap_ticker 통합 테스트."""

    async def test_full_bootstrap_with_activation(self):
        """시딩 → 학습 → 활성화 전체 흐름을 검증합니다."""
        from scripts.rl_bootstrap import bootstrap_ticker

        dataset = _make_dataset("005930", length=500)

        mock_retrain_outcome = RetrainOutcome(
            ticker="005930",
            success=True,
            new_policy_id="rl_005930_test",
            profile_id="tabular_q_v2_momentum",
            excess_return=15.0,
            walk_forward_passed=True,
            walk_forward_consistency=0.8,
            deployed=True,
            active_policy_before=None,
            active_policy_after="rl_005930_test",
        )

        with (
            patch("scripts.rl_bootstrap.fetch_recent_market_data", new_callable=AsyncMock) as mock_fetch,
            patch("scripts.rl_bootstrap.RLDatasetBuilder") as mock_builder_cls,
            patch.object(RLContinuousImprover, "retrain_ticker", new_callable=AsyncMock) as mock_retrain,
        ):
            mock_fetch.return_value = [{"close": 100 + i, "timestamp_kst": f"t{i}"} for i in range(500)]
            mock_builder = AsyncMock()
            mock_builder.build_dataset.return_value = dataset
            mock_builder_cls.return_value = mock_builder
            mock_retrain.return_value = mock_retrain_outcome

            result = await bootstrap_ticker("005930", seed_days=720, train_days=720)

        self.assertIsNotNone(result.seed)
        self.assertTrue(result.seed.success)
        self.assertIsNotNone(result.retrain)
        self.assertTrue(result.retrain.success)
        self.assertTrue(result.retrain.deployed)
        self.assertEqual(result.retrain.active_policy_after, "rl_005930_test")

    async def test_seed_only_skips_training(self):
        """--seed-only 모드에서는 학습을 스킵합니다."""
        from scripts.rl_bootstrap import bootstrap_ticker

        with (
            patch("scripts.rl_bootstrap.fetch_recent_market_data", new_callable=AsyncMock) as mock_fetch,
            patch("scripts.rl_bootstrap.RLDatasetBuilder") as mock_builder_cls,
        ):
            mock_fetch.return_value = [{"close": 100 + i, "timestamp_kst": f"t{i}"} for i in range(500)]
            mock_builder = AsyncMock()
            mock_builder.build_dataset.return_value = _make_dataset("005930")
            mock_builder_cls.return_value = mock_builder

            result = await bootstrap_ticker("005930", seed_only=True)

        self.assertIsNotNone(result.seed)
        self.assertTrue(result.seed.success)
        self.assertIsNone(result.retrain)

    async def test_train_only_skips_seeding(self):
        """--train-only 모드에서는 시딩을 스킵합니다."""
        from scripts.rl_bootstrap import bootstrap_ticker

        mock_outcome = RetrainOutcome(
            ticker="005930", success=True, deployed=False,
            new_policy_id="test_policy",
        )

        with patch.object(
            RLContinuousImprover, "retrain_ticker", new_callable=AsyncMock
        ) as mock_retrain:
            mock_retrain.return_value = mock_outcome
            result = await bootstrap_ticker("005930", train_only=True)

        self.assertIsNone(result.seed)
        self.assertIsNotNone(result.retrain)
        self.assertTrue(result.retrain.success)

    async def test_force_promote_activates_unapproved_policy(self):
        """--force-promote 시 승격 게이트 미통과 정책도 강제 활성화합니다."""
        from scripts.rl_bootstrap import bootstrap_ticker

        mock_outcome = RetrainOutcome(
            ticker="005930",
            success=True,
            new_policy_id="rl_005930_force",
            profile_id="tabular_q_v2_momentum",
            deployed=False,  # 승격 게이트 미통과
        )

        with (
            patch("scripts.rl_bootstrap.fetch_recent_market_data", new_callable=AsyncMock) as mock_fetch,
            patch("scripts.rl_bootstrap.RLDatasetBuilder") as mock_builder_cls,
            patch.object(RLContinuousImprover, "retrain_ticker", new_callable=AsyncMock) as mock_retrain,
            patch.object(RLPolicyStoreV2, "force_activate_policy", return_value=True) as mock_force,
        ):
            mock_fetch.return_value = [{"close": 100 + i, "timestamp_kst": f"t{i}"} for i in range(500)]
            mock_builder = AsyncMock()
            mock_builder.build_dataset.return_value = _make_dataset("005930")
            mock_builder_cls.return_value = mock_builder
            mock_retrain.return_value = mock_outcome

            result = await bootstrap_ticker(
                "005930", force_promote=True, seed_days=720,
            )

        self.assertTrue(result.retrain.deployed)
        mock_force.assert_called_once_with("005930", "rl_005930_force")


class TestBuildReport(unittest.TestCase):
    """리포트 생성 테스트."""

    def test_report_counts(self):
        """리포트 집계가 정확한지 검증합니다."""
        from scripts.rl_bootstrap import BootstrapResult, SeedResult, _build_report

        results = [
            BootstrapResult(
                ticker="005930",
                seed=SeedResult(ticker="005930", success=True, rows=500),
                retrain=RetrainOutcome(
                    ticker="005930", success=True, deployed=True,
                    new_policy_id="p1",
                ),
            ),
            BootstrapResult(
                ticker="000660",
                seed=SeedResult(ticker="000660", success=True, rows=300),
                retrain=RetrainOutcome(
                    ticker="000660", success=True, deployed=False,
                    new_policy_id="p2",
                ),
            ),
            BootstrapResult(
                ticker="259960",
                seed=SeedResult(ticker="259960", success=False, error="FDR 실패"),
            ),
        ]

        report = _build_report(results)

        self.assertEqual(report["total_tickers"], 3)
        self.assertEqual(report["seed_success"], 2)
        self.assertEqual(report["seed_failed"], 1)
        self.assertEqual(report["train_success"], 2)
        self.assertEqual(report["train_failed"], 0)
        self.assertEqual(report["policies_activated"], 1)


if __name__ == "__main__":
    unittest.main()
