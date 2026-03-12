"""
scripts/preflight_real_trading.py — 실거래 전환 사전 점검

사용법:
    python scripts/preflight_real_trading.py
    python scripts/preflight_real_trading.py --skip-audits
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
from src.utils.readiness import evaluate_real_trading_readiness
from src.utils.risk_validation import run_risk_rule_validation
from src.utils.security_audit import run_repository_security_audit


async def _run_operational_audits() -> None:
    print("\n=== Operational Audits (security + risk_rules) ===")

    security_result = run_repository_security_audit(ROOT)
    await insert_operational_audit(
        audit_type="security",
        passed=bool(security_result["passed"]),
        summary=security_result["summary"],
        details=security_result,
        executed_by="scripts/preflight_real_trading.py",
    )
    print(
        f"[security] {'PASS' if security_result['passed'] else 'FAIL'} - {security_result['summary']}"
    )

    risk_result = await run_risk_rule_validation()
    await insert_operational_audit(
        audit_type="risk_rules",
        passed=bool(risk_result["passed"]),
        summary=risk_result["summary"],
        details=risk_result,
        executed_by="scripts/preflight_real_trading.py",
    )
    print(f"[risk_rules] {'PASS' if risk_result['passed'] else 'FAIL'} - {risk_result['summary']}")


async def _main(skip_audits: bool) -> int:
    if not skip_audits:
        await _run_operational_audits()

    result = await evaluate_real_trading_readiness()
    print("\n=== Real Trading Readiness ===")
    for check in result["checks"]:
        icon = "✅" if check["ok"] else "❌"
        print(f"{icon} [{check['severity']}] {check['key']}: {check['message']}")
    print("------------------------------")
    print(
        "READY =", result["ready"],
        "| critical_ok =", result["critical_ok"],
        "| high_ok =", result["high_ok"],
    )
    return 0 if result["ready"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="실거래 전환 사전 점검")
    parser.add_argument(
        "--skip-audits",
        action="store_true",
        help="운영 감사(security/risk_rules) 실행 및 기록을 생략",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(skip_audits=args.skip_audits)))


if __name__ == "__main__":
    main()
