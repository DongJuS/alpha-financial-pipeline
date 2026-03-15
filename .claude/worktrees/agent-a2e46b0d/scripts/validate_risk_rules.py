"""
scripts/validate_risk_rules.py — 리스크 규칙 자동 검증 실행기

사용법:
    python scripts/validate_risk_rules.py
    python scripts/validate_risk_rules.py --no-record
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.queries import insert_operational_audit
from src.utils.risk_validation import run_risk_rule_validation


async def _main(record: bool) -> int:
    result = await run_risk_rule_validation()

    print("\n=== Risk Rule Validation ===")
    print("RESULT:", "PASS" if result["passed"] else "FAIL")
    print("SUMMARY:", result["summary"])
    for check in result["checks"]:
        icon = "✅" if check["ok"] else "❌"
        print(f"{icon} {check['key']}: {check['message']}")

    if record:
        await insert_operational_audit(
            audit_type="risk_rules",
            passed=bool(result["passed"]),
            summary=result["summary"],
            details=result,
            executed_by="scripts/validate_risk_rules.py",
        )
        print("AUDIT_RECORD: saved to operational_audits")

    return 0 if result["passed"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="리스크 규칙 자동 검증")
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="DB 감사 로그(operational_audits) 기록 없이 실행",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(record=not args.no_record)))


if __name__ == "__main__":
    main()
