"""
src/agents/rl_policy_registry.py — PolicyRegistry Pydantic 모델 정의

RL 정책의 중앙 인덱스(registry.json)를 관리하는 Pydantic 모델입니다.
알고리즘별 네임스페이스(tabular/, dqn/, ppo/)와 종목별 디렉토리를 기반으로
정책 메타데이터를 통합 관리합니다.

구조:
    artifacts/rl/models/
    ├── tabular/<ticker>/<policy_id>.json
    ├── dqn/<ticker>/...
    ├── ppo/<ticker>/...
    └── registry.json
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = ROOT / "artifacts" / "rl" / "models"

# 승격 게이트 기본값
DEFAULT_MIN_RETURN_PCT = 5.0
DEFAULT_MAX_DRAWDOWN_LIMIT_PCT = -50.0

# 자동 정리 기본값
CLEANUP_UNAPPROVED_DAYS = 30
CLEANUP_MAX_APPROVED_PER_TICKER = 5


class PolicyEntry(BaseModel):
    """단일 정책의 메타데이터."""

    policy_id: str
    ticker: str
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
    created_at: datetime
    file_path: str  # registry.json 기준 상대 경로 (e.g. "tabular/259960.KS/policy_id.json")

    # 추가 메타데이터 (Codex 제안)
    lookback: int = 6
    episodes: int = 60
    learning_rate: float = 0.18
    discount_factor: float = 0.92
    epsilon: float = 0.15
    trade_penalty_bps: int = 5

    # 실험 run 양방향 참조
    run_id: Optional[str] = None


class TickerPolicies(BaseModel):
    """종목별 정책 목록 및 활성 정책 포인터."""

    active_policy_id: Optional[str] = None
    policies: list[PolicyEntry] = Field(default_factory=list)

    def get_active_policy(self) -> Optional[PolicyEntry]:
        """활성 정책 엔트리를 반환합니다."""
        if not self.active_policy_id:
            return None
        for p in self.policies:
            if p.policy_id == self.active_policy_id:
                return p
        return None

    def get_policy(self, policy_id: str) -> Optional[PolicyEntry]:
        """policy_id로 정책 엔트리를 조회합니다."""
        for p in self.policies:
            if p.policy_id == policy_id:
                return p
        return None

    def add_policy(self, entry: PolicyEntry) -> None:
        """정책을 추가합니다. 동일 policy_id가 있으면 교체합니다."""
        self.policies = [p for p in self.policies if p.policy_id != entry.policy_id]
        self.policies.append(entry)

    def remove_policy(self, policy_id: str) -> Optional[PolicyEntry]:
        """정책을 제거합니다. 활성 정책은 제거할 수 없습니다."""
        if policy_id == self.active_policy_id:
            return None
        removed = None
        new_policies = []
        for p in self.policies:
            if p.policy_id == policy_id:
                removed = p
            else:
                new_policies.append(p)
        self.policies = new_policies
        return removed


class PromotionGate(BaseModel):
    """승격 게이트 설정."""

    min_return_pct: float = DEFAULT_MIN_RETURN_PCT
    max_drawdown_limit_pct: float = DEFAULT_MAX_DRAWDOWN_LIMIT_PCT
    auto_promote_paper_only: bool = True


class CleanupPolicy(BaseModel):
    """자동 정리 정책 설정."""

    unapproved_retention_days: int = CLEANUP_UNAPPROVED_DAYS
    max_approved_per_ticker: int = CLEANUP_MAX_APPROVED_PER_TICKER
    keep_latest_failed: bool = True  # 최근 실패 1개 보존 (회귀 분석용)


class PolicyRegistry(BaseModel):
    """RL 정책 통합 인덱스.

    artifacts/rl/models/registry.json에 저장됩니다.
    """

    version: int = 1
    tickers: dict[str, TickerPolicies] = Field(default_factory=dict)
    promotion_gate: PromotionGate = Field(default_factory=PromotionGate)
    cleanup_policy: CleanupPolicy = Field(default_factory=CleanupPolicy)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_ticker(self, ticker: str) -> TickerPolicies:
        """종목별 정책 목록을 반환합니다. 없으면 빈 목록을 생성합니다."""
        if ticker not in self.tickers:
            self.tickers[ticker] = TickerPolicies()
        return self.tickers[ticker]

    def get_active_policy(self, ticker: str) -> Optional[PolicyEntry]:
        """종목의 활성 정책을 반환합니다."""
        tp = self.tickers.get(ticker)
        if not tp:
            return None
        return tp.get_active_policy()

    def list_all_tickers(self) -> list[str]:
        """등록된 모든 종목을 반환합니다."""
        return list(self.tickers.keys())

    def list_active_policies(self) -> dict[str, Optional[str]]:
        """모든 종목의 활성 policy_id를 반환합니다."""
        return {
            ticker: tp.active_policy_id
            for ticker, tp in self.tickers.items()
        }

    def register_policy(self, entry: PolicyEntry) -> None:
        """정책을 등록합니다."""
        tp = self.get_ticker(entry.ticker)
        tp.add_policy(entry)
        self.last_updated = datetime.now(timezone.utc)

    def promote_policy(
        self,
        ticker: str,
        policy_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """정책을 활성 상태로 승격합니다.

        승격 게이트 조건:
        - return_pct > 현재 활성 정책의 return_pct (또는 활성 정책이 없을 때)
        - max_drawdown_pct >= promotion_gate.max_drawdown_limit_pct
        - approved == True

        Args:
            ticker: 종목 코드
            policy_id: 승격할 정책 ID
            force: True이면 게이트 조건 무시 (수동 승인)

        Returns:
            승격 성공 여부
        """
        tp = self.get_ticker(ticker)
        candidate = tp.get_policy(policy_id)
        if not candidate:
            return False

        if not force:
            # 승인된 정책만 승격 가능
            if not candidate.approved:
                return False
            # max_drawdown 체크
            if candidate.max_drawdown_pct < self.promotion_gate.max_drawdown_limit_pct:
                return False
            # 기존 활성 정책보다 수익률이 높아야 함
            current_active = tp.get_active_policy()
            if current_active and candidate.return_pct <= current_active.return_pct:
                return False

        tp.active_policy_id = policy_id
        self.last_updated = datetime.now(timezone.utc)
        return True

    def total_policy_count(self) -> int:
        """전체 정책 수를 반환합니다."""
        return sum(len(tp.policies) for tp in self.tickers.values())


def algorithm_dir_name(algorithm: str) -> str:
    """알고리즘 이름을 디렉토리 이름으로 변환합니다.

    tabular_q_learning → tabular
    dqn → dqn
    ppo → ppo
    """
    mapping = {
        "tabular_q_learning": "tabular",
        "dqn": "dqn",
        "ppo": "ppo",
    }
    return mapping.get(algorithm, algorithm.split("_")[0])


def build_relative_path(algorithm: str, ticker: str, policy_id: str) -> str:
    """registry.json 기준 상대 파일 경로를 생성합니다.

    예: "tabular/259960.KS/rl_259960.KS_20260314T061942Z.json"
    """
    algo_dir = algorithm_dir_name(algorithm)
    return f"{algo_dir}/{ticker}/{policy_id}.json"
