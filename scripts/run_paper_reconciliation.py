"""
scripts/run_paper_reconciliation.py — KIS paper 계좌 reconciliation 실행기
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.notifier import NotifierAgent
from src.services.paper_reconciliation import reconcile_kis_paper_account


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


async def _main(args: argparse.Namespace) -> int:
    report_date = _parse_date(args.report_date)
    result = await reconcile_kis_paper_account(report_date=report_date, record_audit=not args.no_audit)

    if args.send_report:
        notifier = NotifierAgent()
        await notifier.send_paper_daily_report(report_date=report_date, reconciliation=result)

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS paper reconciliation 실행")
    parser.add_argument("--report-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--send-report", action="store_true", help="일일 리포트 전송")
    parser.add_argument("--no-audit", action="store_true", help="operational_audits 기록 생략")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
