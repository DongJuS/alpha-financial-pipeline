#!/usr/bin/env python3
"""
scripts/cleanup_rl_policies.py — RL 정책 자동 정리 스크립트

정리 규칙 (DB 기반):
- 미승인 정책: 30일 경과 시 삭제
- 승인 정책: 종목당 최대 보존 개수 초과 시 오래된 것부터 삭제
- 활성 정책: 삭제 불가

사용법:
    python scripts/cleanup_rl_policies.py              # dry-run
    python scripts/cleanup_rl_policies.py --execute     # 실제 삭제
    python scripts/cleanup_rl_policies.py --stats       # 통계만 출력
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.rl_policy_store_v2 import RLPolicyStoreV2


async def _print_stats(store: RLPolicyStoreV2) -> None:
    """DB에서 정책 통계를 조회하여 출력합니다."""
    tickers = await store.list_all_tickers()
    active_map = await store.list_active_policies()

    total_policies = 0
    ticker_data: list[tuple[str, str, list]] = []  # (ticker, active_id, policies)

    for ticker in sorted(tickers):
        policies = await store.list_policies(ticker)
        total_policies += len(policies)
        active_id = active_map.get(ticker) or "(없음)"
        ticker_data.append((ticker, active_id, policies))

    print(f"\n{'='*50}")
    print("  RL 정책 레지스트리 통계")
    print(f"{'='*50}\n")
    print(f"  총 종목: {len(tickers)}")
    print(f"  총 정책: {total_policies}")
    print()

    for ticker, active_id, policies in ticker_data:
        approved_count = sum(1 for p in policies if p.approved)
        unapproved_count = len(policies) - approved_count
        print(f"  [{ticker}]")
        print(f"    활성: {active_id}")
        print(f"    승인: {approved_count}개, 미승인: {unapproved_count}개")

        for p in sorted(policies, key=lambda x: x.created_at, reverse=True):
            status = "ACTIVE" if p.is_active else (
                "approved" if p.approved else "unapproved"
            )
            age = (datetime.now(timezone.utc) - p.created_at).days
            print(
                f"      {p.policy_id} | {status:>10} | ret={p.return_pct:+.2f}% | "
                f"mdd={p.max_drawdown_pct:.2f}% | {p.state_version} | {age}일 전"
            )
        print()


def print_stats(store: RLPolicyStoreV2) -> None:
    """레지스트리 통계를 출력합니다."""
    asyncio.run(_print_stats(store))


async def _run_cleanup(*, execute: bool = False) -> None:
    """비동기 정리를 실행합니다."""
    store = RLPolicyStoreV2()
    mode = "EXECUTE" if execute else "DRY-RUN"

    print(f"\n{'='*50}")
    print(f"  RL 정책 자동 정리 ({mode})")
    print(f"{'='*50}\n")

    removed = await store.cleanup(dry_run=not execute)

    if removed:
        print(f"\n정리 대상: {len(removed)}개")
        for pid in removed:
            print(f"  - {pid}")
    else:
        print("정리 대상 없음")

    if not execute and removed:
        print("\n실제 삭제하려면 --execute 플래그를 추가하세요.")
    print()


def run_cleanup(*, execute: bool = False) -> None:
    """정리를 실행합니다."""
    asyncio.run(_run_cleanup(execute=execute))


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
        help="DB 정책 통계만 출력합니다",
    )
    args = parser.parse_args()

    if args.stats:
        store = RLPolicyStoreV2()
        print_stats(store)
    else:
        run_cleanup(execute=args.execute)


if __name__ == "__main__":
    main()
