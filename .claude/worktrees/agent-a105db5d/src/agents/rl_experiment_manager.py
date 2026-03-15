"""
src/agents/rl_experiment_manager.py — RL 실험 관리 시스템

실험 기록과 설정 프로파일을 관리합니다.
- profiles/: 재사용 가능한 하이퍼파라미터 설정
- experiments/: 각 실행 결과를 run_id 단위로 기록
- experiments/index.json: 모든 실험 요약 인덱스

File-based only, DB 없이 운영합니다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.agents.rl_trading import RLDataset, RLEvaluationMetrics, RLPolicyArtifact, RLSplitMetadata

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS_DIR = ROOT / "artifacts" / "rl"


# ────────────────────────────── Models ──────────────────────────────


class RLDatasetMeta(BaseModel):
    """데이터셋 메타데이터."""

    ticker: str
    source: str = "yfinance"
    range: str = "10y"
    data_hash: str
    closes_count: int
    timestamps_start: str
    timestamps_end: str


class RLExperimentConfig(BaseModel):
    """실험 설정 (profile_id + 오버라이드)."""

    profile_id: str
    algorithm: str
    state_version: str
    trainer_params: dict[str, Any]
    dataset_config: dict[str, Any]
    evaluation_gates: dict[str, Any]
    overrides: dict[str, Any] = Field(default_factory=dict)


class RLExperimentRun(BaseModel):
    """전체 실험 run 레코드."""

    run_id: str
    created_at: str
    config: RLExperimentConfig
    dataset_meta: RLDatasetMeta
    split_metadata: RLSplitMetadata
    metrics: RLEvaluationMetrics
    policy_id: Optional[str] = None
    artifact_path: Optional[str] = None
    approved: bool = False
    promoted_at: Optional[str] = None
    notes: str = ""


# ────────────────────────────── Manager ──────────────────────────────


class RLExperimentManager:
    """RL 실험 관리자.

    파일 기반으로 실험 run을 기록하고 조회합니다.
    """

    def __init__(self, artifacts_dir: Path | None = None) -> None:
        self.artifacts_dir = Path(artifacts_dir or DEFAULT_ARTIFACTS_DIR)
        self.experiments_dir = self.artifacts_dir / "experiments"
        self.profiles_dir = self.artifacts_dir / "profiles"
        self.index_path = self.experiments_dir / "index.json"

    def create_run(
        self,
        ticker: str,
        profile_id: str,
        trainer: Any,
        dataset: RLDataset,
        overrides: dict[str, Any] | None = None,
    ) -> str:
        """실험 run 디렉토리를 생성하고 run_id를 반환합니다.

        Args:
            ticker: 종목 코드
            profile_id: 프로파일 ID
            trainer: 훈련기 객체 (attribute access로 파라미터 추출)
            dataset: RLDataset 객체
            overrides: trainer_params 오버라이드

        Returns:
            run_id
        """
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

        profile = self.load_profile(profile_id)
        state_version = profile.get("state_version", "qlearn_v1")
        run_id = self._generate_run_id(ticker, state_version)

        config = self._build_config(profile, trainer, overrides)
        dataset_meta = self._build_dataset_meta(ticker, dataset)
        split_meta = self._build_split_metadata(dataset)

        run_dir = self.experiments_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / "config.json").write_text(
            json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_dir / "dataset_meta.json").write_text(
            json.dumps(dataset_meta.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_dir / "split.json").write_text(
            json.dumps(split_meta.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return run_id

    def record_results(
        self,
        run_id: str,
        artifact: RLPolicyArtifact,
        metrics: RLEvaluationMetrics,
        split_metadata: RLSplitMetadata,
    ) -> Path:
        """실험 결과를 기록합니다.

        Args:
            run_id: 실험 run ID
            artifact: 훈련된 정책 아티팩트
            metrics: 평가 지표
            split_metadata: 데이터 분할 메타데이터

        Returns:
            결과가 저장된 디렉토리
        """
        run_dir = self.experiments_dir / run_id
        if not run_dir.exists():
            raise ValueError(f"run_id {run_id} 디렉토리 없음")

        metrics_dict = {
            "total_return_pct": metrics.total_return_pct,
            "baseline_return_pct": metrics.baseline_return_pct,
            "excess_return_pct": metrics.excess_return_pct,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "trades": metrics.trades,
            "win_rate": metrics.win_rate,
            "holdout_steps": metrics.holdout_steps,
            "approved": metrics.approved,
        }

        (run_dir / "metrics.json").write_text(
            json.dumps(metrics_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_dir / "split.json").write_text(
            json.dumps(split_metadata.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        artifact_link = {
            "policy_id": artifact.policy_id,
            "artifact_path": artifact.artifact_path,
        }
        (run_dir / "artifact_link.json").write_text(
            json.dumps(artifact_link, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return run_dir

    def load_run(self, run_id: str) -> RLExperimentRun:
        """실험 run을 로드합니다.

        Args:
            run_id: 실험 run ID

        Returns:
            RLExperimentRun
        """
        run_dir = self.experiments_dir / run_id
        if not run_dir.exists():
            raise ValueError(f"run_id {run_id} 디렉토리 없음")

        config_dict = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        dataset_meta_dict = json.loads((run_dir / "dataset_meta.json").read_text(encoding="utf-8"))
        split_dict = json.loads((run_dir / "split.json").read_text(encoding="utf-8"))
        metrics_dict = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

        config = RLExperimentConfig(**config_dict)
        dataset_meta = RLDatasetMeta(**dataset_meta_dict)
        split_meta = RLSplitMetadata(**split_dict)
        metrics = RLEvaluationMetrics(**metrics_dict)

        policy_id = None
        artifact_path = None
        if (run_dir / "artifact_link.json").exists():
            link_dict = json.loads((run_dir / "artifact_link.json").read_text(encoding="utf-8"))
            policy_id = link_dict.get("policy_id")
            artifact_path = link_dict.get("artifact_path")

        notes = ""
        if (run_dir / "notes.md").exists():
            notes = (run_dir / "notes.md").read_text(encoding="utf-8")

        promoted_at = None
        if (run_dir / "promoted_at.txt").exists():
            promoted_at = (run_dir / "promoted_at.txt").read_text(encoding="utf-8").strip()

        return RLExperimentRun(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            config=config,
            dataset_meta=dataset_meta,
            split_metadata=split_meta,
            metrics=metrics,
            policy_id=policy_id,
            artifact_path=artifact_path,
            approved=metrics.approved,
            promoted_at=promoted_at,
            notes=notes,
        )

    def list_runs(
        self,
        ticker: Optional[str] = None,
        profile_id: Optional[str] = None,
        approved_only: bool = False,
    ) -> list[RLExperimentRun]:
        """실험 runs을 필터링하여 조회합니다.

        Args:
            ticker: 종목 필터 (None이면 전체)
            profile_id: 프로파일 ID 필터 (None이면 전체)
            approved_only: 승인된 실험만

        Returns:
            RLExperimentRun 목록
        """
        if not self.experiments_dir.exists():
            return []

        runs = []
        for run_dir in sorted(self.experiments_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            if not (run_dir / "config.json").exists():
                continue

            run_id = run_dir.name
            try:
                run = self.load_run(run_id)

                if ticker and not run_dir.name.endswith(f"-{ticker}-*"):
                    # 간단한 필터: run_id에 ticker 포함 여부
                    if f"-{ticker}-" not in run_id:
                        continue

                if profile_id and run.config.profile_id != profile_id:
                    continue

                if approved_only and not run.approved:
                    continue

                runs.append(run)
            except Exception:
                # 손상된 run 무시
                continue

        return runs

    def build_index(self) -> dict[str, Any]:
        """모든 실험을 요약한 index.json을 구축합니다.

        Returns:
            인덱스 dict
        """
        runs = self.list_runs()
        index = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_runs": len(runs),
            "approved_runs": sum(1 for r in runs if r.approved),
            "runs_by_ticker": {},
            "runs_by_profile": {},
            "top_performers": [],
        }

        by_ticker = {}
        by_profile = {}
        for run in runs:
            ticker = run.dataset_meta.ticker
            profile_id = run.config.profile_id

            if ticker not in by_ticker:
                by_ticker[ticker] = []
            by_ticker[ticker].append(
                {
                    "run_id": run.run_id,
                    "return_pct": run.metrics.total_return_pct,
                    "approved": run.approved,
                    "policy_id": run.policy_id,
                }
            )

            if profile_id not in by_profile:
                by_profile[profile_id] = []
            by_profile[profile_id].append(
                {
                    "run_id": run.run_id,
                    "ticker": ticker,
                    "return_pct": run.metrics.total_return_pct,
                    "approved": run.approved,
                }
            )

        index["runs_by_ticker"] = by_ticker
        index["runs_by_profile"] = by_profile

        top_performers = sorted(
            [
                {
                    "run_id": r.run_id,
                    "ticker": r.dataset_meta.ticker,
                    "return_pct": r.metrics.total_return_pct,
                    "profile_id": r.config.profile_id,
                }
                for r in runs
            ],
            key=lambda x: x["return_pct"],
            reverse=True,
        )[:10]
        index["top_performers"] = top_performers

        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return index

    def link_to_policy(self, run_id: str, policy_id: str) -> None:
        """experiment run을 정책과 양방향으로 연결합니다.

        Args:
            run_id: 실험 run ID
            policy_id: 정책 ID
        """
        run_dir = self.experiments_dir / run_id
        if not run_dir.exists():
            raise ValueError(f"run_id {run_id} 디렉토리 없음")

        # artifact_link.json에 policy_id 업데이트
        link_path = run_dir / "artifact_link.json"
        if link_path.exists():
            link = json.loads(link_path.read_text(encoding="utf-8"))
        else:
            link = {}

        link["policy_id"] = policy_id
        link_path.write_text(json.dumps(link, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_profile(self, profile_id: str) -> dict[str, Any]:
        """프로파일을 로드합니다.

        Args:
            profile_id: 프로파일 ID

        Returns:
            프로파일 dict
        """
        profile_path = self.profiles_dir / f"{profile_id}.json"
        if not profile_path.exists():
            raise ValueError(f"profile {profile_id} 없음")

        return json.loads(profile_path.read_text(encoding="utf-8"))

    # ────────────────────────────── Private Helpers ──────────────────────────────

    @staticmethod
    def _generate_run_id(ticker: str, state_version: str) -> str:
        """run_id를 생성합니다.

        형식: <YYYYMMDD>T<HHMMSS>Z-<ticker>-<state_version>

        Args:
            ticker: 종목 코드
            state_version: 상태 버전

        Returns:
            run_id 문자열
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        return f"{timestamp}-{ticker}-{state_version}"

    @staticmethod
    def _compute_dataset_hash(dataset: RLDataset) -> str:
        """데이터셋 해시를 계산합니다.

        Args:
            dataset: RLDataset

        Returns:
            SHA256 hex 문자열 (처음 12자)
        """
        combined = "".join(str(c) for c in dataset.closes)
        full_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return full_hash[:12]

    def _build_config(
        self,
        profile: dict[str, Any],
        trainer: Any,
        overrides: dict[str, Any] | None = None,
    ) -> RLExperimentConfig:
        """프로파일과 trainer에서 RLExperimentConfig를 구축합니다.

        Args:
            profile: 프로파일 dict
            trainer: 훈련기 (attribute access)
            overrides: 오버라이드 dict

        Returns:
            RLExperimentConfig
        """
        overrides = overrides or {}

        trainer_params = profile.get("trainer_params", {}).copy()
        # trainer 객체에서 실제 값들을 추출
        for key in trainer_params:
            if hasattr(trainer, key):
                trainer_params[key] = getattr(trainer, key)

        trainer_params.update(overrides)

        return RLExperimentConfig(
            profile_id=profile.get("profile_id", "unknown"),
            algorithm=profile.get("algorithm", "tabular_q_learning"),
            state_version=profile.get("state_version", "qlearn_v1"),
            trainer_params=trainer_params,
            dataset_config=profile.get("dataset", {}),
            evaluation_gates=profile.get("evaluation", {}),
            overrides=overrides,
        )

    def _build_dataset_meta(self, ticker: str, dataset: RLDataset) -> RLDatasetMeta:
        """RLDataset에서 RLDatasetMeta를 구축합니다.

        Args:
            ticker: 종목 코드
            dataset: RLDataset

        Returns:
            RLDatasetMeta
        """
        data_hash = self._compute_dataset_hash(dataset)
        return RLDatasetMeta(
            ticker=ticker,
            source="yfinance",
            range="10y",
            data_hash=data_hash,
            closes_count=len(dataset.closes),
            timestamps_start=dataset.timestamps[0] if dataset.timestamps else "",
            timestamps_end=dataset.timestamps[-1] if dataset.timestamps else "",
        )

    @staticmethod
    def _build_split_metadata(dataset: RLDataset) -> RLSplitMetadata:
        """RLDataset에서 기본 split metadata를 구축합니다.

        Args:
            dataset: RLDataset

        Returns:
            RLSplitMetadata
        """
        return RLSplitMetadata(
            train_ratio=0.7,
            train_size=int(len(dataset.closes) * 0.7),
            test_size=len(dataset.closes) - int(len(dataset.closes) * 0.7),
            train_start=dataset.timestamps[0] if dataset.timestamps else "",
            train_end=dataset.timestamps[int(len(dataset.closes) * 0.7) - 1]
            if dataset.timestamps else "",
            test_start=dataset.timestamps[int(len(dataset.closes) * 0.7)]
            if dataset.timestamps else "",
            test_end=dataset.timestamps[-1] if dataset.timestamps else "",
        )
