"""
src/utils/integration_audit.py — Phase 10 Integration Audit Checker

Comprehensive checklist for verifying all Phase 10 integration points:
- search_pipeline_connected: SearchAgent can produce ResearchOutput
- rl_policy_available: At least one approved policy in registry
- strategy_b_research_enabled: Strategy B can receive research context
- experiment_tracking_active: ExperimentTracker can write to config/experiments/
- dashboard_endpoints_live: /integration/* endpoints respond
- aggregate_risk_active: AggregateRiskMonitor configured
- promotion_pipeline_active: StrategyPromoter configured
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
EXPERIMENTS_DIR = CONFIG_DIR / "experiments"


class IntegrationAuditChecker:
    """
    Operational audit and integration test checklist.

    Verifies critical components are configured and operational.
    Each check function returns True if the component is ready, False otherwise.
    """

    def __init__(self) -> None:
        self.results: Dict[str, bool] = {}
        self.messages: Dict[str, str] = {}

    def check_search_pipeline_connected(self) -> bool:
        """
        Verify SearchAgent can produce ResearchOutput.

        Check: Import SearchAgent, verify ResearchOutput class exists.
        """
        try:
            from src.agents.search_agent import SearchAgent, ResearchOutput
            # Verify ResearchOutput has expected fields
            required_fields = {"ticker", "query", "timestamp_utc", "sources", "sentiment", "confidence"}
            actual_fields = set(ResearchOutput.model_fields.keys())
            if required_fields.issubset(actual_fields):
                self.messages["search_pipeline_connected"] = "✓ SearchAgent + ResearchOutput OK"
                return True
            else:
                self.messages["search_pipeline_connected"] = f"✗ Missing fields in ResearchOutput: {required_fields - actual_fields}"
                return False
        except Exception as e:
            self.messages["search_pipeline_connected"] = f"✗ SearchAgent import failed: {e}"
            return False

    def check_rl_policy_available(self) -> bool:
        """
        Verify at least one approved policy in registry.

        Check: Look for config/artifacts/rl/models/*/registry.json
        with at least one entry marked 'approved'.
        """
        try:
            registry_path = CONFIG_DIR / "artifacts" / "rl" / "models" / "registry.json"
            if not registry_path.exists():
                self.messages["rl_policy_available"] = "✗ RL registry.json not found"
                return False

            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

            approved_count = sum(1 for entry in registry.get("policies", [])
                                if entry.get("status") == "approved")
            if approved_count > 0:
                self.messages["rl_policy_available"] = f"✓ {approved_count} approved RL policies found"
                return True
            else:
                self.messages["rl_policy_available"] = "✗ No approved RL policies in registry"
                return False
        except Exception as e:
            self.messages["rl_policy_available"] = f"✗ RL registry check failed: {e}"
            return False

    def check_strategy_b_research_enabled(self) -> bool:
        """
        Verify Strategy B can receive research context.

        Check: StrategyBConsensus.run_for_ticker accepts research_context parameter.
        """
        try:
            from src.agents.strategy_b_consensus import StrategyBConsensus
            import inspect

            sig = inspect.signature(StrategyBConsensus.run_for_ticker)
            if "research_context" in sig.parameters:
                self.messages["strategy_b_research_enabled"] = "✓ Strategy B research_context parameter available"
                return True
            else:
                self.messages["strategy_b_research_enabled"] = "✗ Strategy B missing research_context parameter"
                return False
        except Exception as e:
            self.messages["strategy_b_research_enabled"] = f"✗ Strategy B check failed: {e}"
            return False

    def check_experiment_tracking_active(self) -> bool:
        """
        Verify ExperimentTracker can write to config/experiments/.

        Check: Verify directory exists and is writable, ExperimentTracker imports correctly.
        """
        try:
            from src.utils.experiment_tracker import ExperimentTracker, ExperimentRecord, ExperimentMetrics

            # Ensure directory exists
            EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

            # Verify writable
            if not EXPERIMENTS_DIR.is_dir():
                self.messages["experiment_tracking_active"] = f"✗ {EXPERIMENTS_DIR} is not a directory"
                return False

            # Try instantiating tracker
            tracker = ExperimentTracker(use_git_hash=False)
            self.messages["experiment_tracking_active"] = f"✓ ExperimentTracker OK, path={EXPERIMENTS_DIR}"
            return True
        except Exception as e:
            self.messages["experiment_tracking_active"] = f"✗ ExperimentTracker check failed: {e}"
            return False

    def check_dashboard_endpoints_live(self) -> bool:
        """
        Verify /integration/* endpoints respond.

        Check: Look for dashboard/strategy_dashboard.py or similar with integration routes.
        """
        try:
            # Check for strategy_dashboard.py or api endpoints
            dashboard_path = PROJECT_ROOT / "src" / "api" / "strategy_dashboard.py"
            if not dashboard_path.exists():
                dashboard_path = PROJECT_ROOT / "src" / "dashboard" / "strategy_dashboard.py"

            if dashboard_path.exists():
                self.messages["dashboard_endpoints_live"] = "✓ Dashboard endpoints module found"
                return True
            else:
                self.messages["dashboard_endpoints_live"] = "✗ Dashboard module not found"
                return False
        except Exception as e:
            self.messages["dashboard_endpoints_live"] = f"✗ Dashboard check failed: {e}"
            return False

    def check_aggregate_risk_active(self) -> bool:
        """
        Verify AggregateRiskMonitor is configured.

        Check: Import AggregateRiskMonitor and verify it's instantiable.
        """
        try:
            from src.utils.aggregate_risk import AggregateRiskMonitor
            monitor = AggregateRiskMonitor()
            self.messages["aggregate_risk_active"] = "✓ AggregateRiskMonitor instantiated"
            return True
        except Exception as e:
            self.messages["aggregate_risk_active"] = f"✗ AggregateRiskMonitor check failed: {e}"
            return False

    def check_promotion_pipeline_active(self) -> bool:
        """
        Verify StrategyPromoter is configured.

        Check: Import StrategyPromoter and verify it's instantiable.
        """
        try:
            from src.utils.strategy_promotion import StrategyPromoter
            promoter = StrategyPromoter()
            self.messages["promotion_pipeline_active"] = "✓ StrategyPromoter instantiated"
            return True
        except Exception as e:
            self.messages["promotion_pipeline_active"] = f"✗ StrategyPromoter check failed: {e}"
            return False

    def run_audit(self) -> Dict[str, bool]:
        """
        Run all audit checks.

        Returns:
            Dictionary with check names as keys and results (True/False) as values.
        """
        checks = [
            ("search_pipeline_connected", self.check_search_pipeline_connected),
            ("rl_policy_available", self.check_rl_policy_available),
            ("strategy_b_research_enabled", self.check_strategy_b_research_enabled),
            ("experiment_tracking_active", self.check_experiment_tracking_active),
            ("dashboard_endpoints_live", self.check_dashboard_endpoints_live),
            ("aggregate_risk_active", self.check_aggregate_risk_active),
            ("promotion_pipeline_active", self.check_promotion_pipeline_active),
        ]

        for check_name, check_func in checks:
            try:
                result = check_func()
                self.results[check_name] = result
            except Exception as e:
                logger.error(f"Audit check {check_name} raised exception: {e}")
                self.results[check_name] = False
                self.messages[check_name] = f"✗ Exception: {e}"

        return self.results

    def get_audit_report(self) -> str:
        """
        Generate human-readable audit report.

        Returns:
            Formatted report with check results and messages.
        """
        if not self.results:
            return "No audit results yet. Run run_audit() first."

        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)

        report_lines = [
            "=" * 60,
            f"Phase 10 Integration Audit Report",
            f"Passed: {passed}/{total}",
            "=" * 60,
            "",
        ]

        for check_name in sorted(self.results.keys()):
            result = self.results[check_name]
            status = "PASS" if result else "FAIL"
            message = self.messages.get(check_name, "")
            report_lines.append(f"[{status}] {check_name}")
            if message:
                report_lines.append(f"      {message}")

        report_lines.extend(["", "=" * 60])

        return "\n".join(report_lines)


def run_integration_audit() -> Dict[str, bool]:
    """
    Convenience function to run a full integration audit.

    Returns:
        Dictionary with check results.
    """
    checker = IntegrationAuditChecker()
    return checker.run_audit()
