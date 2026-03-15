import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

# Constants for Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
EXPERIMENTS_DIR = CONFIG_DIR / "experiments"
ACTIVE_DIR = CONFIG_DIR / "active"


class ExperimentMetrics(BaseModel):
    primary: str
    values: Dict[str, Any]


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    domain: Literal["strategy_a", "strategy_b", "rl", "search"]
    config_version: str
    status: Literal["draft", "testing", "approved", "active", "retired"] = "testing"
    commit_hash: Optional[str] = None
    discussion_doc: Optional[str] = None
    expected_impact: List[str] = Field(default_factory=list)
    metrics: ExperimentMetrics
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ExperimentTracker:
    """
    공통 메타 레코드 (Experiment Metadata) 로깅 및 추적 클래스.
    각 도메인(A, B, RL, Search)에서 일관된 JSON 스키마를 떨어뜨릴 수 있도록 강제합니다.
    """

    def __init__(self, use_git_hash: bool = True):
        self.use_git_hash = use_git_hash

    def get_current_commit_hash(self) -> str:
        if not self.use_git_hash:
            return "unknown"
        try:
            # shell command to get the latest commit hash
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(PROJECT_ROOT)
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

    def log_experiment(self, record: ExperimentRecord) -> Path:
        """실험 결과(메타데이터)를 config/experiments 하위에 JSON으로 저장합니다."""
        
        # 커밋 해시가 명시되어 있지 않은 경우 자동 주입
        if not record.commit_hash or record.commit_hash == "unknown":
            record.commit_hash = self.get_current_commit_hash()

        domain_dir = EXPERIMENTS_DIR / record.domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        filepath = domain_dir / f"{record.run_id}.json"
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(record.model_dump_json(indent=2))

        return filepath

# Instantiate a global tracker
tracker = ExperimentTracker()

def log_experiment(record: ExperimentRecord) -> Path:
    """Convenience function to access the global tracker"""
    return tracker.log_experiment(record)
