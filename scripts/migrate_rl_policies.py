#!/usr/bin/env python3
"""
scripts/migrate_rl_policies.py — RL 정책 아티팩트 마이그레이션

기존 구조:
    artifacts/rl/<policy_id>.json                    (V1 직접 저장)
    artifacts/rl/models/<ticker>/<policy_id>.json     (V2 수동 복사)
    artifacts/rl/active_policies.json                 (V1 활성 정책 레지스트리)

새 구조:
    artifacts/rl/models/tabular/<ticker>/<policy_id>.json
    artifacts/rl/models/dqn/<ticker>/...
    artifacts/rl/models/ppo/<ticker>/...
    artifacts/rl/models/registry.json

마이그레이션 단계:
1. artifacts/rl/*.json (레거시) → artifacts/rl/models/<algo>/<ticker>/ 로 복사
2. artifacts/rl/models/<ticker>/*.json (중간 구조) → artifacts/rl/models/<algo>/<ticker>/ 로 이동
3. registry.json 생성 (모든 정책 메타데이터 + 활성 정책 포인터)
4. active_policies.json의 활성 정책을 registry.json에 반영

사용법:
    python scripts/migrate_rl_policies.py                    # dry-run (변경 없음)
    python scripts/migrate_rl_policies.py --execute          # 실제 마이그레이션
    python scripts/migrate_rl_policies.py --execute --clean  # 마이그레이션 + 레거시 파일 정리
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.rl_policy_registry import (
    PolicyEntry,
)

# 주의: PolicyRegistry 클래스가 제거됨 (DB 전환).
# 이 스크립트는 V1→V2 파일 마이그레이션용이며, DB 마이그레이션은
# scripts/db/migrate_rl_registry.py 를 사용한다.
# registry.json 재생성이 필요하면 이 스크립트의 registry 관련 로직을 제거하고
# 파일 복사만 수행하도록 수정해야 한다.
_DEPRECATED = True


ARTIFACTS_DIR = ROOT / "artifacts" / "rl"
MODELS_DIR = ARTIFACTS_DIR / "models"
LEGACY_ACTIVE_PATH = ARTIFACTS_DIR / "active_policies.json"
REGISTRY_PATH = MODELS_DIR / "registry.json"

# 마이그레이션에서 무시할 파일
SKIP_FILES = {"active_policies.json"}


def discover_legacy_policies() -> list[tuple[Path, dict]]:
    """artifacts/rl/*.json에서 레거시 정책 파일을 찾습니다."""
    results = []
    for path in sorted(ARTIFACTS_DIR.glob("*.json")):
        if path.name in SKIP_FILES:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "policy_id" in data and "q_table" in data:
                results.append((path, data))
        except Exception as exc:
            print(f"  [WARN] 파싱 실패 (무시): {path.name} — {exc}")
    return results


def discover_intermediate_policies() -> list[tuple[Path, dict]]:
    """artifacts/rl/models/<ticker>/*.json에서 중간 구조 정책을 찾습니다."""
    results = []
    for ticker_dir in sorted(MODELS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        # 알고리즘 디렉토리(tabular/, dqn/ 등)는 건너뜀
        if ticker_dir.name in {"tabular", "dqn", "ppo"}:
            continue
        for path in sorted(ticker_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "policy_id" in data and "q_table" in data:
                    results.append((path, data))
            except Exception as exc:
                print(f"  [WARN] 파싱 실패 (무시): {path} — {exc}")
    return results


def load_v1_active_policies() -> dict[str, dict]:
    """V1 active_policies.json을 로드합니다."""
    if not LEGACY_ACTIVE_PATH.exists():
        return {}
    try:
        data = json.loads(LEGACY_ACTIVE_PATH.read_text(encoding="utf-8"))
        return data.get("policies", {})
    except Exception:
        return {}


def policy_to_entry(data: dict, relative_path: str) -> PolicyEntry:
    """정책 JSON을 PolicyEntry로 변환합니다."""
    ev = data.get("evaluation", {})
    created_at_str = data.get("created_at", "")
    try:
        created_at = datetime.fromisoformat(created_at_str)
    except (ValueError, TypeError):
        created_at = datetime.now(timezone.utc)

    return PolicyEntry(
        policy_id=data["policy_id"],
        instrument_id=data.get("ticker", "unknown"),
        algorithm=data.get("algorithm", "tabular_q_learning"),
        state_version=data.get("state_version", "qlearn_v1"),
        return_pct=ev.get("total_return_pct", 0.0),
        baseline_return_pct=ev.get("baseline_return_pct", 0.0),
        excess_return_pct=ev.get("excess_return_pct", 0.0),
        max_drawdown_pct=ev.get("max_drawdown_pct", 0.0),
        trades=ev.get("trades", 0),
        win_rate=ev.get("win_rate", 0.0),
        holdout_steps=ev.get("holdout_steps", 0),
        approved=ev.get("approved", False),
        created_at=created_at,
        file_path=relative_path,
        lookback=int(data.get("lookback", 6)),
        episodes=int(data.get("episodes", 60)),
        learning_rate=float(data.get("learning_rate", 0.18)),
        discount_factor=float(data.get("discount_factor", 0.92)),
        epsilon=float(data.get("epsilon", 0.15)),
        trade_penalty_bps=int(data.get("trade_penalty_bps", 5)),
    )


def run_migration(*, execute: bool = False, clean: bool = False) -> None:
    """마이그레이션을 실행합니다.

    DEPRECATED: registry.json 기반 마이그레이션. DB 마이그레이션은
    scripts/db/migrate_rl_registry.py 를 사용하세요.
    PolicyRegistry 클래스가 제거되어(DB 전환) 이 함수는 더 이상 동작하지 않습니다.
    """
    print("\n[DEPRECATED] 이 스크립트는 registry.json 기반입니다.")
    print("DB 마이그레이션은 scripts/db/migrate_rl_registry.py 를 사용하세요.\n")


def main() -> None:
    print("[DEPRECATED] 이 스크립트는 registry.json 기반이며 더 이상 사용되지 않습니다.")
    print("DB 마이그레이션: python scripts/db/migrate_rl_registry.py")
    sys.exit(1)


if __name__ == "__main__":
    main()
