"""
src/agents/rl_policy_registry.py — PolicyEntry DTO + 유틸 함수

DB 기반 정책 관리로 전환하면서 경량화된 모듈.
PolicyEntry 는 DB row ↔ 코드 간 DTO 역할만 수행한다.

제거된 클래스:
- TickerPolicies  → DB가 종목별 그룹핑을 대체
- PolicyRegistry  → DB가 레지스트리를 대체
- PromotionGate   → 상수로 충분
- CleanupPolicy   → 상수로 충분
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = ROOT / "artifacts" / "rl" / "models"

# ──────────────────────────── 승격 게이트 상수 ────────────────────────────
DEFAULT_MIN_RETURN_PCT = 5.0
DEFAULT_MAX_DRAWDOWN_LIMIT_PCT = -50.0

# ──────────────────────────── 자동 정리 상수 ────────────────────────────
CLEANUP_UNAPPROVED_DAYS = 30
CLEANUP_MAX_APPROVED_PER_TICKER = 5


class PolicyEntry(BaseModel):
    """단일 정책의 메타데이터 (DB <-> 코드 DTO)."""

    policy_id: str
    instrument_id: str  # DB 컬럼명과 일치 (구 ticker)
    algorithm: str = "tabular_q_learning"
    state_version: str = "qlearn_v1"
    return_pct: float = 0.0
    baseline_return_pct: float = 0.0
    excess_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    trades: int = 0
    win_rate: float = 0.0
    holdout_steps: int = 0
    approved: bool = False
    is_active: bool = False
    created_at: datetime
    file_path: str  # models_dir 기준 상대 경로
    hyperparams: Optional[dict] = None

    # ── 하이퍼파라미터 접근 편의 프로퍼티 ──

    @property
    def lookback(self) -> int:
        if self.hyperparams and "lookback" in self.hyperparams:
            return int(self.hyperparams["lookback"])
        return 6

    @property
    def episodes(self) -> int:
        if self.hyperparams and "episodes" in self.hyperparams:
            return int(self.hyperparams["episodes"])
        return 60

    @property
    def learning_rate(self) -> float:
        if self.hyperparams and "learning_rate" in self.hyperparams:
            return float(self.hyperparams["learning_rate"])
        return 0.18

    @property
    def discount_factor(self) -> float:
        if self.hyperparams and "discount_factor" in self.hyperparams:
            return float(self.hyperparams["discount_factor"])
        return 0.92

    @property
    def epsilon(self) -> float:
        if self.hyperparams and "epsilon" in self.hyperparams:
            return float(self.hyperparams["epsilon"])
        return 0.15

    @property
    def trade_penalty_bps(self) -> int:
        if self.hyperparams and "trade_penalty_bps" in self.hyperparams:
            return int(self.hyperparams["trade_penalty_bps"])
        return 5

    # ── 하위 호환: ticker 프로퍼티 ──

    @property
    def ticker(self) -> str:
        """instrument_id 의 별칭. 기존 코드 호환용."""
        return self.instrument_id

    @classmethod
    def from_db_row(cls, row: Any) -> PolicyEntry:
        """asyncpg.Record (또는 dict-like) 에서 PolicyEntry 를 생성한다."""
        hyperparams = row.get("hyperparams") if hasattr(row, "get") else row["hyperparams"]
        # asyncpg 가 JSONB 를 자동 파싱하는 경우 dict, 아니면 str
        if isinstance(hyperparams, str):
            import json
            hyperparams = json.loads(hyperparams)

        return cls(
            policy_id=row["policy_id"],
            instrument_id=row["instrument_id"],
            algorithm=row["algorithm"],
            state_version=row["state_version"],
            return_pct=float(row["return_pct"]),
            baseline_return_pct=float(row["baseline_return_pct"]),
            excess_return_pct=float(row["excess_return_pct"]),
            max_drawdown_pct=float(row["max_drawdown_pct"]),
            trades=int(row["trades"]),
            win_rate=float(row["win_rate"]),
            holdout_steps=int(row["holdout_steps"]),
            approved=bool(row["approved"]),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            file_path=row["file_path"],
            hyperparams=hyperparams,
        )


# ──────────────────────────── 유틸 함수 ────────────────────────────


def algorithm_dir_name(algorithm: str) -> str:
    """알고리즘 이름을 디렉토리 이름으로 변환한다.

    tabular_q_learning -> tabular
    dqn -> dqn
    ppo -> ppo
    """
    mapping = {
        "tabular_q_learning": "tabular",
        "dqn": "dqn",
        "ppo": "ppo",
    }
    return mapping.get(algorithm, algorithm.split("_")[0])


def build_relative_path(algorithm: str, ticker: str, policy_id: str) -> str:
    """models_dir 기준 상대 파일 경로를 생성한다.

    예: "tabular/259960.KS/rl_259960.KS_20260314T061942Z.json"
    """
    algo_dir = algorithm_dir_name(algorithm)
    return f"{algo_dir}/{ticker}/{policy_id}.json"
