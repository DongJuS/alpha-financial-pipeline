"""
test/test_search_bridge.py — Tests for search_bridge integration module

Tests:
- format_research_for_prompt with valid ResearchOutput
- format_research_for_prompt with None
- extract_research_features with valid ResearchOutput
- extract_research_features with None
- extract_research_features sentiment scoring
"""

import unittest
from datetime import datetime, timezone

from src.agents.search_agent import ResearchOutput
from src.integrations.search_bridge import extract_research_features, format_research_for_prompt


class TestFormatResearchForPrompt(unittest.TestCase):
    def test_format_with_none_returns_empty_string(self):
        """format_research_for_prompt should return empty string for None."""
        result = format_research_for_prompt(None)
        self.assertEqual(result, "")

    def test_format_with_full_research_output(self):
        """format_research_for_prompt should format all fields."""
        research = ResearchOutput(
            ticker="005930",
            query="삼성전자 실적",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bullish",
            confidence=0.85,
            key_facts=[
                "분기 실적 증가",
                "반도체 수요 증가",
            ],
            risk_factors=[
                "지정학적 리스크",
                "환율 변동성",
            ],
            summary="강력한 긍정적 신호",
            sources=[
                {"url": "https://example1.com", "extraction_status": "extracted"},
                {"url": "https://example2.com", "extraction_status": "extracted"},
            ],
            model_used="claude-3-5-sonnet-latest",
        )
        result = format_research_for_prompt(research)

        # Verify key content is present
        self.assertIn("Research Context", result)
        self.assertIn("삼성전자 실적", result)
        self.assertIn("BULLISH", result)
        self.assertIn("85%", result)
        self.assertIn("분기 실적 증가", result)
        self.assertIn("지정학적 리스크", result)
        self.assertIn("강력한 긍정적 신호", result)
        self.assertIn("2 URL(s)", result)

    def test_format_with_minimal_research_output(self):
        """format_research_for_prompt should handle minimal data."""
        research = ResearchOutput(
            ticker="000660",
            query="SK하이닉스",
            timestamp_utc=datetime.now(timezone.utc),
        )
        result = format_research_for_prompt(research)

        self.assertIn("Research Context", result)
        self.assertIn("SK하이닉스", result)
        # Should not error on empty lists
        self.assertTrue(len(result) > 0)

    def test_format_with_empty_lists(self):
        """format_research_for_prompt should handle empty key_facts and risk_factors."""
        research = ResearchOutput(
            ticker="005930",
            query="test query",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="neutral",
            confidence=0.5,
            key_facts=[],
            risk_factors=[],
            summary="No specific insights",
            sources=[],
        )
        result = format_research_for_prompt(research)

        # Should not include sections for empty lists
        self.assertNotIn("Key Facts:", result)
        self.assertNotIn("Risk Factors:", result)
        self.assertIn("Summary:", result)
        self.assertIn("Sources: 0 URL(s)", result)


class TestExtractResearchFeatures(unittest.TestCase):
    def test_extract_with_none_returns_zeros(self):
        """extract_research_features should return zero-valued dict for None."""
        result = extract_research_features(None)

        self.assertEqual(result, {
            "sentiment_score": 0.0,
            "confidence": 0.0,
            "source_count": 0,
            "fact_count": 0,
            "risk_count": 0,
        })

    def test_extract_bullish_sentiment(self):
        """extract_research_features should map bullish to +1."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bullish",
            confidence=0.8,
            key_facts=["fact1", "fact2"],
            risk_factors=["risk1"],
            sources=[{"url": "http://example.com", "extraction_status": "extracted"}],
        )
        result = extract_research_features(research)

        # sentiment_score = 1.0 * 0.8 = 0.8 (bullish moderated by confidence)
        self.assertEqual(result["sentiment_score"], 0.8)
        self.assertEqual(result["confidence"], 0.8)
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["fact_count"], 2)
        self.assertEqual(result["risk_count"], 1)

    def test_extract_bearish_sentiment(self):
        """extract_research_features should map bearish to -1."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bearish",
            confidence=0.7,
        )
        result = extract_research_features(research)

        # sentiment_score = -1.0 * 0.7 = -0.7
        self.assertEqual(result["sentiment_score"], -0.7)
        self.assertEqual(result["confidence"], 0.7)

    def test_extract_neutral_sentiment(self):
        """extract_research_features should map neutral to 0."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="neutral",
            confidence=0.5,
        )
        result = extract_research_features(research)

        # sentiment_score = 0.0 * 0.5 = 0.0
        self.assertEqual(result["sentiment_score"], 0.0)
        self.assertEqual(result["confidence"], 0.5)

    def test_extract_mixed_sentiment(self):
        """extract_research_features should map mixed to 0 (neutral)."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="mixed",
            confidence=0.6,
        )
        result = extract_research_features(research)

        # sentiment_score = 0.0 * 0.6 = 0.0 (mixed treated as neutral)
        self.assertEqual(result["sentiment_score"], 0.0)
        self.assertEqual(result["confidence"], 0.6)

    def test_extract_high_confidence_bullish(self):
        """High confidence bullish should produce high positive score."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bullish",
            confidence=1.0,
        )
        result = extract_research_features(research)

        self.assertEqual(result["sentiment_score"], 1.0)

    def test_extract_low_confidence_bearish(self):
        """Low confidence bearish should produce weak negative score."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bearish",
            confidence=0.2,
        )
        result = extract_research_features(research)

        self.assertAlmostEqual(result["sentiment_score"], -0.2)

    def test_extract_with_multiple_sources_and_factors(self):
        """extract_research_features should count all sources and factors."""
        research = ResearchOutput(
            ticker="005930",
            query="test",
            timestamp_utc=datetime.now(timezone.utc),
            sentiment="bullish",
            confidence=0.75,
            key_facts=["fact1", "fact2", "fact3", "fact4"],
            risk_factors=["risk1", "risk2"],
            sources=[
                {"url": "http://example1.com", "extraction_status": "extracted"},
                {"url": "http://example2.com", "extraction_status": "extracted"},
                {"url": "http://example3.com", "extraction_status": "extracted"},
            ],
        )
        result = extract_research_features(research)

        self.assertEqual(result["source_count"], 3)
        self.assertEqual(result["fact_count"], 4)
        self.assertEqual(result["risk_count"], 2)
        self.assertEqual(result["sentiment_score"], 0.75)


if __name__ == "__main__":
    unittest.main()
