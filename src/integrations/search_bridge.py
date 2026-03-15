"""
src/integrations/search_bridge.py — Bridge between SearchAgent and Strategy/RL components

Provides utilities to:
1. Format ResearchOutput for LLM prompt injection (strategy_b_consensus)
2. Extract numerical research features for RL dataset enrichment
"""

from typing import Optional

from src.agents.search_agent import ResearchOutput
from src.utils.logging import get_logger

logger = get_logger(__name__)


def format_research_for_prompt(research: Optional[ResearchOutput]) -> str:
    """
    Format ResearchOutput into a human-readable prompt section for LLM injection.

    Args:
        research: ResearchOutput from SearchAgent, or None

    Returns:
        Formatted string suitable for prompt injection, empty string if None
    """
    if research is None:
        return ""

    lines = []
    lines.append("── Research Context ──")

    if research.query:
        lines.append(f"Query: {research.query}")

    if research.sentiment:
        lines.append(f"Sentiment: {research.sentiment.upper()}")

    lines.append(f"Confidence: {research.confidence:.2%}")

    if research.key_facts:
        lines.append("Key Facts:")
        for fact in research.key_facts:
            lines.append(f"  • {fact}")

    if research.risk_factors:
        lines.append("Risk Factors:")
        for risk in research.risk_factors:
            lines.append(f"  • {risk}")

    if research.summary:
        lines.append(f"Summary: {research.summary}")

    if research.sources:
        lines.append(f"Sources: {len(research.sources)} URL(s)")

    return "\n".join(lines)


def extract_research_features(research: Optional[ResearchOutput]) -> dict:
    """
    Extract numerical research features for RL dataset enrichment.

    Args:
        research: ResearchOutput from SearchAgent, or None

    Returns:
        Dictionary with research features:
        - sentiment_score: -1 (bearish) to +1 (bullish)
        - confidence: 0 to 1
        - source_count: number of sources
        - fact_count: number of key facts
        - risk_count: number of risk factors
    """
    if research is None:
        return {
            "sentiment_score": 0.0,
            "confidence": 0.0,
            "source_count": 0,
            "fact_count": 0,
            "risk_count": 0,
        }

    # Convert sentiment to numerical score: -1 (bearish), 0 (neutral), +1 (bullish)
    sentiment_map = {
        "bearish": -1.0,
        "neutral": 0.0,
        "bullish": 1.0,
        "mixed": 0.0,  # mixed -> neutral
    }
    sentiment_score = sentiment_map.get(research.sentiment.lower(), 0.0)

    # Blend sentiment with confidence (confidence moderates the sentiment signal)
    adjusted_sentiment = sentiment_score * research.confidence

    return {
        "sentiment_score": adjusted_sentiment,
        "confidence": research.confidence,
        "source_count": len(research.sources) if research.sources else 0,
        "fact_count": len(research.key_facts) if research.key_facts else 0,
        "risk_count": len(research.risk_factors) if research.risk_factors else 0,
    }
