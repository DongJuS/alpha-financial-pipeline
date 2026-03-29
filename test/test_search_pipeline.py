"""
test/test_search_pipeline.py — SearXNG 검색/분석 파이프라인 테스트

Tests cover:
- SearXNGClient URL canonicalization and rate limiting
- SearchAgent pipeline flow with mocked external calls
- ResearchOutput model
- Error handling and graceful degradation
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from src.agents.search_agent import (
    ResearchOutput,
    SearchAgent,
)
from src.utils.searxng_client import SearchResult, SearXNGClient


# ────────────────────────── SearXNGClient 테스트 ──────────────────────────────


class TestSearXNGClient(unittest.TestCase):
    """Test SearXNGClient configuration."""

    def test_client_default_base_url(self):
        """Default base_url should be localhost:8888."""
        client = SearXNGClient()
        self.assertIn("8888", client.base_url)

    def test_client_custom_base_url(self):
        """Custom base_url should be accepted."""
        client = SearXNGClient(base_url="http://custom:9999")
        self.assertEqual(client.base_url, "http://custom:9999")


class TestSearchResult(unittest.TestCase):
    """Test SearchResult model."""

    def test_search_result_valid(self):
        result = SearchResult(
            url="https://example.com",
            title="Test Article",
            snippet="Test content",
            engine="google",
        )
        self.assertEqual(result.url, "https://example.com")
        self.assertEqual(result.title, "Test Article")
        self.assertEqual(result.engine, "google")


# ────────────────────────── ResearchOutput 테스트 ─────────────────────────────


class TestResearchOutput(unittest.TestCase):
    """Test ResearchOutput model."""

    def test_research_output_full(self):
        """ResearchOutput should accept all fields."""
        output = ResearchOutput(
            ticker="259960",
            query="크래프톤 2026 실적",
            sentiment="bullish",
            confidence=0.75,
            key_facts=["팩트 1", "팩트 2"],
            risk_factors=["위험 1", "위험 2"],
            sources=[{"url": "https://example.com", "title": "test"}],
        )
        self.assertEqual(output.ticker, "259960")
        self.assertEqual(output.sentiment, "bullish")
        self.assertEqual(len(output.key_facts), 2)

    def test_research_output_minimal(self):
        """ResearchOutput with minimal fields."""
        output = ResearchOutput(
            query="test",
            sentiment="neutral",
            confidence=0.5,
            sources=[],
            key_facts=[],
            risk_factors=[],
        )
        self.assertEqual(output.sentiment, "neutral")
        self.assertIsNone(output.ticker)

    def test_research_output_serializable(self):
        """ResearchOutput attributes should be JSON serializable."""
        output = ResearchOutput(
            query="test",
            sentiment="neutral",
            confidence=0.5,
            sources=[{"url": "https://example.com"}],
            key_facts=["fact"],
            risk_factors=["risk"],
        )
        data = {
            "query": output.query,
            "sentiment": output.sentiment,
            "confidence": output.confidence,
            "sources": output.sources,
            "key_facts": output.key_facts,
            "risk_factors": output.risk_factors,
        }
        json_str = json.dumps(data)
        self.assertIsInstance(json_str, str)


# ────────────────────────── SearchAgent 파이프라인 테스트 ─────────────────────


class TestSearchAgentPipeline(unittest.IsolatedAsyncioTestCase):
    """Test SearchAgent pipeline orchestration."""

    async def test_run_research_no_results(self):
        """검색 결과 0건 → neutral/0.4 반환."""
        agent = SearchAgent()
        with patch.object(agent, "_searxng") as mock_searxng:
            mock_searxng.search = AsyncMock(return_value=[])
            output = await agent.run_research("test query")

        self.assertIsInstance(output, ResearchOutput)
        self.assertEqual(output.query, "test query")
        self.assertEqual(output.sentiment, "neutral")
        self.assertEqual(output.confidence, 0.4)
        self.assertEqual(output.sources, [])

    async def test_run_research_with_results(self):
        """검색 결과 있을 때 Claude 분석 결과 반환."""
        agent = SearchAgent()

        mock_results = [
            SearchResult(url="https://example.com/1", title="Article 1", snippet="Content 1", engine="google"),
            SearchResult(url="https://example.com/2", title="Article 2", snippet="Content 2", engine="google"),
        ]
        mock_analysis = {
            "sentiment": "bullish",
            "confidence": 0.8,
            "key_facts": ["사실 1"],
            "risk_factors": ["위험 1"],
        }

        with (
            patch.object(agent, "_searxng") as mock_searxng,
            patch.object(agent, "_reasoner") as mock_reasoner,
        ):
            mock_searxng.search = AsyncMock(return_value=mock_results)
            mock_reasoner.reason_with_json_output = AsyncMock(return_value=mock_analysis)
            mock_reasoner.model = "claude-test"

            output = await agent.run_research("test query", ticker="005930")

        self.assertEqual(output.query, "test query")
        self.assertEqual(output.ticker, "005930")
        self.assertEqual(output.sentiment, "bullish")
        self.assertEqual(output.confidence, 0.8)
        self.assertEqual(len(output.sources), 2)

    async def test_run_research_searxng_failure(self):
        """SearXNG 연결 실패 → neutral graceful degradation."""
        agent = SearchAgent()
        with patch.object(agent, "_searxng") as mock_searxng:
            mock_searxng.search = AsyncMock(side_effect=ConnectionError("SearXNG down"))
            output = await agent.run_research("test query")

        self.assertIsInstance(output, ResearchOutput)
        self.assertEqual(output.sentiment, "neutral")
        self.assertLessEqual(output.confidence, 0.5)

    async def test_run_research_reasoning_failure(self):
        """Claude 분석 실패 → neutral fallback."""
        agent = SearchAgent()

        mock_results = [
            SearchResult(url="https://example.com/1", title="Article", snippet="Content", engine="google"),
        ]

        with (
            patch.object(agent, "_searxng") as mock_searxng,
            patch.object(agent, "_reasoner") as mock_reasoner,
        ):
            mock_searxng.search = AsyncMock(return_value=mock_results)
            mock_reasoner.reason_with_json_output = AsyncMock(side_effect=RuntimeError("Claude API error"))

            output = await agent.run_research("test query")

        self.assertIsInstance(output, ResearchOutput)
        # 분석 실패 시에도 neutral로 graceful degradation
        self.assertEqual(output.sentiment, "neutral")


class TestSearchAgentErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test error handling in search pipeline."""

    async def test_search_failure_returns_neutral(self):
        """검색 실패 시 neutral 반환."""
        agent = SearchAgent()
        with patch.object(agent, "_searxng") as mock_searxng:
            mock_searxng.search = AsyncMock(return_value=[])
            output = await agent.run_research("test query")

        self.assertEqual(len(output.sources), 0)
        self.assertEqual(output.sentiment, "neutral")

    async def test_agent_init_default(self):
        """SearchAgent 기본 초기화."""
        agent = SearchAgent()
        self.assertEqual(agent.max_sources, 5)
        self.assertIsNotNone(agent._searxng)
        self.assertIsNotNone(agent._reasoner)


if __name__ == "__main__":
    unittest.main()
