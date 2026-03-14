"""
src/agents/rl_experiment.py — RL 실험 프로파일 및 run 추적 관리

프로파일 (profiles):
  - 재사용 가능한 하이퍼파라미터 세트
  - artifacts/rl/profiles/<profile_id>.json

실험 run (experiments):
  - 학습 실행마다 생성되는 메타데이터 디렉토리
  - artifacts/rl/experiments/<run_id>/
    ├── config.json       (프로파일 + 오버라이드)
    ├── dataset_meta.json (데이터 소스, 해시)
    ├── split.json        (train/test 분할)
    ├── metrics.json      (평가 지표)
    └── artifact_link.json(정책 연결)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.agents.rl_trading import RLDataset, RLEvaluationMetrics, RLSplitMetadata
from src.utils.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "artifacts" / "rl" / "profiles"
EXPERIMENTS_DIR = ROOT / "artifacts" / "rl" / "experiments"


# ──────────────────────────── Profile ────────────────────────────


class TrainerParams(BaseModel):
    """학습 하이퍼파라미터."""

    episodes: int = 300
    lookback: int = 20
    learning_rate: float = 0.10
    discount_factor: float = 0.95
    epsilon: float = 0.30
    trade_penalty_bps: int = 2
    opportunity_cost_factor: float = 0.5
    num_seeds: int = 5


class RLProfile(BaseModel):
    """재사용 가능한 RL 하이퍼파라미터 프로파일."""

    profile_id: str
    algorithm: str = "tabular_q_learning"
    state_version: str = "qlearn_v2"
    trainer_params: TrainerParams = Field(default_factory=TrainerParams)
    default_train_ratio: float = 0.7


def load_profile(
    profile_id: str, profiles_dir: Path | None = None
) -> Optional[RLProfile]:
    """프로파일 JSON 파일을 로드합니다."""
    directory = profiles_dir or PROFILES_DIR
    path = directory / f"{profile_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RLProfile.model_validate(data)


def save_profile(profile: RLProfile, profiles_dir: Path | None = None) -> Path:
    """프로파일을 JSON 파일로 저장합니다."""
    directory = profiles_dir or PROFILES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile.profile_id}.json"
    path.write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return path


# ──────────────────────────── Dataset Hash ────────────────────────────


def compute_dataset_hash(closes: list[float]) -> str:
    """종가 리스트의 SHA256 해시 (앞 16자)를 반환합니다.

    동일한 데이터 → 동일한 해시를 보장하여 재현성을 추적합니다.
    """
    payload = json.dumps(closes, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────── Run ID ────────────────────────────


def generate_run_id(ticker: str, state_version: str) -> str:
    """실험 run ID를 생성합니다.

    형식: {timestamp}Z-{ticker}-{state_version}
    예: 20260315T120000Z-259960.KS-qlearn_v2
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{ticker}-{state_version}"


# ──────────────────────────── Experiment Manager ────────────────────────────


class RLExperimentManager:
    """RL 실험 run 메타데이터를 관리합니다."""

    def __init__(self, experiments_dir: Path | None = None) -> None:
        self.experiments_dir = experiments_dir or EXPERIMENTS_DIR

    def _run_dir(self, run_id: str) -> Path:
        return self.experiments_dir / run_id

    def create_run(
        self,
        *,
        dataset: RLDataset,
        profile: RLProfile | None = None,
        profile_id: str | None = None,
        trainer_overrides: dict[str, Any] | None = None,
        data_source: str = "unknown",
        data_range: str = "",
        state_version: str = "qlearn_v2",
    ) -> str:
        """실험 run을 생성하고 config.json + dataset_meta.json을 저장합니다.

        Returns:
            생성된 run_id
        """
        run_id = generate_run_id(dataset.ticker, state_version)
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # config.json
        effective_profile_id = profile_id
        if profile:
            effective_profile_id = profile.profile_id

        config: dict[str, Any] = {
            "run_id": run_id,
            "profile_id": effective_profile_id,
            "state_version": state_version,
        }
        if profile:
            config["trainer_params"] = profile.trainer_params.model_dump()
        if trainer_overrides:
            config["trainer_overrides"] = trainer_overrides
        config["created_at"] = datetime.now(timezone.utc).isoformat()

        self._write_json(run_dir / "config.json", config)

        # dataset_meta.json
        dataset_hash = compute_dataset_hash(dataset.closes)
        dataset_meta = {
            "ticker": dataset.ticker,
            "data_source": data_source,
            "data_range": data_range,
            "dataset_hash": dataset_hash,
            "total_rows": len(dataset.closes),
            "first_timestamp": dataset.timestamps[0] if dataset.timestamps else None,
            "last_timestamp": dataset.timestamps[-1] if dataset.timestamps else None,
        }
        self._write_json(run_dir / "dataset_meta.json", dataset_meta)

        logger.info("실험 run 생성: %s", run_id)
        return run_id

    def record_split(self, run_id: str, split: RLSplitMetadata) -> None:
        """split.json을 저장합니다."""
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"실험 run 디렉토리가 없습니다: {run_id}")
        self._write_json(run_dir / "split.json", asdict(split))

    def record_metrics(self, run_id: str, evaluation: RLEvaluationMetrics) -> None:
        """metrics.json을 저장합니다."""
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"실험 run 디렉토리가 없습니다: {run_id}")
        self._write_json(run_dir / "metrics.json", asdict(evaluation))

    def link_artifact(
        self,
        run_id: str,
        policy_id: str,
        artifact_path: str | None = None,
    ) -> None:
        """artifact_link.json을 저장하여 정책과 실험을 연결합니다."""
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"실험 run 디렉토리가 없습니다: {run_id}")
        link = {
            "policy_id": policy_id,
            "artifact_path": artifact_path,
            "promoted": False,
            "promoted_at": None,
        }
        self._write_json(run_dir / "artifact_link.json", link)

    def mark_promoted(self, run_id: str) -> None:
        """artifact_link.json에 promoted=True를 기록합니다."""
        run_dir = self._run_dir(run_id)
        link_path = run_dir / "artifact_link.json"
        if not link_path.exists():
            raise FileNotFoundError(
                f"artifact_link.json이 없습니다: {run_id}"
            )
        link = json.loads(link_path.read_text(encoding="utf-8"))
        link["promoted"] = True
        link["promoted_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(link_path, link)

    def list_experiments(self, ticker: str | None = None) -> list[dict[str, Any]]:
        """실험 요약 목록을 반환합니다.

        Args:
            ticker: 특정 종목으로 필터링 (None이면 전체)

        Returns:
            config.json + metrics.json 요약 딕셔너리 목록 (최신순)
        """
        if not self.experiments_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for run_dir in sorted(self.experiments_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            config_path = run_dir / "config.json"
            if not config_path.exists():
                continue

            config = json.loads(config_path.read_text(encoding="utf-8"))

            # ticker 필터링
            if ticker:
                dataset_path = run_dir / "dataset_meta.json"
                if dataset_path.exists():
                    dataset_meta = json.loads(
                        dataset_path.read_text(encoding="utf-8")
                    )
                    if dataset_meta.get("ticker") != ticker:
                        continue
                else:
                    continue

            summary: dict[str, Any] = {
                "run_id": config.get("run_id", run_dir.name),
                "profile_id": config.get("profile_id"),
                "state_version": config.get("state_version"),
                "created_at": config.get("created_at"),
            }

            # metrics 추가 (있는 경우)
            metrics_path = run_dir / "metrics.json"
            if metrics_path.exists():
                summary["metrics"] = json.loads(
                    metrics_path.read_text(encoding="utf-8")
                )

            # artifact link 추가 (있는 경우)
            link_path = run_dir / "artifact_link.json"
            if link_path.exists():
                summary["artifact_link"] = json.loads(
                    link_path.read_text(encoding="utf-8")
                )

            results.append(summary)

        return results

    def load_experiment(self, run_id: str) -> dict[str, Any]:
        """실험의 모든 메타데이터를 통합하여 반환합니다."""
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"실험 run 디렉토리가 없습니다: {run_id}")

        result: dict[str, Any] = {"run_id": run_id}

        for filename in (
            "config.json",
            "dataset_meta.json",
            "split.json",
            "metrics.json",
            "artifact_link.json",
        ):
            filepath = run_dir / filename
            if filepath.exists():
                key = filename.replace(".json", "")
                result[key] = json.loads(filepath.read_text(encoding="utf-8"))

        return result

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
