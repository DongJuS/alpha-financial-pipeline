"""
test/test_phase10_api.py — Phase 10 Integration API Tests

Tests for the /integration/* endpoints:
  - GET /integration/search-sources
  - GET /integration/rl-evaluation
  - GET /integration/active-policies
  - GET /integration/audit-status
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app


client = TestClient(app)

# ── Search Sources Tests ──────────────────────────────────────────────────


class TestSearchSourcesEndpoint:
    """Tests for GET /integration/search-sources"""

    def test_search_sources_returns_200(self) -> None:
        """Endpoint should return 200 OK."""
        response = client.get("/api/v1/integration/search-sources")
        assert response.status_code == 200

    def test_search_sources_response_structure(self) -> None:
        """Response should have correct structure."""
        response = client.get("/api/v1/integration/search-sources")
        data = response.json()

        assert "items" in data
        assert "total_count" in data
        assert "last_updated" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["total_count"], int)
        assert isinstance(data["last_updated"], str)

    def test_search_sources_item_structure(self) -> None:
        """Each item should have required fields."""
        response = client.get("/api/v1/integration/search-sources")
        data = response.json()

        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "query_id",
                "ticker",
                "query",
                "sentiment",
                "source_count",
                "confidence",
                "sources",
                "timestamp",
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_search_sources_sentiment_valid(self) -> None:
        """Sentiment should be valid enum value."""
        response = client.get("/api/v1/integration/search-sources")
        data = response.json()

        valid_sentiments = ["bullish", "bearish", "neutral"]
        for item in data["items"]:
            assert item["sentiment"] in valid_sentiments

    def test_search_sources_confidence_range(self) -> None:
        """Confidence should be between 0.0 and 1.0."""
        response = client.get("/api/v1/integration/search-sources")
        data = response.json()

        for item in data["items"]:
            assert 0.0 <= item["confidence"] <= 1.0


# ── RL Evaluation Tests ────────────────────────────────────────────────────


class TestRLEvaluationEndpoint:
    """Tests for GET /integration/rl-evaluation"""

    def test_rl_evaluation_returns_200(self) -> None:
        """Endpoint should return 200 OK."""
        response = client.get("/api/v1/integration/rl-evaluation")
        assert response.status_code == 200

    def test_rl_evaluation_response_structure(self) -> None:
        """Response should have correct structure."""
        response = client.get("/api/v1/integration/rl-evaluation")
        data = response.json()

        assert "items" in data
        assert "total_count" in data
        assert "last_updated" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["total_count"], int)

    def test_rl_evaluation_item_structure(self) -> None:
        """Each item should have required fields."""
        response = client.get("/api/v1/integration/rl-evaluation")
        data = response.json()

        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "policy_id",
                "ticker",
                "algorithm",
                "holdout_return_pct",
                "win_rate",
                "status",
                "timestamp",
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_rl_evaluation_status_valid(self) -> None:
        """Status should be valid enum value."""
        response = client.get("/api/v1/integration/rl-evaluation")
        data = response.json()

        valid_statuses = ["approved", "pending", "rejected"]
        for item in data["items"]:
            assert item["status"] in valid_statuses

    def test_rl_evaluation_win_rate_range(self) -> None:
        """Win rate should be between 0.0 and 1.0."""
        response = client.get("/api/v1/integration/rl-evaluation")
        data = response.json()

        for item in data["items"]:
            assert 0.0 <= item["win_rate"] <= 1.0

    def test_rl_evaluation_sharpe_optional(self) -> None:
        """Sharpe ratio can be null."""
        response = client.get("/api/v1/integration/rl-evaluation")
        data = response.json()

        for item in data["items"]:
            if item["sharpe_ratio"] is not None:
                assert isinstance(item["sharpe_ratio"], (int, float))


# ── Active Policies Tests ──────────────────────────────────────────────────


class TestActivePoliciesEndpoint:
    """Tests for GET /integration/active-policies"""

    def test_active_policies_returns_200(self) -> None:
        """Endpoint should return 200 OK."""
        response = client.get("/api/v1/integration/active-policies")
        assert response.status_code == 200

    def test_active_policies_response_structure(self) -> None:
        """Response should have correct structure."""
        response = client.get("/api/v1/integration/active-policies")
        data = response.json()

        assert "items" in data
        assert "total_count" in data
        assert "last_updated" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["total_count"], int)

    def test_active_policies_item_structure(self) -> None:
        """Each item should have required fields."""
        response = client.get("/api/v1/integration/active-policies")
        data = response.json()

        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "policy_id",
                "ticker",
                "algorithm",
                "strategy_id",
                "mode",
                "return_pct",
                "trades_count",
                "timestamp",
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_active_policies_mode_valid(self) -> None:
        """Mode should be valid enum value."""
        response = client.get("/api/v1/integration/active-policies")
        data = response.json()

        valid_modes = ["shadow", "paper", "live"]
        for item in data["items"]:
            assert item["mode"] in valid_modes

    def test_active_policies_trades_count_nonnegative(self) -> None:
        """Trades count should be non-negative."""
        response = client.get("/api/v1/integration/active-policies")
        data = response.json()

        for item in data["items"]:
            assert item["trades_count"] >= 0


# ── Audit Status Tests ─────────────────────────────────────────────────────


class TestAuditStatusEndpoint:
    """Tests for GET /integration/audit-status"""

    def test_audit_status_returns_200(self) -> None:
        """Endpoint should return 200 OK."""
        response = client.get("/api/v1/integration/audit-status")
        assert response.status_code == 200

    def test_audit_status_response_structure(self) -> None:
        """Response should have correct structure."""
        response = client.get("/api/v1/integration/audit-status")
        data = response.json()

        assert "items" in data
        assert "overall_status" in data
        assert "last_updated" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["overall_status"], str)

    def test_audit_status_item_structure(self) -> None:
        """Each item should have required fields."""
        response = client.get("/api/v1/integration/audit-status")
        data = response.json()

        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "category",
                "item_name",
                "status",
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_audit_status_overall_valid(self) -> None:
        """Overall status should be valid enum value."""
        response = client.get("/api/v1/integration/audit-status")
        data = response.json()

        valid_overall_statuses = ["healthy", "warning", "critical"]
        assert data["overall_status"] in valid_overall_statuses

    def test_audit_status_item_status_valid(self) -> None:
        """Item status should be valid enum value."""
        response = client.get("/api/v1/integration/audit-status")
        data = response.json()

        valid_item_statuses = ["pass", "fail", "pending", "warning"]
        for item in data["items"]:
            assert item["status"] in valid_item_statuses

    def test_audit_status_correlates_with_items(self) -> None:
        """Overall status should correlate with item statuses."""
        response = client.get("/api/v1/integration/audit-status")
        data = response.json()

        item_statuses = [item["status"] for item in data["items"]]
        overall = data["overall_status"]

        if any(s == "fail" for s in item_statuses):
            assert overall == "critical"
        elif any(s == "warning" for s in item_statuses):
            assert overall == "warning"


# ── Integration Tests ──────────────────────────────────────────────────────


class TestPhase10Integration:
    """Integration tests for all Phase 10 endpoints."""

    def test_all_endpoints_accessible(self) -> None:
        """All Phase 10 endpoints should be accessible."""
        endpoints = [
            "/api/v1/integration/search-sources",
            "/api/v1/integration/rl-evaluation",
            "/api/v1/integration/active-policies",
            "/api/v1/integration/audit-status",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, f"{endpoint} failed"

    def test_all_endpoints_have_timestamps(self) -> None:
        """All endpoints should have last_updated timestamp."""
        endpoints = [
            "/api/v1/integration/search-sources",
            "/api/v1/integration/rl-evaluation",
            "/api/v1/integration/active-policies",
            "/api/v1/integration/audit-status",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "last_updated" in data
            assert isinstance(data["last_updated"], str)

    def test_endpoints_have_consistent_structure(self) -> None:
        """All list endpoints should have items and total_count."""
        endpoints = [
            "/api/v1/integration/search-sources",
            "/api/v1/integration/rl-evaluation",
            "/api/v1/integration/active-policies",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "items" in data
            assert "total_count" in data
            assert len(data["items"]) == data["total_count"]
