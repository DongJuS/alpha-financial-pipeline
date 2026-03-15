"""
scripts/promote_strategy.py — 전략 승격 CLI

사용법:
    python scripts/promote_strategy.py --strategy A --from virtual --to paper
    python scripts/promote_strategy.py --strategy A --check
    python scripts/promote_strategy.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.utils.logging import get_logger, setup_logging
from src.utils.strategy_promotion import StrategyPromoter

setup_logging()
logger = get_logger(__name__)


async def run_promote(args: argparse.Namespace) -> None:
    promoter = StrategyPromoter()

    if args.list:
        statuses = await promoter.get_all_strategy_status()
        print("\n=== 전략 모드 현황 ===\n")
        for s in statuses:
            modes = s["active_modes"] or ["(없음)"]
            print(f"  {s['strategy_id']:>4s}: {', '.join(modes)}")
            for path, info in s.get("promotion_readiness", {}).items():
                status = "✅ 준비 완료" if info["ready"] else "❌ 미충족"
                print(f"         {path}: {status}")
                if info.get("failures"):
                    for f in info["failures"]:
                        print(f"           - {f}")
        print()
        return

    if not args.strategy:
        logger.error("--strategy 옵션을 지정하세요 (A, B, RL, S, L)")
        sys.exit(1)

    strategy_id = args.strategy.upper()

    if args.check:
        # 가능한 모든 승격 경로 평가
        for from_m, to_m in [("virtual", "paper"), ("paper", "real")]:
            check = await promoter.evaluate_promotion_readiness(strategy_id, from_m, to_m)
            status = "✅ 준비 완료" if check.ready else "❌ 미충족"
            print(f"\n[{strategy_id}] {from_m} → {to_m}: {status}")
            print(f"  기준: {json.dumps(check.criteria, ensure_ascii=False)}")
            print(f"  실제: {json.dumps(check.actual, ensure_ascii=False)}")
            if check.failures:
                for f in check.failures:
                    print(f"  ❌ {f}")
        return

    if not args.from_mode or not args.to_mode:
        logger.error("--from 및 --to 옵션을 지정하세요 (virtual, paper, real)")
        sys.exit(1)

    result = await promoter.promote_strategy(
        strategy_id=strategy_id,
        from_mode=args.from_mode,
        to_mode=args.to_mode,
        force=args.force,
        approved_by="cli_user",
    )

    if result.success:
        print(f"\n✅ {result.message}")
    else:
        print(f"\n❌ {result.message}")
        if result.check and result.check.failures:
            for f in result.check.failures:
                print(f"  - {f}")
        if not args.force:
            print("\n  --force 옵션으로 강제 승격할 수 있습니다.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="전략 모드 승격 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--strategy", default="", help="전략 ID (A, B, RL, S, L)")
    parser.add_argument("--from", dest="from_mode", default="", help="현재 모드 (virtual, paper)")
    parser.add_argument("--to", dest="to_mode", default="", help="승격 대상 모드 (paper, real)")
    parser.add_argument("--check", action="store_true", help="승격 준비 상태만 확인 (실행 안 함)")
    parser.add_argument("--list", action="store_true", help="전체 전략 모드 현황 표시")
    parser.add_argument("--force", action="store_true", help="기준 미충족 시에도 강제 승격")
    args = parser.parse_args()
    asyncio.run(run_promote(args))


if __name__ == "__main__":
    main()
