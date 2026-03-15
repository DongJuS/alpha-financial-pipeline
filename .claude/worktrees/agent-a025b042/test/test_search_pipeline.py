"""
test/test_search_pipeline.py — Comprehensive tests for SearXNG search/scraping pipeline

Tests cover:
- SearXNGClient URL canonicalization and rate limiting
- SearchAgent pipeline flow with mocked external calls
- FetchResult/ExtractionResult/ResearchOutput models
- Database storage helpers
- Error handling and partial failures
"""

import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.search_agent import (
    ExtractionResult,
    FetchResult,
    ResearchOutput,
    SearchAgent,
)
from src.utils.searxng_client import SearchResult, SearXNGClient


class TestSearXNGClientCanonicalization(unittest.TestCase):
    """Test URL canonicalization logic."""

    def test_canonicalize_removes_utm_params(self):
        """URL canonicalization should remove tracking parameters."""
        url = "https://example.com/article?id=123&utm_source=google&utm_medium=search"
        canonical = SearXNGClient._canonicalize_url(url)
        self.assertIn("id=123", canonical)
        self.assertNotIn("utm_source", canonical)
        self.assertNotIn("utm_medium", canonical)

    def test_canonicalize_removes_fbclid(self):
        """Canonicalization should remove Facebook click ID."""
        url = "https://example.com/post?title=test&fbclid=abc123def456"
        canonical = SearXNGClient._canonicalize_url(url)
        self.assertNotIn("fbclid", canonical)
        self.assertIn("title=test", canonical)

    def test_canonicalize_handles_multiple_tracking_params(self):
        """Handle multiple tracking params together."""
        url = "https://example.com?gclid=123&utm_campaign=summer&msclkid=xyz"
        canonical = SearXNGClient._canonicalize_url(url)
        self.assertNotIn("gclid", canonical)
        self.assertNotIn("utm_campaign", canonical)
        self.assertNotIn("msclkid", canonical)

    def test_canonicalize_preserves_legitimate_params(self):
        """Legitimate query params should be preserved."""
        url = "https://example.com/search?q=python&page=2&sort=date"
        canonical = SearXNGClient._canonicalize_url(url)
        self.assertIn("q=python", canonical)
        self.assertIn("page=2", canonical)
        self.assertIn("sort=date", canonical)

    def test_canonicalize_handles_malformed_urls(self):
        """Should handle malformed URLs gracefully."""
        url = "not a valid url at all"
        canonical = SearXNGClient._canonicalize_url(url)
        # Should return original or empty, not crash
        self.assertIsInstance(canonical, str)


class TestSearXNGClientRateLimiting(unittest.IsolatedAsyncioTestCase):
    """Test rate limiting logic."""

    async def test_rate_limit_enforced(self):
        """Rate limiting should enforce min delay between requests to same domain."""
        client = SearXNGClient(rate_limit_delay=0.1)

        start = asyncio.get_event_loop().time()
        await client._apply_rate_limit("example.com")
        await client._apply_rate_limit("example.com")
        elapsed = asyncio.get_event_loop().time() - start

        # Should have waited ~0.1 seconds
        self.assertGreater(elapsed, 0.08)

    async def test_different_domains_no_wait(self):
        """Different domains should not trigger rate limit."""
        client = SearXNGClient(rate_limit_delay=0.5)

        start = asyncio.get_event_loop().time()
        await client._apply_rate_limit("domain1.com")
        await client._apply_rate_limit("domain2.com")
        elapsed = asyncio.get_event_loop().time() - start

        # Should have minimal wait (no rate limit between different domains)
        self.assertLess(elapsed, 0.1)


class TestFetchResult(unittest.TestCase):
    """Test FetchResult model."""

    def test_fetch_result_valid(self):
        """FetchResult should accept valid data."""
        result = FetchResult(
            url="https://example.com",
            status_code=200,
            content_text="Hello world",
            content_hash="abc123",
        )
        self.assertEqual(result.url, "https://example.com")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content_text, "Hello world")

    def test_fetch_result_with_error(self):
        """FetchResult should handle error cases."""
        result = FetchResult(
            url="https://example.com",
            status_code=404,
            error="Not found",
        )
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.error, "Not found")
        self.assertEqual(result.content_text, "")


class TestExtractionResult(unittest.TestCase):
    """Test ExtractionResult model."""

    def test_extraction_result_extracted(self):
        """ExtractionResult should represent successful extraction."""
        result = ExtractionResult(
            url="https://example.com/article",
            structured_data={"title": "Article Title", "body": "Content..."},
            status="extracted",
        )
        self.assertEqual(result.status, "extracted")
        self.assertEqual(result.structured_data["title"], "Article Title")

    def test_extraction_result_partial(self):
        """ExtractionResult should represent partial extraction."""
        result = ExtractionResult(
            url="https://example.com/article",
            status="partial",
            error="Some fields missing",
        )
        self.assertEqual(result.status, "partial")
        self.assertIsNotNone(result.error)

    def test_extraction_result_failed(self):
        """ExtractionResult should represent failure."""
        result = ExtractionResult(
            url="https://example.com/article",
            status="failed",
            error="Unable to parse content",
        )
        self.assertEqual(result.status, "failed")


class TestResearchOutput(unittest.TestCase):
    """Test ResearchOutput model (research contract)."""

    def test_research_output_full(self):
        """ResearchOutput should accept all fields."""
        output = ResearchOutput(
            ticker="259960",
            query="크래프톤 2026 실적",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bullish",
            confidence=0.75,
            key_facts=["팩트 1", "팩트 2"],
            risk_factors=["위험 1", "위험 2"],
            summary="요약 텍스트",
        )
        self.assertEqual(output.ticker, "259960")
        self.assertEqual(output.sentiment, "bullish")
        self.assertEqual(len(output.key_facts), 2)

    def test_research_output_serializable(self):
        """ResearchOutput should be JSON serializable."""
        output = ResearchOutput(
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="neutral",
        )
        # Should be able to dict() and then json.dumps()
        data = output.dict(default=str)
        json_str = json.dumps(data)
        self.assertIsInstance(json_str, str)


class TestSearchAgentPipeline(unittest.IsolatedAsyncioTestCase):
    """Test SearchAgent pipeline orchestration."""

    async def test_run_research_no_results(self):
        """Pipeline should handle no search results gracefully."""
        # Mock SearXNG to return no results
        mock_searxng = AsyncMock()
        mock_searxng.search = AsyncMock(return_value=[])

        agent = SearchAgent(searxng_client=mock_searxng)
        output = await agent.run_research("test query")

        self.assertIsInstance(output, ResearchOutput)
        self.assertEqual(output.query, "test query")
        self.assertIn("No search results", output.summary)

        await agent.close()

    async def test_run_research_with_results(self):
        """Pipeline should process search results successfully."""
        # Mock SearXNG to return results
        mock_searxng = AsyncMock()
        mock_searxng.search = AsyncMock(
            return_value=[
                SearchResult(
                    url="https://example.com/1",
                    title="Article 1",
                    snippet="Content 1",
                    engine="google",
                ),
                SearchResult(
                    url="https://example.com/2",
                    title="Article 2",
                    snippet="Content 2",
                    engine="google",
                ),
            ]
        )

        # Mock Claude reasoning
        mock_reasoning = AsyncMock()
        mock_reasoning.reason_with_json_output = AsyncMock(
            return_value={
                "sentiment": "bullish",
                "confidence": 0.8,
                "key_facts": ["사실 1"],
                "risk_factors": ["위험 1"],
                "summary": "요약 텍스트",
            }
        )

        agent = SearchAgent(
            searxng_client=mock_searxng,
            reasoning_client=mock_reasoning,
        )

        output = await agent.run_research("test query", ticker="000001")

        self.assertEqual(output.query, "test query")
        self.assertEqual(output.ticker, "000001")
        self.assertEqual(output.sentiment, "bullish")
        self.assertEqual(output.confidence, 0.8)
        self.assertEqual(len(output.sources), 2)

        await agent.close()

    async def test_run_research_fetch_failure_handling(self):
        """Pipeline should handle fetch failures gracefully."""
        mock_searxng = AsyncMock()
        mock_searxng.search = AsyncMock(
            return_value=[
                SearchResult(
                    url="https://example.com/1",
                    title="Article",
                    snippet="Content",
                    engine="google",
                ),
            ]
        )

        mock_reasoning = AsyncMock()
        mock_reasoning.reason_with_json_output = AsyncMock(
            return_value={
                "sentiment": "neutral",
                "confidence": 0.5,
                "key_facts": [],
                "risk_factors": [],
                "summary": "No content",
            }
        )

        agent = SearchAgent(
            searxng_client=mock_searxng,
            reasoning_client=mock_reasoning,
        )

        # Should complete even if fetch fails
        output = await agent.run_research("test query")

        self.assertIsInstance(output, ResearchOutput)
        self.assertEqual(output.query, "test query")

        await agent.close()

    async def test_fetch_pages_parallel(self):
        """Multiple URLs should be fetched in parallel."""
        mock_searxng = AsyncMock()
        mock_reasoning = AsyncMock()

        agent = SearchAgent(
            searxng_client=mock_searxng,
            reasoning_client=mock_reasoning,
        )

        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

        # Mock successful fetch
        client = AsyncMock()
        with patch.object(agent, "_get_http_client", return_value=client):
            client.get = AsyncMock(
                side_effect=[
                    MagicMock(status_code=200, text="Content 1"),
                    MagicMock(status_code=200, text="Content 2"),
                    MagicMock(status_code=200, text="Content 3"),
                ]
            )

            results = await agent._fetch_pages(urls)

        self.assertEqual(len(results), 3)
        for result in results:
            self.assertIsInstance(result, FetchResult)
            self.assertEqual(result.status_code, 200)

        await agent.close()

    async def test_extract_structured(self):
        """Extraction should process fetched content."""
        agent = SearchAgent()

        fetch_results = [
            FetchResult(
                url="https://example.com/1",
                status_code=200,
                content_text="Article content here",
            ),
            FetchResult(
                url="https://example.com/2",
                status_code=404,
                error="Not found",
            ),
        ]

        extractions = await agent._extract_structured(fetch_results)

        self.assertEqual(len(extractions), 2)
        self.assertEqual(extractions[0].status, "extracted")
        self.assertEqual(extractions[1].status, "failed")

        await agent.close()


class TestSearchAgentErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test error handling in search pipeline."""

    async def test_claude_reasoning_failure(self):
        """Pipeline should handle Claude reasoning failure."""
        mock_searxng = AsyncMock()
        mock_searxng.search = AsyncMock(
            return_value=[
                SearchResult(
                    url="https://example.com/1",
                    title="Article",
                    snippet="Content",
                    engine="google",
                ),
            ]
        )

        mock_reasoning = AsyncMock()
        mock_reasoning.reason_with_json_output = AsyncMock(
            side_effect=RuntimeError("Claude API error")
        )

        agent = SearchAgent(
            searxng_client=mock_searxng,
            reasoning_client=mock_reasoning,
        )

        output = await agent.run_research("test query")

        # Should return partial result even on reasoning failure
        self.assertIsInstance(output, ResearchOutput)
        self.assertIn("Reasoning failed", output.summary)

        await agent.close()

    async def test_search_failure_returns_empty(self):
        """Pipeline should handle search failure."""
        mock_searxng = AsyncMock()
        mock_searxng.search = AsyncMock(return_value=[])

        agent = SearchAgent(searxng_client=mock_searxng)

        output = await agent.run_research("test query")

        self.assertEqual(len(output.sources), 0)
        self.assertIn("No search results", output.summary)

        await agent.close()


if __name__ == "__main__":
    unittest.main()
