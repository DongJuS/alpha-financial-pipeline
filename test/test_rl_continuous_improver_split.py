"""RLContinuousImprover ↔ RLSplitBandit 통합 테스트.

bandit이 고른 ratio가 trainer에 전달되는지, 결과로 bandit이 업데이트되는지,
outcome이 selected_train_ratio/snapshot을 노출하는지, 반복 호출 시 수렴하는지,
profile override가 반영되는지, bandit 실패 시 fallback 동작을 검증한다.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.rl_continuous_improver import (
    RLContinuousImprover,
)
from src.agents.rl_split_bandit import DEFAULT_RATIOS, RLSplitBandit, reward_from_walk_forward
from src.agents.rl_trading import (
    RLDataset,
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLSplitMetadata,
)
from src.agents.rl_walk_forward import WalkForwardResult


# ── Fakes ────────────────────────────────────────────────────────────────


class FakeBandit:
    """RLSplitBandit 인터페이스 부분 구현 stub."""

    def __init__(
        self,
        *,
        fixed_ratio: float | None = None,
        raise_on_select: bool = False,
        reward_fn=None,
    ) -> None:
        self._fixed_ratio = fixed_ratio
        self._raise_on_select = raise_on_select
        self._reward_fn = reward_fn
        self.select_calls: list[tuple[str, str]] = []
        self.update_calls: list[tuple[str, str, float, float]] = []
        self.snapshot_calls: list[tuple[str, str]] = []
        self._mean: dict[float, float] = {}

    def select_ratio(self, ticker: str, profile_id: str) -> float:
        self.select_calls.append((ticker, profile_id))
        if self._raise_on_select:
            raise RuntimeError("boom")
        if self._fixed_ratio is not None:
            return self._fixed_ratio
        # 보상 기반 greedy (cold-start 포함)
        for ratio in DEFAULT_RATIOS:
            if ratio not in self._mean:
                return ratio
        return max(self._mean.items(), key=lambda kv: kv[1])[0]

    def update(self, ticker: str, profile_id: str, ratio: float, reward: float):
        self.update_calls.append((ticker, profile_id, float(ratio), float(reward)))
        prev = self._mean.get(ratio, 0.0)
        self._mean[ratio] = (prev + reward) / 2 if ratio in self._mean else reward
        return None

    def snapshot(self, ticker: str, profile_id: str) -> dict[str, Any]:
        self.snapshot_calls.append((ticker, profile_id))
        best = max(self._mean.items(), key=lambda kv: kv[1])[0] if self._mean else None
        return {
            "ticker": ticker,
            "profile_id": profile_id,
            "best_ratio": best,
            "arms": {str(k): {"mean_reward": v} for k, v in self._mean.items()},
        }


class FakeTrainer:
    """train_with_metadata 호출 인자를 기록하는 trainer stub."""

    def __init__(
        self,
        *,
        excess_return_pct: float = 10.0,
        approved: bool = True,
    ) -> None:
        self._excess = excess_return_pct
        self._approved = approved
        self.calls: list[dict[str, Any]] = []

    def train_with_metadata(
        self, dataset: RLDataset, *, train_ratio: float, **kwargs,
    ) -> tuple[RLPolicyArtifact, RLSplitMetadata]:
        self.calls.append({"dataset": dataset, "train_ratio": train_ratio})
        artifact = RLPolicyArtifact(
            policy_id=f"rl_{dataset.ticker}_{len(self.calls)}",
            ticker=dataset.ticker,
            created_at=datetime.now(timezone.utc).isoformat(),
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            lookback=6,
            episodes=10,
            learning_rate=0.1,
            discount_factor=0.95,
            epsilon=0.15,
            trade_penalty_bps=2,
            q_table={"s0": {"BUY": 1.0, "HOLD": 0.0, "SELL": 0.0}},
            evaluation=RLEvaluationMetrics(
                total_return_pct=self._excess + 2.0,
                baseline_return_pct=2.0,
                excess_return_pct=self._excess,
                max_drawdown_pct=-5.0,
                trades=4,
                win_rate=0.6,
                holdout_steps=20,
                approved=self._approved,
            ),
        )
        split = RLSplitMetadata(
            train_ratio=train_ratio,
            train_size=int(len(dataset.closes) * train_ratio),
            test_size=len(dataset.closes) - int(len(dataset.closes) * train_ratio),
            train_start=dataset.timestamps[0],
            train_end=dataset.timestamps[int(len(dataset.closes) * train_ratio) - 1],
            test_start=dataset.timestamps[int(len(dataset.closes) * train_ratio)],
            test_end=dataset.timestamps[-1],
        )
        return artifact, split


def _make_walk_forward_result(
    *, consistency: float, excess: float, overall_approved: bool = True
) -> WalkForwardResult:
    return WalkForwardResult(
        n_folds=5,
        total_data_points=120,
        folds=[],
        avg_return_pct=excess + 2.0,
        avg_excess_return_pct=excess,
        consistency_score=consistency,
        overall_approved=overall_approved,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Test fixture builder ─────────────────────────────────────────────────


def _make_dataset(ticker: str = "005930.KS", length: int = 120) -> RLDataset:
    closes = [100.0 + i * 0.5 for i in range(length)]
    timestamps = [f"2026-01-{(i % 28) + 1:02d}" for i in range(length)]
    return RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)


def _build_improver(
    *,
    split_bandit: Any,
    trainer: FakeTrainer,
    walk_forward_result: WalkForwardResult,
    profile: dict[str, Any] | None = None,
) -> RLContinuousImprover:
    profile = profile or {
        "profile_id": "tabular_q_v2_momentum",
        "state_version": "qlearn_v2",
        "trainer_params": {},
        "dataset": {
            "default_train_ratio": 0.7,
            "adaptive_ratios": list(DEFAULT_RATIOS),
            "bandit_epsilon": 0.0,
            "min_history_points": 40,
        },
    }

    fake_em = MagicMock()
    fake_em.load_profile = MagicMock(return_value=profile)
    fake_em.create_run = MagicMock(return_value="run-1")
    fake_em.record_results = MagicMock(return_value=Path(tempfile.gettempdir()) / "run-1")
    fake_em.link_to_policy = MagicMock()
    fake_em.experiments_dir = Path(tempfile.gettempdir())

    fake_store = MagicMock()
    fake_store.save_policy = AsyncMock(side_effect=lambda artifact: artifact)
    fake_store.activate_policy = AsyncMock(return_value=True)
    fake_store.list_active_policies = AsyncMock(return_value={})
    fake_store.list_all_tickers = AsyncMock(return_value=["005930.KS"])

    fake_walk = MagicMock()
    fake_walk.evaluate = MagicMock(return_value=walk_forward_result)

    improver = RLContinuousImprover(
        experiment_manager=fake_em,
        policy_store=fake_store,
        walk_forward_evaluator=fake_walk,
        split_bandit=split_bandit,
    )
    # trainer/dataset 빌드 경로 가로채기
    improver._trainer_for_profile = MagicMock(return_value=trainer)  # type: ignore[assignment]
    improver._build_dataset = AsyncMock(return_value=_make_dataset())  # type: ignore[assignment]
    # walk-forward run은 evaluator를 직접 호출 — adapter 우회
    improver._run_walk_forward = MagicMock(return_value=walk_forward_result)  # type: ignore[assignment]
    improver._store_episode_to_s3 = AsyncMock(return_value=None)  # type: ignore[assignment]
    improver._write_walk_forward = MagicMock()  # type: ignore[assignment]
    improver._mark_promoted = MagicMock()  # type: ignore[assignment]
    return improver


# ── Tests ────────────────────────────────────────────────────────────────


class ImproverSplitIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_improver_uses_bandit_selected_ratio(self) -> None:
        bandit = FakeBandit(fixed_ratio=0.6)
        trainer = FakeTrainer()
        wf = _make_walk_forward_result(consistency=0.7, excess=8.0)
        improver = _build_improver(
            split_bandit=bandit, trainer=trainer, walk_forward_result=wf
        )

        with patch(
            "src.agents.rl_continuous_improver.normalize_with_db",
            new=AsyncMock(return_value="005930.KS"),
        ):
            await improver.retrain_ticker(
                "005930", profile_ids=["tabular_q_v2_momentum"]
            )

        self.assertEqual(len(trainer.calls), 1)
        self.assertAlmostEqual(trainer.calls[0]["train_ratio"], 0.6)
        self.assertEqual(
            bandit.select_calls, [("005930.KS", "tabular_q_v2_momentum")]
        )

    async def test_improver_updates_bandit_with_walk_forward_reward(self) -> None:
        bandit = FakeBandit(fixed_ratio=0.6)
        trainer = FakeTrainer(excess_return_pct=10.0)
        wf = _make_walk_forward_result(consistency=0.8, excess=10.0)
        improver = _build_improver(
            split_bandit=bandit, trainer=trainer, walk_forward_result=wf
        )

        with patch(
            "src.agents.rl_continuous_improver.normalize_with_db",
            new=AsyncMock(return_value="005930.KS"),
        ):
            await improver.retrain_ticker(
                "005930", profile_ids=["tabular_q_v2_momentum"]
            )

        self.assertEqual(len(bandit.update_calls), 1)
        ticker, profile_id, ratio, reward = bandit.update_calls[0]
        self.assertEqual(ticker, "005930.KS")
        self.assertEqual(profile_id, "tabular_q_v2_momentum")
        self.assertAlmostEqual(ratio, 0.6)
        expected = reward_from_walk_forward(
            consistency_score=0.8, excess_return_pct=10.0
        )
        self.assertAlmostEqual(reward, expected, places=6)

    async def test_retrain_outcome_includes_selected_ratio_and_snapshot(self) -> None:
        bandit = FakeBandit(fixed_ratio=0.6)
        trainer = FakeTrainer()
        wf = _make_walk_forward_result(consistency=0.8, excess=10.0)
        improver = _build_improver(
            split_bandit=bandit, trainer=trainer, walk_forward_result=wf
        )

        with patch(
            "src.agents.rl_continuous_improver.normalize_with_db",
            new=AsyncMock(return_value="005930.KS"),
        ):
            outcome = await improver.retrain_ticker(
                "005930", profile_ids=["tabular_q_v2_momentum"]
            )

        self.assertTrue(outcome.success)
        self.assertAlmostEqual(outcome.selected_train_ratio, 0.6)
        self.assertIsNotNone(outcome.bandit_snapshot)
        self.assertIn("best_ratio", outcome.bandit_snapshot)

    async def test_bandit_failure_falls_back_to_default_train_ratio(self) -> None:
        bandit = FakeBandit(raise_on_select=True)
        trainer = FakeTrainer()
        wf = _make_walk_forward_result(consistency=0.7, excess=8.0)
        improver = _build_improver(
            split_bandit=bandit, trainer=trainer, walk_forward_result=wf
        )

        with patch(
            "src.agents.rl_continuous_improver.normalize_with_db",
            new=AsyncMock(return_value="005930.KS"),
        ):
            outcome = await improver.retrain_ticker(
                "005930", profile_ids=["tabular_q_v2_momentum"]
            )

        self.assertTrue(outcome.success)
        self.assertEqual(len(trainer.calls), 1)
        # profile의 default_train_ratio=0.7로 fallback
        self.assertAlmostEqual(trainer.calls[0]["train_ratio"], 0.7)

    async def test_profile_overrides_arms_and_epsilon_when_no_injected_bandit(
        self,
    ) -> None:
        """split_bandit 미주입 시 profile의 adaptive_ratios/bandit_epsilon이 반영된다."""
        trainer = FakeTrainer()
        wf = _make_walk_forward_result(consistency=0.7, excess=8.0)
        custom_profile = {
            "profile_id": "tabular_q_custom",
            "state_version": "qlearn_v2",
            "trainer_params": {},
            "dataset": {
                "default_train_ratio": 0.7,
                "adaptive_ratios": [0.55, 0.65],
                "bandit_epsilon": 0.5,
                "min_history_points": 40,
            },
        }
        improver = _build_improver(
            split_bandit=None,  # 미주입 → profile 기반 lazy 생성
            trainer=trainer,
            walk_forward_result=wf,
            profile=custom_profile,
        )

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "src.agents.rl_split_bandit.DEFAULT_BANDIT_DIR", Path(tmp)
            ),
            patch(
                "src.agents.rl_continuous_improver.normalize_with_db",
                new=AsyncMock(return_value="005930.KS"),
            ),
        ):
            await improver.retrain_ticker(
                "005930", profile_ids=["tabular_q_custom"]
            )

        # cache된 bandit이 생성됐는지 + ratios/epsilon이 profile 값
        bandit = improver._bandit_cache["tabular_q_custom"]
        self.assertEqual(bandit.ratios, (0.55, 0.65))
        self.assertAlmostEqual(bandit.epsilon, 0.5)
        # 첫 호출이므로 cold-start → 0.55 선택되어 trainer에 전달
        self.assertAlmostEqual(trainer.calls[0]["train_ratio"], 0.55)

    async def test_real_bandit_converges_to_best_ratio_over_repeated_calls(
        self,
    ) -> None:
        """실제 RLSplitBandit + walk-forward 결과 dynamic: 0.6에만 높은 보상을 주면 수렴."""
        with tempfile.TemporaryDirectory() as tmp:
            real_bandit = RLSplitBandit(
                storage_dir=Path(tmp),
                ratios=DEFAULT_RATIOS,
                epsilon=0.0,
            )

            # 각 호출마다 trainer가 받은 ratio에 따라 walk-forward 결과가 바뀌는 improver
            trainer = FakeTrainer()
            # walk-forward 결과를 매번 다르게 주기 위해 improver._run_walk_forward를
            # 호출 시점에 ratio를 보고 결정하도록 override
            def dynamic_wf(dataset, trainer_arg):
                last_ratio = trainer.calls[-1]["train_ratio"]
                consistency = 0.95 if abs(last_ratio - 0.6) < 1e-6 else 0.3
                excess = 20.0 if abs(last_ratio - 0.6) < 1e-6 else 0.0
                return _make_walk_forward_result(
                    consistency=consistency, excess=excess
                )

            improver = _build_improver(
                split_bandit=real_bandit,
                trainer=trainer,
                walk_forward_result=_make_walk_forward_result(
                    consistency=0.0, excess=0.0
                ),
            )
            improver._run_walk_forward = dynamic_wf  # type: ignore[assignment]

            with patch(
                "src.agents.rl_continuous_improver.normalize_with_db",
                new=AsyncMock(return_value="005930.KS"),
            ):
                # cold-start 4회 + greedy 2회 = 6회
                for _ in range(6):
                    await improver.retrain_ticker(
                        "005930", profile_ids=["tabular_q_v2_momentum"]
                    )

            snapshot = real_bandit.snapshot(
                "005930.KS", "tabular_q_v2_momentum"
            )
            self.assertAlmostEqual(snapshot["best_ratio"], 0.6)
            # 마지막 2회는 greedy로 0.6을 선택했어야 함
            last_two_ratios = [call["train_ratio"] for call in trainer.calls[-2:]]
            self.assertEqual(last_two_ratios, [0.6, 0.6])


if __name__ == "__main__":
    unittest.main()
