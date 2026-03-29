"""
src/agents/rl_continuous_improver.py — RL continuous improvement loop

LLM 전략과 달리 RL은 스스로 더 나은 정책을 학습/교체할 수 있어야 하므로,
다음 루프를 하나의 서비스로 묶습니다.

1. 최신 시장 데이터셋 구성
2. 여러 RL 프로파일 후보 학습
3. holdout + walk-forward 검증
4. 가장 좋은 후보 선택
5. 승격 게이트 통과 시 활성 정책 교체
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
from typing import Any, Sequence

from src.agents.rl_experiment_manager import RLExperimentManager
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import (
    RLDataset,
    RLDatasetBuilder,
    RLPolicyArtifact,
    RLSplitMetadata,
    TabularQTrainer,
)
from src.agents.rl_trading_v2 import TabularQTrainerV2
from src.agents.rl_walk_forward import WalkForwardEvaluator, WalkForwardResult
from src.utils.logging import get_logger
from src.utils.ticker import find_in_map, normalize_with_db, to_raw

logger = get_logger(__name__)

DEFAULT_PROFILE_IDS = (
    "tabular_q_v2_momentum",
    "tabular_q_v1_baseline",
)


@dataclass
class CandidateResult:
    profile_id: str
    run_id: str
    artifact: RLPolicyArtifact
    split_metadata: RLSplitMetadata
    walk_forward: WalkForwardResult


@dataclass
class RetrainOutcome:
    ticker: str
    success: bool
    new_policy_id: str | None = None
    profile_id: str | None = None
    excess_return: float | None = None
    walk_forward_passed: bool = False
    walk_forward_consistency: float | None = None
    deployed: bool = False
    active_policy_before: str | None = None
    active_policy_after: str | None = None
    error: str | None = None


class _WalkForwardTrainerAdapter:
    """WalkForwardEvaluator와 현재 trainer 시그니처를 맞춥니다."""

    def __init__(self, ticker: str, trainer: Any) -> None:
        self._ticker = ticker
        self._trainer = trainer

    def train(self, closes: list[float]) -> dict[str, dict[str, float]]:
        dataset = RLDataset(
            ticker=self._ticker,
            closes=closes,
            timestamps=[str(idx) for idx in range(len(closes))],
        )
        artifact = self._trainer.train(dataset)
        return artifact.q_table

    def evaluate(
        self,
        q_table: dict[str, dict[str, float]],
        closes: list[float],
    ) -> Any:
        return self._trainer.evaluate(closes, q_table)


class RLContinuousImprover:
    """RL 정책의 지속적 개선을 담당합니다."""

    def __init__(
        self,
        *,
        dataset_builder: RLDatasetBuilder | None = None,
        experiment_manager: RLExperimentManager | None = None,
        policy_store: RLPolicyStoreV2 | None = None,
        walk_forward_evaluator: WalkForwardEvaluator | None = None,
    ) -> None:
        self._dataset_builder = dataset_builder
        self._experiment_manager = experiment_manager or RLExperimentManager()
        self._policy_store = policy_store or RLPolicyStoreV2()
        self._walk_forward = walk_forward_evaluator or WalkForwardEvaluator(
            n_folds=5,
            expanding_window=True,
            consistency_threshold=0.6,
        )

    async def retrain_ticker(
        self,
        ticker: str,
        *,
        profile_ids: Sequence[str] | None = None,
        dataset_days: int = 180,
    ) -> RetrainOutcome:
        profile_list = list(profile_ids or DEFAULT_PROFILE_IDS)
        if not profile_list:
            return RetrainOutcome(
                ticker=ticker,
                success=False,
                error="사용 가능한 RL 프로파일이 없습니다.",
            )

        canonical_ticker = await normalize_with_db(ticker)
        raw_ticker = to_raw(canonical_ticker)
        active_before = self._active_policy_id(canonical_ticker)

        try:
            dataset = await self._build_dataset(raw_ticker, canonical_ticker, dataset_days, profile_list[0])
        except Exception as exc:
            logger.warning("RL 데이터셋 구성 실패 [%s]: %s", ticker, exc)
            return RetrainOutcome(
                ticker=canonical_ticker,
                success=False,
                active_policy_before=active_before,
                active_policy_after=active_before,
                error=str(exc),
            )

        candidates: list[CandidateResult] = []
        errors: list[str] = []
        for profile_id in profile_list:
            try:
                candidate = await self._train_candidate(
                    dataset=dataset,
                    profile_id=profile_id,
                )
                candidates.append(candidate)
            except Exception as exc:
                logger.warning(
                    "RL 후보 학습 실패 [%s][%s]: %s",
                    canonical_ticker,
                    profile_id,
                    exc,
                )
                errors.append(f"{profile_id}: {exc}")

        if not candidates:
            return RetrainOutcome(
                ticker=canonical_ticker,
                success=False,
                active_policy_before=active_before,
                active_policy_after=active_before,
                error="; ".join(errors) or "후보 정책 생성 실패",
            )

        best = max(candidates, key=self._candidate_sort_key)
        deployed = False
        if best.artifact.evaluation.approved and best.walk_forward.overall_approved:
            deployed = self._policy_store.activate_policy(best.artifact)
            if deployed:
                self._mark_promoted(best.run_id)

        active_after = self._active_policy_id(canonical_ticker)

        # S3 Data Lake에 학습 에피소드 아카이빙 (비필수)
        await self._store_episode_to_s3(
            ticker=canonical_ticker,
            best=best,
            dataset_days=dataset_days,
            deployed=deployed,
        )

        return RetrainOutcome(
            ticker=canonical_ticker,
            success=True,
            new_policy_id=best.artifact.policy_id,
            profile_id=best.profile_id,
            excess_return=best.artifact.evaluation.excess_return_pct,
            walk_forward_passed=best.walk_forward.overall_approved,
            walk_forward_consistency=best.walk_forward.consistency_score,
            deployed=deployed,
            active_policy_before=active_before,
            active_policy_after=active_after,
            error=None if deployed or not errors else "; ".join(errors),
        )

    async def retrain_all(
        self,
        *,
        tickers: Sequence[str] | None = None,
        profile_ids: Sequence[str] | None = None,
        dataset_days: int = 180,
    ) -> list[RetrainOutcome]:
        targets = list(dict.fromkeys(tickers or self.list_target_tickers()))
        outcomes: list[RetrainOutcome] = []
        for ticker in targets:
            outcomes.append(
                await self.retrain_ticker(
                    ticker,
                    profile_ids=profile_ids,
                    dataset_days=dataset_days,
                )
            )
        return outcomes

    def list_target_tickers(self) -> list[str]:
        registry = self._policy_store.load_registry()
        return registry.list_all_tickers()

    async def _build_dataset(
        self,
        raw_ticker: str,
        canonical_ticker: str,
        dataset_days: int,
        profile_id: str,
    ) -> RLDataset:
        builder = self._dataset_builder or self._builder_for_profile(profile_id)
        dataset = await builder.build_dataset(raw_ticker, days=dataset_days)
        return RLDataset(
            ticker=canonical_ticker,
            closes=list(dataset.closes),
            timestamps=list(dataset.timestamps),
        )

    async def _train_candidate(
        self,
        *,
        dataset: RLDataset,
        profile_id: str,
    ) -> CandidateResult:
        profile = self._experiment_manager.load_profile(profile_id)
        trainer = self._trainer_for_profile(profile)
        train_ratio = float(profile.get("dataset", {}).get("default_train_ratio", 0.7))

        run_id = self._experiment_manager.create_run(
            dataset.ticker,
            profile_id,
            trainer,
            dataset,
        )
        artifact, split_metadata = trainer.train_with_metadata(dataset, train_ratio=train_ratio)
        artifact = self._policy_store.save_policy(artifact)

        run_dir = self._experiment_manager.record_results(
            run_id,
            artifact,
            artifact.evaluation,
            split_metadata,
        )
        self._experiment_manager.link_to_policy(run_id, artifact.policy_id)

        walk_forward = self._run_walk_forward(dataset, trainer)
        self._write_walk_forward(run_dir, walk_forward)

        return CandidateResult(
            profile_id=profile_id,
            run_id=run_id,
            artifact=artifact,
            split_metadata=split_metadata,
            walk_forward=walk_forward,
        )

    def _builder_for_profile(self, profile_id: str) -> RLDatasetBuilder:
        profile = self._experiment_manager.load_profile(profile_id)
        dataset_cfg = profile.get("dataset", {})
        min_history = int(dataset_cfg.get("min_history_points", 40))
        return RLDatasetBuilder(min_history_points=min_history)

    def _trainer_for_profile(self, profile: dict[str, Any]) -> Any:
        params = dict(profile.get("trainer_params", {}))
        state_version = str(profile.get("state_version", "")).lower()
        trainer_cls = (
            TabularQTrainerV2
            if state_version.endswith("v2") or "opportunity_cost_factor" in params or "num_seeds" in params
            else TabularQTrainer
        )
        sig = inspect.signature(trainer_cls.__init__)
        filtered = {
            key: value
            for key, value in params.items()
            if key in sig.parameters
        }
        return trainer_cls(**filtered)

    def _run_walk_forward(
        self,
        dataset: RLDataset,
        trainer: Any,
    ) -> WalkForwardResult:
        adapter = _WalkForwardTrainerAdapter(dataset.ticker, trainer)
        return self._walk_forward.evaluate(dataset.closes, adapter)

    @staticmethod
    def _candidate_sort_key(candidate: CandidateResult) -> tuple[float, ...]:
        return (
            1.0 if candidate.walk_forward.overall_approved else 0.0,
            candidate.walk_forward.consistency_score,
            1.0 if candidate.artifact.evaluation.approved else 0.0,
            candidate.artifact.evaluation.excess_return_pct,
            candidate.artifact.evaluation.total_return_pct,
            candidate.artifact.evaluation.max_drawdown_pct,
        )

    def _active_policy_id(self, ticker: str) -> str | None:
        active_map = self._policy_store.load_registry().list_active_policies()
        return find_in_map(ticker, {k: v for k, v in active_map.items() if v})

    @staticmethod
    def _write_walk_forward(run_dir: Path, result: WalkForwardResult) -> None:
        (run_dir / "walk_forward.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _mark_promoted(self, run_id: str) -> None:
        run_dir = self._experiment_manager.experiments_dir / run_id
        if not run_dir.exists():
            return
        (run_dir / "promoted_at.txt").write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )

    async def _store_episode_to_s3(
        self,
        ticker: str,
        best: CandidateResult,
        dataset_days: int,
        deployed: bool,
    ) -> None:
        """학습 에피소드를 S3 Data Lake에 아카이빙합니다 (비필수)."""
        try:
            from src.services.datalake import store_rl_episodes

            evaluation = best.artifact.evaluation
            record = {
                "ticker": ticker,
                "policy_id": best.artifact.policy_id,
                "profile_id": best.profile_id,
                "dataset_days": dataset_days,
                "train_return_pct": evaluation.baseline_return_pct,
                "holdout_return_pct": evaluation.total_return_pct,
                "excess_return_pct": evaluation.excess_return_pct,
                "max_drawdown_pct": evaluation.max_drawdown_pct,
                "walk_forward_passed": best.walk_forward.overall_approved,
                "walk_forward_consistency": best.walk_forward.consistency_score,
                "deployed": deployed,
                "created_at": datetime.now(timezone.utc),
            }
            await store_rl_episodes([record])
        except Exception as exc:
            logger.debug("RL 에피소드 S3 저장 실패 (비필수): %s", exc)
