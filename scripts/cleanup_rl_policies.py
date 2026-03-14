#!/usr/bin/env python3
"""
scripts/cleanup_rl_policies.py — RL 정책 자동 정리 스크립트

정리 규칙 (registry.json의 cleanup_policy 기준):
- 미승인 정책: 30일 경과 시 삭제 (최근 실패 1개는 보존)
- 승인 정책: 종목당 최대 5개 보존 (활성 정책 제외)
- 활성 정책: 삭제 불가

사용법:
    python scripts/cleanup_rl_policies.py              # dry-run
    python scripts/cleanup_rl_policies.py --execute     # 실제 삭제
    python scripts/cleanup_rl_policies.py --stats       # 통계만 출력
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.rl_policy_store_v2 import RLPolicyStoreV2


def print_stats(store: RLPolicyStoreV2) -> None:
    """레지스트리 통계를 출력합니다."""
    registry = store.load_registry()
    print(f"\n{'='*50}")
    print(f"  RL 정책 레지스트리 통계")
    print(f"{'='*50}\n")
    print(f"  레지스트리 버전: {registry.version}")
    print(f"  마지막 업데이트: {registry.last_updated}")
    print(f"  총 종목: {len(registry.tickers)}")
    print(f"  총 정책: {registry.total_policy_count()}")
    print()

    for ticker, tp in sorted(registry.tickers.items()):
        active = tp.active_policy_id or "(없음)"
        approved_count = sum(1 for p in tp.policies if p.approved)
        unapproved_count = len(tp.policies) - approved_count
        print(f"  [{ticker}]")
        print(f"    활성: {active}")
        print(f"    승인: {approved_count}개, 미승인: {unapproved_count}개")

        for p in sorted(tp.policies, key=lambda x: x.created_at, reverse=True):
            status = "ACTIVE" if p.policy_id == tp.active_policy_id else (
                "approved" if p.approved else "unapproved"
            )
            age = (datetime.now(timezone.utc) - p.created_at).days
            print(
                f"      {p.policy_id} | {status:>10} | ret={p.return_pct:+.2f}% | "
                f"mdd={p.max_drawdown_pct:.2f}% | {p.state_version} | {age}일 전"
            )
        print()


def run_cleanup(*, execute: bool = False) -> None:
    """정리를 실행합니다."""
    mode = "EXECUTE" if execute else "DRY-RUN"
    store = RLPolicyStoreV2(auto_save_registry=execute)

    print(f"\n{'='*50}")
    print(f"  RL 정책 자동 정리 ({mode})")
    print(f"{'='*50}\n")

    removed = store.cleanup(dry_run=not execute)

    if removed:
        print(f"\n정리 대상: {len(removed)}개")
        for pid in removed:
            print(f"  - {pid}")
    else:
        print("정리 대상 없음")

    if not execute and removed:
        print(f"\n실제 삭제하려면 --execute 플래그를 추가하세요.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RL 정책을 자동 정리합니다."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 삭제를 실행합니다 (기본: dry-run)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="레지스트리 통계만 출력합니다",
    )
    args = parser.parse_args()

    if args.stats:
        store = RLPolicyStoreV2()
        print_stats(store)
    else:
        run_cleanup(execute=args.execute)


if __name__ == "__main__":
    main()
