"""
test/test_integration_audit.py — Phase 10 Integration Audit Tests

Tests for IntegrationAuditChecker and experiment tracking integration across
all four agent domains (Strategy A, Strategy B, RL, Search).
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from src.utils.integration_audit import IntegrationAuditChecker, run_integration_audit
from src.utils.experiment_tracker import ExperimentRecord, ExperimentMetrics, log_experiment


class TestIntegrationAuditChecker(unittest.TestCase):
    """Test IntegrationAuditChecker individual checks."""

    def setUp(self):
        self.checker = IntegrationAuditChecker()

    def test_check_search_pipeline_connected_success(self):
        """Test that SearchAgent and ResearchOutput are importable."""
        result = self.checker.check_search_pipeline_connected()
        self.assertTrue(result, f"Search pipeline check failed: {self.checker.messages.get('search_pipeline_connected')}")

    def test_check_strategy_b_research_enabled_success(self):
        """Test that Strategy B accepts research_context parameter."""
        result = self.checker.check_strategy_b_research_enabled()
        self.assertTrue(result, f"Strategy B research check failed: {self.checker.messages.get('strategy_b_research_enabled')}")

    def test_check_experiment_tracking_active_success(self):
        """Test that ExperimentTracker can be instantiated."""
        result = self.checker.check_experiment_tracking_active()
        self.assertTrue(result, f"Experiment tracking check failed: {self.checker.messages.get('experiment_tracking_active')}")

    def test_check_aggregate_risk_active_success(self):
        """Test that AggregateRiskMonitor can be instantiated."""
        result = self.checker.check_aggregate_risk_active()
        self.assertTrue(result, f"Aggregate risk check failed: {self.checker.messages.get('aggregate_risk_active')}")

    def test_check_promotion_pipeline_active_success(self):
        """Test that StrategyPromoter can be instantiated."""
        result = self.checker.check_promotion_pipeline_active()
        self.assertTrue(result, f"Promotion pipeline check failed: {self.checker.messages.get('promotion_pipeline_active')}")

    def test_run_audit_returns_dict(self):
        """Test that run_audit returns a dictionary with all check names."""
        results = self.checker.run_audit()
        self.assertIsInstance(results, dict)
        expected_keys = {
            "search_pipeline_connected",
            "rl_policy_available",
            "strategy_b_research_enabled",
            "experiment_tracking_active",
            "dashboard_endpoints_live",
            "aggregate_risk_active",
            "promotion_pipeline_active",
        }
        self.assertEqual(set(results.keys()), expected_keys)

    def test_get_audit_report_contains_results(self):
        """Test that get_audit_report includes all check results."""
        self.checker.run_audit()
        report = self.checker.get_audit_report()
        self.assertIn("Phase 10 Integration Audit Report", report)
        self.assertIn("PASS", report)
        self.assertIn("Passed:", report)

    def test_get_audit_report_no_results_message(self):
        """Test that get_audit_report handles case with no results."""
        report = self.checker.get_audit_report()
        self.assertIn("No audit results yet", report)


class TestExperimentTracking(unittest.TestCase):
    """Test experiment tracking integration with agents."""

    def test_create_strategy_a_experiment_record(self):
        """Test creating an ExperimentRecord for Strategy A."""
        metrics = ExperimentMetrics(
            primary="winner_model",
            values={
                "winner_model": "predictor_1",
                "confidence": 0.85,
                "ticker_count": 10,
                "outcomes_backfilled": 45,
            }
        )
        record = ExperimentRecord(
            run_id="strategy_a_2026-03-16",
            domain="strategy_a",
            config_version="1.0",
            status="testing",
            metrics=metrics,
        )
        self.assertEqual(record.domain, "strategy_a")
        self.assertEqual(record.run_id, "strategy_a_2026-03-16")
        self.assertIn("winner_model", record.metrics.values)

    def test_create_strategy_b_experiment_record(self):
        """Test creating an ExperimentRecord for Strategy B."""
        metrics = ExperimentMetrics(
            primary="consensus_reached",
            values={
                "consensus_reached": True,
                "confidence": 0.78,
                "rounds": 2,
                "models_used": 4,
                "ticker": "NVDA",
            }
        )
        record = ExperimentRecord(
            run_id="strategy_b_NVDA_2026-03-16",
            domain="strategy_b",
            config_version="1.0",
            status="testing",
            metrics=metrics,
        )
        self.assertEqual(record.domain, "strategy_b")
        self.assertEqual(record.metrics.values["consensus_reached"], True)

    def test_create_rl_experiment_record(self):
        """Test creating an ExperimentRecord for RL trading."""
        metrics = ExperimentMetrics(
            primary="total_reward",
            values={
                "episodes": 300,
                "epsilon": 0.30,
                "total_reward": 1250.5,
                "avg_reward": 0.45,
                "ticker": "AAPL",
                "algorithm": "tabular_q_learning",
            }
        )
        record = ExperimentRecord(
            run_id="rl_AAPL_20260316T120000Z",
            domain="rl",
            config_version="2.0",
            status="testing",
            metrics=metrics,
        )
        self.assertEqual(record.domain, "rl")
        self.assertGreater(record.metrics.values["total_reward"], 0)

    def test_create_search_experiment_record(self):
        """Test creating an ExperimentRecord for Search agent."""
        metrics = ExperimentMetrics(
            primary="extraction_success_rate",
            values={
                "sources_found": 5,
                "extraction_success_rate": 0.8,
                "sentiment": "bullish",
                "confidence": 0.75,
                "ticker": "TSLA",
                "query_length": 45,
            }
        )
        record = ExperimentRecord(
            run_id="search_TSLA_20260316T143000Z",
            domain="search",
            config_version="1.0",
            status="testing",
            metrics=metrics,
        )
        self.assertEqual(record.domain, "search")
        self.assertEqual(record.metrics.values["sentiment"], "bullish")

    def test_experiment_record_validation(self):
        """Test that ExperimentRecord validates domain correctly."""
        with self.assertRaises(Exception):
            ExperimentRecord(
                run_id="invalid_domain_test",
                domain="invalid_domain",  # Should be one of: strategy_a, strategy_b, rl, search
                config_version="1.0",
                metrics=ExperimentMetrics(primary="test", values={}),
            )

    def test_experiment_tracker_log_experiment(self):
        """Test logging an experiment to disk."""
        metrics = ExperimentMetrics(
            primary="test_metric",
            values={"test_value": 42}
        )
        record = ExperimentRecord(
            run_id="test_experiment_2026-03-16",
            domain="strategy_a",
            config_version="1.0",
            metrics=metrics,
        )
        # This should not raise an exception
        try:
            filepath = log_experiment(record)
            # Verify file was created
            self.assertTrue(filepath.exists(), f"Experiment file not created at {filepath}")
            # Verify content
            with open(filepath, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            self.assertEqual(saved_data["domain"], "strategy_a")
            self.assertEqual(saved_data["run_id"], "test_experiment_2026-03-16")
        except Exception as e:
            self.fail(f"Failed to log experiment: {e}")

    def test_experiment_metrics_structure(self):
        """Test ExperimentMetrics can hold complex values."""
        metrics = ExperimentMetrics(
            primary="multi_metric",
            values={
                "string_val": "test",
                "int_val": 100,
                "float_val": 3.14,
                "bool_val": True,
                "list_val": [1, 2, 3],
                "dict_val": {"nested": "value"},
            }
        )
        self.assertEqual(metrics.values["string_val"], "test")
        self.assertEqual(metrics.values["nested"], {"nested": "value"})


class TestIntegrationAuditConvenience(unittest.TestCase):
    """Test convenience functions."""

    def test_run_integration_audit_function(self):
        """Test the convenience run_integration_audit function."""
        results = run_integration_audit()
        self.assertIsInstance(results, dict)
        self.assertGreater(len(results), 0)


class TestExperimentRecordDefaults(unittest.TestCase):
    """Test ExperimentRecord default values."""

    def test_experiment_record_created_at_default(self):
        """Test that created_at is set by default."""
        record = ExperimentRecord(
            run_id="test_run",
            domain="strategy_a",
            config_version="1.0",
            metrics=ExperimentMetrics(primary="test", values={}),
        )
        self.assertIsNotNone(record.created_at)
        # Should be ISO format
        self.assertIn("T", record.created_at)

    def test_experiment_record_status_default(self):
        """Test that status defaults to 'testing'."""
        record = ExperimentRecord(
            run_id="test_run",
            domain="strategy_a",
            config_version="1.0",
            metrics=ExperimentMetrics(primary="test", values={}),
        )
        self.assertEqual(record.status, "testing")

    def test_experiment_record_expected_impact_default(self):
        """Test that expected_impact defaults to empty list."""
        record = ExperimentRecord(
            run_id="test_run",
            domain="strategy_a",
            config_version="1.0",
            metrics=ExperimentMetrics(primary="test", values={}),
        )
        self.assertEqual(record.expected_impact, [])


if __name__ == "__main__":
    unittest.main()
