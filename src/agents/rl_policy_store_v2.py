"""
src/agents/rl_policy_store_v2.py — RLPolicyStoreV2

V1 RLPolicyStore를 대체하지 않고 확장합니다.
저장 경로: artifacts/rl/models/<algorithm>/<ticker>/<policy_id>.json
인덱스: artifacts/rl/models/registry.json

V1과의 호환:
- V1 active_policies.json도 함께 읽을 수 있음 (마이그레이션 기간)
- registry.json이 single source of truth
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agents.rl_policy_registry import (
    CleanupPolicy,
    PolicyEntry,
    PolicyRegistry,
    PromotionGate,
    algorithm_dir_name,
    build_relative_path,
)
from src.agents.rl_trading import RLPolicyArtifact
from src.utils.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = ROOT / "artifacts" / "rl" / "models"
LEGACY_ARTIFACTS_DIR = ROOT / "artifacts" / "rl"


class RLPolicyStoreV2:
    """V2 정책 저장소.

    - 저장 경로: models/<algorithm>/<ticker>/<policy_id>.json
    - 인덱스: models/registry.json
    - V1 active_policies.json 후방 호환 읽기 지원
    """

    def __init__(
        self,
        models_dir: Path | None = None,
        *,
        auto_save_registry: bool = True,
    ) -> None:
        self.models_dir = Path(models_dir or DEFAULT_MODELS_DIR)
        self.registry_path = self.models_dir / "registry.json"
        self.auto_save_registry = auto_save_registry
        self._registry: PolicyRegistry | None = None

    # ──────────────────────────── Registry I/O ────────────────────────────

    def load_registry(self) -> PolicyRegistry:
        """registry.json을 로드합니다. 없으면 빈 레지스트리를 생성합니다."""
        if self._registry is not None:
            return self._registry

        if self.registry_path.exists():
            try:
                data = json.loads(self.registry_path.read_text(encoding="utf-8"))
                self._registry = PolicyRegistry.model_validate(data)
            except Exception as exc:
                logger.warning("registry.json 파싱 실패, 빈 레지스트리 생성: %s", exc)
                self._registry = PolicyRegistry()
        else:
            self._registry = PolicyRegistry()

        return self._registry

    def save_registry(self) -> None:
        """registry.json을 저장합니다."""
        registry = self.load_registry()
        registry.last_updated = datetime.now(timezone.utc)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        payload = registry.model_dump(mode="json")
        self.registry_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _maybe_save(self) -> None:
        """auto_save_registry가 True이면 저장합니다."""
        if self.auto_save_registry:
            self.save_registry()

    # ──────────────────────────── Policy CRUD ────────────────────────────

    def save_policy(
        self,
        artifact: RLPolicyArtifact,
        *,
        run_id: str | None = None,
    ) -> RLPolicyArtifact:
        """정책 아티팩트를 파일로 저장하고 레지스트리에 등록합니다.

        저장 경로: models/<algorithm>/<ticker>/<policy_id>.json

        Args:
            artifact: 저장할 정책 아티팩트
            run_id: 실험 run ID (양방향 참조용)
        """
        registry = self.load_registry()

        # 디렉토리 생성
        algo_dir = algorithm_dir_name(artifact.algorithm)
        ticker_dir = self.models_dir / algo_dir / artifact.ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        # 파일 저장
        file_path = ticker_dir / f"{artifact.policy_id}.json"
        payload = artifact.to_dict()
        payload["artifact_path"] = str(file_path)
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifact.artifact_path = str(file_path)

        # 레지스트리 등록
        relative_path = build_relative_path(
            artifact.algorithm, artifact.ticker, artifact.policy_id
        )
        entry = PolicyEntry(
            policy_id=artifact.policy_id,
            ticker=artifact.ticker,
            algorithm=artifact.algorithm,
            state_version=artifact.state_version,
            return_pct=artifact.evaluation.total_return_pct,
            baseline_return_pct=artifact.evaluation.baseline_return_pct,
            excess_return_pct=artifact.evaluation.excess_return_pct,
            max_drawdown_pct=artifact.evaluation.max_drawdown_pct,
            trades=artifact.evaluation.trades,
            win_rate=artifact.evaluation.win_rate,
            holdout_steps=artifact.evaluation.holdout_steps,
            approved=artifact.evaluation.approved,
            created_at=datetime.fromisoformat(artifact.created_at),
            file_path=relative_path,
            lookback=artifact.lookback,
            episodes=artifact.episodes,
            learning_rate=artifact.learning_rate,
            discount_factor=artifact.discount_factor,
            epsilon=artifact.epsilon,
            trade_penalty_bps=artifact.trade_penalty_bps,
            run_id=run_id,
        )
        registry.register_policy(entry)
        self._maybe_save()

        logger.info(
            "정책 저장 완료: %s → %s", artifact.policy_id, relative_path
        )
        return artifact

    def load_policy(self, policy_id: str, ticker: str | None = None) -> Optional[RLPolicyArtifact]:
        """policy_id로 정책을 로드합니다.

        레지스트리에서 file_path를 조회하여 로드합니다.
        ticker가 제공되면 해당 종목에서만 검색합니다.
        """
        registry = self.load_registry()
        entry = self._find_entry(registry, policy_id, ticker)
        if not entry:
            return None
        return self._load_artifact_from_entry(entry)

    def load_active_policy(self, ticker: str) -> Optional[RLPolicyArtifact]:
        """종목의 활성 정책을 로드합니다."""
        registry = self.load_registry()
        entry = registry.get_active_policy(ticker)
        if not entry:
            # V1 호환: active_policies.json에서 시도
            return self._load_from_v1_active(ticker)
        return self._load_artifact_from_entry(entry)

    def activate_policy(self, artifact: RLPolicyArtifact) -> bool:
        """정책을 활성 상태로 승격합니다.

        승격 게이트를 통과해야 합니다.
        """
        registry = self.load_registry()
        success = registry.promote_policy(artifact.ticker, artifact.policy_id)
        if success:
            self._maybe_save()
            logger.info(
                "정책 승격 완료: %s (ticker=%s, return=%.2f%%)",
                artifact.policy_id,
                artifact.ticker,
                artifact.evaluation.total_return_pct,
            )
        else:
            logger.info(
                "정책 승격 실패 (게이트 미통과): %s (ticker=%s, return=%.2f%%)",
                artifact.policy_id,
                artifact.ticker,
                artifact.evaluation.total_return_pct,
            )
        return success

    def force_activate_policy(self, ticker: str, policy_id: str) -> bool:
        """강제 승격 (수동 승인용)."""
        registry = self.load_registry()
        success = registry.promote_policy(ticker, policy_id, force=True)
        if success:
            self._maybe_save()
            logger.info("정책 강제 승격: %s (ticker=%s)", policy_id, ticker)
        return success

    def list_active_policies(self) -> dict[str, Optional[str]]:
        """모든 종목의 활성 정책 ID를 반환합니다."""
        registry = self.load_registry()
        return registry.list_active_policies()

    def list_policies(self, ticker: str) -> list[PolicyEntry]:
        """종목의 모든 정책 엔트리를 반환합니다."""
        registry = self.load_registry()
        tp = registry.tickers.get(ticker)
        if not tp:
            return []
        return list(tp.policies)

    # ──────────────────────────── Cleanup ────────────────────────────

    def cleanup(
        self,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> list[str]:
        """자동 정리를 실행합니다.

        정리 규칙:
        - 미승인 정책: unapproved_retention_days 경과 시 삭제
        - 승인 정책: 종목당 max_approved_per_ticker개 초과 시 오래된 것부터 삭제
        - 활성 정책: 삭제 불가
        - keep_latest_failed=True이면 최근 미승인 1개 보존

        Returns:
            삭제된 policy_id 목록
        """
        registry = self.load_registry()
        cp = registry.cleanup_policy
        current_time = now or datetime.now(timezone.utc)
        removed: list[str] = []

        for ticker, tp in registry.tickers.items():
            # 1. 미승인 정책 정리
            unapproved = [
                p for p in tp.policies
                if not p.approved and p.policy_id != tp.active_policy_id
            ]
            # 생성일 기준 정렬 (최신 먼저)
            unapproved.sort(key=lambda p: p.created_at, reverse=True)

            for i, entry in enumerate(unapproved):
                # 최근 실패 1개 보존
                if cp.keep_latest_failed and i == 0:
                    continue
                age_days = (current_time - entry.created_at).total_seconds() / 86400
                if age_days > cp.unapproved_retention_days:
                    if not dry_run:
                        self._delete_policy_file(entry)
                        tp.remove_policy(entry.policy_id)
                    removed.append(entry.policy_id)
                    logger.info(
                        "정리 대상 (미승인 %d일 경과): %s",
                        int(age_days),
                        entry.policy_id,
                    )

            # 2. 승인 정책 수량 제한
            approved = [
                p for p in tp.policies
                if p.approved and p.policy_id != tp.active_policy_id
            ]
            approved.sort(key=lambda p: p.created_at, reverse=True)

            # 활성 정책 제외하고 max_approved_per_ticker - 1 개까지만 보존
            excess = approved[cp.max_approved_per_ticker - 1:]
            for entry in excess:
                if not dry_run:
                    self._delete_policy_file(entry)
                    tp.remove_policy(entry.policy_id)
                removed.append(entry.policy_id)
                logger.info(
                    "정리 대상 (승인 초과): %s", entry.policy_id
                )

        if removed and not dry_run:
            self._maybe_save()

        return removed

    # ──────────────────────────── Internal helpers ────────────────────────────

    def _find_entry(
        self,
        registry: PolicyRegistry,
        policy_id: str,
        ticker: str | None = None,
    ) -> Optional[PolicyEntry]:
        """레지스트리에서 policy_id로 엔트리를 찾습니다."""
        if ticker:
            tp = registry.tickers.get(ticker)
            if tp:
                return tp.get_policy(policy_id)
            return None
        # 전체 종목 검색
        for tp in registry.tickers.values():
            entry = tp.get_policy(policy_id)
            if entry:
                return entry
        return None

    def _load_artifact_from_entry(self, entry: PolicyEntry) -> Optional[RLPolicyArtifact]:
        """PolicyEntry의 file_path에서 아티팩트를 로드합니다."""
        file_path = self.models_dir / entry.file_path
        if not file_path.exists():
            logger.warning("정책 파일 없음: %s", file_path)
            return None
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            return RLPolicyArtifact.from_dict(payload)
        except Exception as exc:
            logger.error("정책 로드 실패 [%s]: %s", entry.policy_id, exc)
            return None

    def _load_from_v1_active(self, ticker: str) -> Optional[RLPolicyArtifact]:
        """V1 active_policies.json에서 활성 정책을 로드합니다 (후방 호환)."""
        v1_registry_path = LEGACY_ARTIFACTS_DIR / "active_policies.json"
        if not v1_registry_path.exists():
            return None
        try:
            data = json.loads(v1_registry_path.read_text(encoding="utf-8"))
            policy_info = data.get("policies", {}).get(ticker)
            if not policy_info:
                return None
            artifact_path = policy_info.get("artifact_path")
            if artifact_path and Path(artifact_path).exists():
                payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
                return RLPolicyArtifact.from_dict(payload)
            return None
        except Exception as exc:
            logger.warning("V1 active_policies.json 로드 실패: %s", exc)
            return None

    def _delete_policy_file(self, entry: PolicyEntry) -> None:
        """정책 파일을 삭제합니다."""
        file_path = self.models_dir / entry.file_path
        if file_path.exists():
            file_path.unlink()
            logger.info("정책 파일 삭제: %s", file_path)

    def _resolve_artifact_path(self, entry: PolicyEntry) -> Path:
        """엔트리의 절대 파일 경로를 반환합니다."""
        return self.models_dir / entry.file_path
