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

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.rl_policy_registry import (
    PolicyEntry,
    PolicyRegistry,
    algorithm_dir_name,
    build_relative_path,
)


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
        ticker=data.get("ticker", "unknown"),
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
    """마이그레이션을 실행합니다."""
    mode = "EXECUTE" if execute else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  RL 정책 마이그레이션 ({mode})")
    print(f"{'='*60}\n")

    # 1. 레거시 정책 수집
    legacy = discover_legacy_policies()
    intermediate = discover_intermediate_policies()
    v1_active = load_v1_active_policies()

    print(f"레거시 정책 (artifacts/rl/*.json): {len(legacy)}개")
    print(f"중간 구조 정책 (artifacts/rl/models/<ticker>/*.json): {len(intermediate)}개")
    print(f"V1 활성 정책: {list(v1_active.keys())}\n")

    # 중복 제거: policy_id 기준으로 최신 파일 우선
    all_policies: dict[str, tuple[Path, dict]] = {}

    for path, data in legacy:
        pid = data["policy_id"]
        if pid not in all_policies:
            all_policies[pid] = (path, data)

    for path, data in intermediate:
        pid = data["policy_id"]
        # 중간 구조가 레거시보다 우선 (더 나중에 복사된 것)
        all_policies[pid] = (path, data)

    print(f"고유 정책 (중복 제거 후): {len(all_policies)}개\n")

    # 2. 레지스트리 구성
    registry = PolicyRegistry()
    migrated = 0
    skipped = 0

    for pid, (source_path, data) in sorted(all_policies.items()):
        ticker = data.get("ticker", "unknown")
        algorithm = data.get("algorithm", "tabular_q_learning")

        # 대상 경로 계산
        relative_path = build_relative_path(algorithm, ticker, pid)
        target_path = MODELS_DIR / relative_path

        # 파일 복사/이동
        if target_path.exists() and target_path != source_path:
            print(f"  [SKIP] 이미 존재: {relative_path}")
            skipped += 1
        elif target_path == source_path:
            print(f"  [KEEP] 이미 올바른 위치: {relative_path}")
        else:
            print(f"  [COPY] {source_path.relative_to(ROOT)} → {relative_path}")
            if execute:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                # artifact_path도 업데이트
                data["artifact_path"] = str(target_path)
                target_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            migrated += 1

        # 레지스트리에 등록
        entry = policy_to_entry(data, relative_path)
        registry.register_policy(entry)

    # 3. V1 활성 정책 반영
    print(f"\n활성 정책 매핑:")
    for ticker, info in v1_active.items():
        active_pid = info.get("policy_id")
        if active_pid:
            tp = registry.get_ticker(ticker)
            entry = tp.get_policy(active_pid)
            if entry:
                tp.active_policy_id = active_pid
                print(f"  {ticker} → {active_pid} (V1에서 이전)")
            else:
                print(f"  {ticker} → {active_pid} (레지스트리에 없음, 무시)")

    # 4. 빈 알고리즘 디렉토리 생성
    for algo_dir in ["tabular", "dqn", "ppo"]:
        dir_path = MODELS_DIR / algo_dir
        if not dir_path.exists():
            print(f"\n  [MKDIR] {algo_dir}/")
            if execute:
                dir_path.mkdir(parents=True, exist_ok=True)

    # 5. registry.json 저장
    print(f"\nregistry.json 저장:")
    print(f"  종목 수: {len(registry.tickers)}")
    print(f"  정책 수: {registry.total_policy_count()}")
    print(f"  활성 정책: {registry.list_active_policies()}")

    if execute:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        payload = registry.model_dump(mode="json")
        REGISTRY_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  → {REGISTRY_PATH.relative_to(ROOT)} 저장 완료")

    # 6. 레거시 파일 정리 (선택)
    if clean:
        print(f"\n레거시 파일 정리:")
        for path, _ in legacy:
            print(f"  [DEL] {path.relative_to(ROOT)}")
            if execute:
                path.unlink()

        # 중간 구조의 빈 디렉토리 정리
        for ticker_dir in sorted(MODELS_DIR.iterdir()):
            if not ticker_dir.is_dir():
                continue
            if ticker_dir.name in {"tabular", "dqn", "ppo"}:
                continue
            # 이미 tabular로 복사되었으므로 제거 가능
            for f in ticker_dir.glob("*.json"):
                print(f"  [DEL] {f.relative_to(ROOT)}")
                if execute:
                    f.unlink()
            if execute and not any(ticker_dir.iterdir()):
                ticker_dir.rmdir()
                print(f"  [RMDIR] {ticker_dir.relative_to(ROOT)}")

    # 요약
    print(f"\n{'='*60}")
    print(f"  마이그레이션 완료 요약 ({mode})")
    print(f"{'='*60}")
    print(f"  복사/이동: {migrated}개")
    print(f"  스킵 (이미 존재): {skipped}개")
    print(f"  레지스트리 등록: {registry.total_policy_count()}개")
    if not execute:
        print(f"\n  실제 실행하려면 --execute 플래그를 추가하세요.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RL 정책 아티팩트를 새 디렉토리 구조로 마이그레이션합니다."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 마이그레이션을 실행합니다 (기본: dry-run)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="마이그레이션 후 레거시 파일을 정리합니다",
    )
    args = parser.parse_args()
    run_migration(execute=args.execute, clean=args.clean)


if __name__ == "__main__":
    main()
