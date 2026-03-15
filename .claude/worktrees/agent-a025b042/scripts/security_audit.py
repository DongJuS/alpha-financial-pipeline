"""
scripts/security_audit.py — 저장소 보안 감사 실행기

사용법:
    python scripts/security_audit.py
    python scripts/security_audit.py --no-record
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
from src.utils.security_audit import run_repository_security_audit


async def _main(record: bool) -> int:
    result = run_repository_security_audit(ROOT)

    print("\n=== Security Audit ===")
    print("RESULT:", "PASS" if result["passed"] else "FAIL")
    print("SUMMARY:", result["summary"])

    if result["failures"]:
        print("- Failures")
        for item in result["failures"]:
            print(f"  - {item}")

    if result["warnings"]:
        print("- Warnings")
        for item in result["warnings"]:
            print(f"  - {item}")

    findings = result["secret_scan"]["findings"]
    if findings:
        print("- Secret Findings")
        for f in findings[:20]:
            print(f"  - [{f['type']}] {f['path']}:{f['line']}")

    print(
        "SCANNED_FILES:",
        result["secret_scan"]["scanned_files"],
        "| FINDINGS:",
        len(findings),
    )

    if record:
        await insert_operational_audit(
            audit_type="security",
            passed=bool(result["passed"]),
            summary=result["summary"],
            details=result,
            executed_by="scripts/security_audit.py",
        )
        print("AUDIT_RECORD: saved to operational_audits")

    return 0 if result["passed"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="저장소 보안 감사")
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="DB 감사 로그(operational_audits) 기록 없이 실행",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(record=not args.no_record)))


if __name__ == "__main__":
    main()
