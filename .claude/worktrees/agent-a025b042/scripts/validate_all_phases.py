"""
scripts/validate_all_phases.py — Phase 1~7 구현 완성도 자동 검증

주의:
- 본 검증은 "개발/운영 준비 상태"를 기준으로 합니다.
- 실계좌 자격증명 실효성(외부 API 실제 주문 가능)은 별도 점검 대상입니다.

사용법:
    python scripts/validate_all_phases.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.db_client import fetch, fetchrow, fetchval


@dataclass
class CheckResult:
    key: str
    ok: bool
    detail: str


def _percent(results: list[CheckResult]) -> int:
    if not results:
        return 0
    passed = sum(1 for r in results if r.ok)
    return int(round((passed / len(results)) * 100))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


async def phase1_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    table_count = int(await fetchval("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'"))
    checks.append(CheckResult("db:table_count", table_count >= 14, f"count={table_count}"))

    required_tables = {
        "users",
        "market_data",
        "predictions",
        "predictor_tournament_scores",
        "debate_transcripts",
        "portfolio_config",
        "portfolio_positions",
        "trade_history",
        "agent_heartbeats",
        "collector_errors",
        "notification_history",
        "real_trading_audit",
        "operational_audits",
        "paper_trading_runs",
    }
    rows = await fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    )
    exists = {r["tablename"] for r in rows}
    missing = sorted(required_tables - exists)
    checks.append(CheckResult("db:required_tables", len(missing) == 0, f"missing={missing}"))

    main_text = _read_text(ROOT / "src/api/main.py")
    checks.append(CheckResult("api:health_route", "@app.get(\"/health\"" in main_text, "health route exists"))

    return checks


async def phase2_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    files = [
        "src/agents/collector.py",
        "src/agents/predictor.py",
        "src/agents/portfolio_manager.py",
        "src/agents/notifier.py",
        "src/agents/orchestrator.py",
    ]
    for file in files:
        path = ROOT / file
        checks.append(CheckResult(f"agent:{path.stem}", path.exists(), file))

    hb_count = int(await fetchval("SELECT COUNT(*) FROM agent_heartbeats"))
    checks.append(CheckResult("heartbeat:records", hb_count >= 0, f"count={hb_count}"))
    return checks


async def phase3_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    text = _read_text(ROOT / "src/agents/orchestrator.py")
    checks.append(CheckResult("orchestrator:tournament_flag", "--tournament" in text, "cli flag"))

    ta_file = ROOT / "src/agents/strategy_a_tournament.py"
    checks.append(CheckResult("strategy_a:file", ta_file.exists(), str(ta_file)))

    test_file = ROOT / "test/test_strategy_a_tournament.py"
    checks.append(CheckResult("strategy_a:test", test_file.exists(), str(test_file)))

    score_rows = int(await fetchval("SELECT COUNT(*) FROM predictor_tournament_scores"))
    checks.append(CheckResult("strategy_a:score_table", score_rows >= 0, f"rows={score_rows}"))
    return checks


async def phase4_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    text = _read_text(ROOT / "src/agents/orchestrator.py")
    checks.append(CheckResult("orchestrator:consensus_flag", "--consensus" in text, "cli flag"))

    sb_file = ROOT / "src/agents/strategy_b_consensus.py"
    checks.append(CheckResult("strategy_b:file", sb_file.exists(), str(sb_file)))

    test_file = ROOT / "test/test_strategy_b_consensus.py"
    checks.append(CheckResult("strategy_b:test", test_file.exists(), str(test_file)))

    debate_rows = int(await fetchval("SELECT COUNT(*) FROM debate_transcripts"))
    checks.append(CheckResult("strategy_b:debate_table", debate_rows >= 0, f"rows={debate_rows}"))
    return checks


async def phase5_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    market_page = _read_text(ROOT / "ui/web/src/pages/Market.tsx")
    checks.append(CheckResult("ui:market_chart", "ComposedChart" in market_page or "LineChart" in market_page, "market chart"))

    dashboard_page = _read_text(ROOT / "ui/web/src/pages/Dashboard.tsx")
    dashboard_component = _read_text(ROOT / "ui/web/src/components/TossTradingDashboard.tsx")
    checks.append(
        CheckResult(
            "ui:dashboard_chart",
            "LineChart" in dashboard_page or "LineChart" in dashboard_component,
            "dashboard performance chart",
        )
    )

    settings_page = _read_text(ROOT / "ui/web/src/pages/Settings.tsx")
    checks.append(
        CheckResult(
            "ui:settings_api",
            "useUpdatePortfolioConfig" in settings_page and "useUpdateNotificationPreferences" in settings_page,
            "settings wired",
        )
    )

    portfolio_router = _read_text(ROOT / "src/api/routers/portfolio.py")
    checks.append(CheckResult("api:performance_series", "@router.get(\"/performance-series\"" in portfolio_router, "endpoint"))

    return checks


async def phase6_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    latest_baseline = await fetchrow(
        """
        SELECT simulated_days, passed, return_pct::float AS return_pct, benchmark_return_pct::float AS benchmark_return_pct
        FROM paper_trading_runs
        WHERE scenario = 'baseline'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    if latest_baseline:
        checks.append(
            CheckResult(
                "phase6:baseline_30d",
                bool(latest_baseline["passed"]) and int(latest_baseline["simulated_days"]) >= 30,
                f"days={latest_baseline['simulated_days']}, passed={latest_baseline['passed']}",
            )
        )
        checks.append(
            CheckResult(
                "phase6:benchmark_compare",
                latest_baseline["benchmark_return_pct"] is not None,
                f"strategy={latest_baseline['return_pct']}, benchmark={latest_baseline['benchmark_return_pct']}",
            )
        )
    else:
        checks.append(CheckResult("phase6:baseline_30d", False, "no baseline run"))
        checks.append(CheckResult("phase6:benchmark_compare", False, "no baseline run"))

    latest_high_vol = await fetchrow(
        """
        SELECT simulated_days, passed
        FROM paper_trading_runs
        WHERE scenario = 'high_volatility'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    checks.append(
        CheckResult(
            "phase6:high_volatility",
            bool(latest_high_vol and latest_high_vol["passed"]),
            "high_volatility scenario",
        )
    )

    latest_load = await fetchrow(
        """
        SELECT simulated_days, passed
        FROM paper_trading_runs
        WHERE scenario = 'load'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    checks.append(
        CheckResult(
            "phase6:load_test",
            bool(latest_load and latest_load["passed"]),
            "load scenario",
        )
    )

    latest_reconcile = await fetchrow(
        """
        SELECT passed
        FROM operational_audits
        WHERE audit_type = 'paper_reconciliation'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    checks.append(
        CheckResult(
            "phase6:paper_reconciliation",
            bool(latest_reconcile and latest_reconcile["passed"]),
            "latest paper_reconciliation audit",
        )
    )

    return checks


async def phase7_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []

    sec = await fetchrow(
        """
        SELECT passed
        FROM operational_audits
        WHERE audit_type = 'security'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    risk = await fetchrow(
        """
        SELECT passed
        FROM operational_audits
        WHERE audit_type = 'risk_rules'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )

    checks.append(CheckResult("phase7:security_audit", bool(sec and sec["passed"]), "latest security audit"))
    checks.append(CheckResult("phase7:risk_validation", bool(risk and risk["passed"]), "latest risk_rules audit"))

    guide = ROOT / "docs/REAL_TRADING_GUIDE.md"
    checks.append(CheckResult("phase7:guide", guide.exists(), str(guide)))

    portfolio_router = _read_text(ROOT / "src/api/routers/portfolio.py")
    checks.append(
        CheckResult(
            "phase7:readiness_guard",
            "evaluate_real_trading_readiness" in portfolio_router and "insert_real_trading_audit" in portfolio_router,
            "mode switch guard",
        )
    )

    return checks


async def main() -> int:
    phase_map: dict[str, list[CheckResult]] = {
        "Phase 1": await phase1_checks(),
        "Phase 2": await phase2_checks(),
        "Phase 3": await phase3_checks(),
        "Phase 4": await phase4_checks(),
        "Phase 5": await phase5_checks(),
        "Phase 6": await phase6_checks(),
        "Phase 7": await phase7_checks(),
    }

    print("\n=== Phase Completion Validation ===")
    all_ok = True
    for phase, checks in phase_map.items():
        pct = _percent(checks)
        phase_ok = pct == 100
        all_ok = all_ok and phase_ok
        print(f"{phase}: {pct}% {'✅' if phase_ok else '❌'}")
        for item in checks:
            icon = "  - ✅" if item.ok else "  - ❌"
            print(f"{icon} {item.key}: {item.detail}")

    print("-------------------------------")
    print("OVERALL:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
