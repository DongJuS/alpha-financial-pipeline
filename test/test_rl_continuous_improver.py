from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.agents.rl_continuous_improver import RLContinuousImprover
from src.agents.rl_experiment_manager import RLExperimentManager
from src.agents.rl_trading import (
    RLDataset,
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLSplitMetadata,
)
from src.agents.rl_walk_forward import WalkForwardResult


class StubDatasetBuilder:
    async def build_dataset(self, ticker: str, days: int = 180) -> RLDataset:
        closes = [100.0 + idx for idx in range(120)]
        timestamps = [f"2026-01-{(idx % 28) + 1:02d}" for idx in range(120)]
        return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


class StubTrainer:
    def __init__(
        self,
        *,
        profile_id: str,
        state_version: str,
        total_return_pct: float,
        excess_return_pct: float,
        approved: bool,
    ) -> None:
        self.profile_id = profile_id
        self.state_version = state_version
        self.total_return_pct = total_return_pct
        self.excess_return_pct = excess_return_pct
        self.approved = approved

        # create_run()이 trainer attribute를 읽습니다.
        self.lookback = 20 if state_version.endswith("v2") else 6
        self.episodes = 300 if state_version.endswith("v2") else 60
        self.learning_rate = 0.10 if state_version.endswith("v2") else 0.18
        self.discount_factor = 0.95 if state_version.endswith("v2") else 0.92
        self.epsilon = 0.30 if state_version.endswith("v2") else 0.15
        self.trade_penalty_bps = 2 if state_version.endswith("v2") else 5

    def train_with_metadata(
        self,
        dataset: RLDataset,
        *,
        train_ratio: float = 0.7,
        **kwargs,
    ) -> tuple[RLPolicyArtifact, RLSplitMetadata]:
        return self.train(dataset), RLSplitMetadata(
            train_ratio=train_ratio,
            train_size=int(len(dataset.closes) * train_ratio),
            test_size=len(dataset.closes) - int(len(dataset.closes) * train_ratio),
            train_start=dataset.timestamps[0],
            train_end=dataset.timestamps[int(len(dataset.closes) * train_ratio) - 1],
            test_start=dataset.timestamps[int(len(dataset.closes) * train_ratio)],
            test_end=dataset.timestamps[-1],
        )

    def train(self, dataset: RLDataset) -> RLPolicyArtifact:
        created_at = datetime.now(timezone.utc).isoformat()
        return RLPolicyArtifact(
            policy_id=f"{self.profile_id}_{dataset.ticker}",
            ticker=dataset.ticker,
            created_at=created_at,
            algorithm="tabular_q_learning",
            state_version=self.state_version,
            lookback=self.lookback,
            episodes=self.episodes,
            learning_rate=self.learning_rate,
            discount_factor=self.discount_factor,
            epsilon=self.epsilon,
            trade_penalty_bps=self.trade_penalty_bps,
            q_table={"state": {"BUY": 1.0, "SELL": 0.0, "HOLD": 0.0, "CLOSE": 0.0}},
            evaluation=RLEvaluationMetrics(
                total_return_pct=self.total_return_pct,
                baseline_return_pct=2.0,
                excess_return_pct=self.excess_return_pct,
                max_drawdown_pct=-10.0,
                trades=12,
                win_rate=0.58,
                holdout_steps=24,
                approved=self.approved,
            ),
        )

    def evaluate(
        self,
        prices: list[float],
        q_table: dict[str, dict[str, float]],
    ) -> RLEvaluationMetrics:
        return RLEvaluationMetrics(
            total_return_pct=max(0.0, self.total_return_pct / 2.0),
            baseline_return_pct=1.0,
            excess_return_pct=max(0.0, self.excess_return_pct / 2.0),
            max_drawdown_pct=-10.0,
            trades=8,
            win_rate=0.55,
            holdout_steps=max(0, len(prices) - 21),
            approved=True,
        )


def _walk_forward_result(
    *,
    approved: bool,
    consistency: float,
) -> WalkForwardResult:
    return WalkForwardResult(
        n_folds=5,
        total_data_points=120,
        folds=[],
        consistency_score=consistency,
        overall_approved=approved,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _write_profile(root: Path, profile_id: str, state_version: str) -> None:
    profiles_dir = root / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile_id": profile_id,
        "algorithm": "tabular_q_learning",
        "state_version": state_version,
        "trainer_params": {"lookback": 20 if state_version.endswith("v2") else 6},
        "dataset": {"default_train_ratio": 0.7, "min_history_points": 40},
        "evaluation": {"min_approval_return_pct": 5.0},
    }
    (profiles_dir / f"{profile_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _active_artifact(policy_id: str, ticker: str) -> RLPolicyArtifact:
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
        q_table={"state": {"BUY": 0.2, "SELL": 0.0, "HOLD": 0.0, "CLOSE": 0.0}},
        evaluation=RLEvaluationMetrics(
            total_return_pct=5.0,
            baseline_return_pct=1.0,
            excess_return_pct=4.0,
            max_drawdown_pct=-12.0,
            trades=8,
            win_rate=0.50,
            holdout_steps=20,
            approved=True,
        ),
    )


class RLContinuousImproverTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        _write_profile(self.root, "tabular_q_v2_momentum", "qlearn_v2")
        _write_profile(self.root, "tabular_q_v1_baseline", "qlearn_v1")

        self.store = MagicMock()
        self.store.save_policy = AsyncMock(side_effect=lambda a: a)
        self.store.activate_policy = AsyncMock(return_value=True)
        self.store.force_activate_policy = AsyncMock(return_value=True)
        self.store.list_active_policies = AsyncMock(return_value={})
        self.store.list_all_tickers = AsyncMock(return_value=[])
        self.store.list_policies = AsyncMock(return_value=[])
        self.exp_mgr = RLExperimentManager(artifacts_dir=self.root)
        self.builder = StubDatasetBuilder()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_retrain_ticker_promotes_best_approved_candidate(self) -> None:
        # list_active_policies: 첫 호출=before(기존 활성), 둘째=after(새 활성)
        self.store.list_active_policies = AsyncMock(side_effect=[
            {"005930.KS": "active_old"},
            {"005930.KS": "tabular_q_v2_momentum_005930.KS"},
        ])

        improver = RLContinuousImprover(
            dataset_builder=self.builder,
            experiment_manager=self.exp_mgr,
            policy_store=self.store,
        )
        trainers = {
            "tabular_q_v2_momentum": StubTrainer(
                profile_id="tabular_q_v2_momentum",
                state_version="qlearn_v2",
                total_return_pct=14.0,
                excess_return_pct=12.0,
                approved=True,
            ),
            "tabular_q_v1_baseline": StubTrainer(
                profile_id="tabular_q_v1_baseline",
                state_version="qlearn_v1",
                total_return_pct=9.0,
                excess_return_pct=7.0,
                approved=True,
            ),
        }
        improver._trainer_for_profile = lambda profile: trainers[profile["profile_id"]]  # type: ignore[method-assign]
        improver._run_walk_forward = lambda dataset, trainer: _walk_forward_result(  # type: ignore[method-assign]
            approved=True,
            consistency=0.81 if trainer.profile_id.endswith("v2_momentum") else 0.72,
        )

        outcome = await improver.retrain_ticker("005930.KS")

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.profile_id, "tabular_q_v2_momentum")
        self.assertEqual(outcome.new_policy_id, "tabular_q_v2_momentum_005930.KS")
        self.assertTrue(outcome.walk_forward_passed)
        self.assertTrue(outcome.deployed)
        self.assertEqual(outcome.active_policy_before, "active_old")
        self.assertEqual(outcome.active_policy_after, "tabular_q_v2_momentum_005930.KS")

    async def test_retrain_ticker_keeps_policy_inactive_when_walk_forward_fails(self) -> None:
        improver = RLContinuousImprover(
            dataset_builder=self.builder,
            experiment_manager=self.exp_mgr,
            policy_store=self.store,
        )
        trainers = {
            "tabular_q_v2_momentum": StubTrainer(
                profile_id="tabular_q_v2_momentum",
                state_version="qlearn_v2",
                total_return_pct=11.0,
                excess_return_pct=9.0,
                approved=True,
            ),
            "tabular_q_v1_baseline": StubTrainer(
                profile_id="tabular_q_v1_baseline",
                state_version="qlearn_v1",
                total_return_pct=8.0,
                excess_return_pct=6.0,
                approved=True,
            ),
        }
        improver._trainer_for_profile = lambda profile: trainers[profile["profile_id"]]  # type: ignore[method-assign]
        improver._run_walk_forward = lambda dataset, trainer: _walk_forward_result(  # type: ignore[method-assign]
            approved=False,
            consistency=0.42,
        )

        outcome = await improver.retrain_ticker("000660.KS")

        self.assertTrue(outcome.success)
        self.assertFalse(outcome.walk_forward_passed)
        self.assertFalse(outcome.deployed)
        self.assertIsNone(outcome.active_policy_after)

