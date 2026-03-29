"""
src/agents/search_agent.py — SearchAgent

SearXNG → 스니펫 구조화 → Claude CLI 감성 분석 파이프라인.

흐름:
1. SearXNGClient.search() 로 뉴스/공시 검색
2. 검색 결과 스니펫을 ReasoningClient 에게 전달해 구조화된 JSON 추출
   (sentiment, confidence, key_facts, risk_factors)
3. ResearchOutput 으로 래핑하여 반환
"""

from __future__ import annotations

import os
from typing import Optional
from zoneinfo import ZoneInfo

from src.utils.logging import get_logger
from src.utils.searxng_client import SearXNGClient, SearchResult
from src.utils.reasoning_client import ReasoningClient

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")


class ResearchOutput:
    """검색 결과 데이터 모델"""

    def __init__(
        self,
        query: str,
        sentiment: str,
        confidence: float,
        sources: list[dict],
        key_facts: list[str],
        risk_factors: list[str],
        ticker: Optional[str] = None,
        model_used: str = "claude",
    ):
        self.query = query
        self.sentiment = sentiment
        self.confidence = confidence
        self.sources = sources
        self.key_facts = key_facts
        self.risk_factors = risk_factors
        self.ticker = ticker
        self.model_used = model_used


# ── 감성 분석 프롬프트 ────────────────────────────────────────────────────────

_SENTIMENT_SYSTEM = (
    "당신은 한국 주식 시장 전문 애널리스트입니다. "
    "제공된 뉴스/공시 스니펫을 바탕으로 해당 종목의 단기 주가 방향성을 판단합니다."
)

_SENTIMENT_PROMPT_TPL = """다음은 종목 '{ticker}'({query})에 관한 최신 뉴스 스니펫 {n}건입니다.

{snippets}

위 정보를 바탕으로 아래 JSON 형식으로만 응답하세요:
{{
  "sentiment": "bullish" | "bearish" | "neutral",
  "confidence": 0.0~1.0,
  "key_facts": ["핵심 사실 1", "핵심 사실 2", ...],
  "risk_factors": ["리스크 1", "리스크 2", ...]
}}
규칙:
- sentiment: 단기(1~5일) 주가에 긍정이면 bullish, 부정이면 bearish, 판단 어려우면 neutral
- confidence: 정보의 충분성·일관성 기반 0~1 (스니펫이 없거나 상충되면 0.4 이하)
- key_facts: 주가에 직접 영향을 줄 수 있는 사실 최대 5개
- risk_factors: 하락 가능성을 높이는 요인 최대 3개"""


class SearchAgent:
    """SearXNG + Claude 기반 리서치 에이전트

    SearXNG로 최신 뉴스를 검색하고, Claude CLI로 감성 분석을 수행합니다.
    SearXNG 미연결 시 또는 Claude CLI 미설치 시에도 graceful degradation으로
    neutral/0.5 를 반환하여 블렌딩 파이프라인이 중단되지 않도록 합니다.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_sources: int = 5,
        db_pool: Optional[object] = None,
    ):
        self.api_key = api_key
        self.max_sources = max_sources
        self.db_pool = db_pool

        searxng_url = os.environ.get("SEARXNG_API_URL", "http://localhost:8888")
        self._searxng = SearXNGClient(base_url=searxng_url)
        self._reasoner = ReasoningClient()

    async def run_research(
        self,
        query: str,
        ticker: Optional[str] = None,
        category: str = "news",
        max_sources: int = 5,
    ) -> ResearchOutput:
        """SearXNG 검색 → Claude 감성 분석 파이프라인.

        Args:
            query: 검색 쿼리 (예: "삼성전자 실적 뉴스")
            ticker: 종목 코드 (선택, 프롬프트 컨텍스트용)
            category: SearXNG 카테고리 (news, general 등)
            max_sources: 최대 소스 개수

        Returns:
            ResearchOutput (sentiment, confidence, sources, key_facts, risk_factors)
        """
        n = max_sources or self.max_sources

        # ── Step 1: SearXNG 검색 ─────────────────────────────────────────
        results: list[SearchResult] = []
        try:
            results = await self._searxng.search(
                query,
                categories=category,
                language="ko",
                max_results=n,
            )
            logger.info(
                "SearXNG 검색 완료: query='%s' ticker=%s results=%d",
                query, ticker, len(results),
            )
        except Exception as e:
            logger.warning(
                "SearXNG 검색 실패 (graceful degradation): %s — neutral 반환", e
            )
            return ResearchOutput(
                query=query,
                sentiment="neutral",
                confidence=0.4,
                sources=[],
                key_facts=[],
                risk_factors=["SearXNG 연결 실패로 정보 없음"],
                ticker=ticker,
            )

        if not results:
            logger.info("SearXNG 결과 0건: query='%s' — neutral 반환", query)
            return ResearchOutput(
                query=query,
                sentiment="neutral",
                confidence=0.4,
                sources=[],
                key_facts=[],
                risk_factors=["검색 결과 없음"],
                ticker=ticker,
            )

        sources = [
            {"url": r.url, "title": r.title, "snippet": r.snippet, "engine": r.engine}
            for r in results
        ]

        # ── Step 2: Claude 감성 분석 ──────────────────────────────────────
        snippets_text = "\n\n".join(
            f"[{i+1}] {r.title}\n{r.snippet}"
            for i, r in enumerate(results)
        )
        prompt = _SENTIMENT_PROMPT_TPL.format(
            ticker=ticker or "N/A",
            query=query,
            n=len(results),
            snippets=snippets_text,
        )

        try:
            raw_json = await self._reasoner.reason_with_json_output(
                prompt,
                system=_SENTIMENT_SYSTEM,
            )
            sentiment = str(raw_json.get("sentiment", "neutral")).lower()
            if sentiment not in ("bullish", "bearish", "neutral"):
                sentiment = "neutral"
            confidence = float(raw_json.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            key_facts = list(raw_json.get("key_facts", []))[:5]
            risk_factors = list(raw_json.get("risk_factors", []))[:3]
            model_used = self._reasoner.model

            logger.info(
                "감성 분석 완료: ticker=%s sentiment=%s confidence=%.2f",
                ticker, sentiment, confidence,
            )
        except Exception as e:
            logger.warning(
                "Claude 감성 분석 실패 (graceful degradation): %s — neutral 반환", e
            )
            sentiment = "neutral"
            confidence = 0.4
            key_facts = [r.title for r in results[:3]]
            risk_factors = ["LLM 분석 실패로 신뢰도 낮음"]
            model_used = "fallback"

        return ResearchOutput(
            query=query,
            sentiment=sentiment,
            confidence=confidence,
            sources=sources,
            key_facts=key_facts,
            risk_factors=risk_factors,
            ticker=ticker,
            model_used=model_used,
        )

    async def close(self) -> None:
        """리소스 정리"""
        await self._searxng.close()
