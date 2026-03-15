"""
src/agents/search_agent.py — SearchAgent for Hybrid Search/Scraping Pipeline

Orchestrates the full pipeline: SearXNG search → parallel fetch → extraction → Claude reasoning.
Supports optional database storage and integrates with existing agent infrastructure.
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
import httpx
from pydantic import BaseModel, Field

from src.utils.searxng_client import SearXNGClient, SearchResult
from src.utils.reasoning_client import ReasoningClient
from src.utils.logging import get_logger

logger = get_logger(__name__)


class FetchResult(BaseModel):
    """Result of fetching and parsing a single URL."""

    url: str
    status_code: int = 200
    content_text: str = ""
    content_hash: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None


class ExtractionResult(BaseModel):
    """Result of structured data extraction from fetched content."""

    url: str
    structured_data: dict = {}
    extraction_schema: str = "html_to_text"
    status: str = "pending"  # pending, extracted, partial, failed
    error: Optional[str] = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResearchOutput(BaseModel):
    """Final research contract output (Claude reasoning result)."""

    ticker: Optional[str] = None
    query: str
    timestamp_utc: datetime
    sources: list[dict] = []
    sentiment: str = "neutral"  # bullish, bearish, neutral, mixed
    confidence: float = 0.5
    key_facts: list[str] = []
    risk_factors: list[str] = []
    summary: str = ""
    model_used: str = "claude-3-5-sonnet-latest"


class SearchAgent:
    """
    Hybrid pipeline SearchAgent.

    Orchestrates: search → fetch → extract → reason
    Supports optional DB persistence via asyncpg pool.
    """

    def __init__(
        self,
        searxng_client: Optional[SearXNGClient] = None,
        reasoning_client: Optional[ReasoningClient] = None,
        db_pool: Optional[asyncpg.pool.Pool] = None,
    ):
        """
        Initialize SearchAgent.

        Args:
            searxng_client: SearXNGClient instance (auto-created if None)
            reasoning_client: ReasoningClient instance (auto-created if None)
            db_pool: asyncpg connection pool for storage (optional)
        """
        self.searxng = searxng_client or SearXNGClient()
        self.reasoning = reasoning_client or ReasoningClient()
        self.db_pool = db_pool
        self._http_client: Optional[httpx.AsyncClient] = None

    async def close(self) -> None:
        """Clean up resources."""
        await self.searxng.close()
        if self._http_client:
            await self._http_client.aclose()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy-initialize async HTTP client for fetching."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=15.0)
        return self._http_client

    async def run_research(
        self,
        query: str,
        *,
        ticker: Optional[str] = None,
        category: str = "general",
        max_sources: int = 5,
    ) -> ResearchOutput:
        """
        Execute full research pipeline: search → fetch → extract → reason.

        Args:
            query: Search query string
            ticker: Optional stock ticker for context
            category: SearXNG category (general, news, finance)
            max_sources: Max sources to process

        Returns:
            ResearchOutput with final research contract
        """
        start_time = time.time()
        logger.info(f"Starting research pipeline: query='{query}', ticker={ticker}")

        # Step 1: Search
        search_results = await self.searxng.search(
            query,
            categories=category,
            language="ko",
            max_results=max_sources,
        )

        if not search_results:
            logger.warning("No search results found")
            return ResearchOutput(
                query=query,
                timestamp_utc=datetime.now(timezone.utc),
                summary="No search results found.",
            )

        logger.info(f"Got {len(search_results)} search results")

        # Step 2: Fetch pages in parallel
        urls = [r.url for r in search_results]
        fetch_results = await self._fetch_pages(urls)
        logger.info(f"Fetched {len([f for f in fetch_results if f.error is None])} pages successfully")

        # Step 3: Extract structured data
        extraction_results = await self._extract_structured(fetch_results)
        logger.info(f"Extracted {len([e for e in extraction_results if e.status == 'extracted'])} pages")

        # Step 4: Claude reasoning
        output = await self._reason(query, extraction_results, ticker=ticker)
        output.timestamp_utc = datetime.now(timezone.utc)

        elapsed = time.time() - start_time
        logger.info(f"Research pipeline completed in {elapsed:.1f}s: {output.summary[:100]}")

        # Step 5: Store results (if DB available)
        if self.db_pool:
            await self._store_research(query, search_results, extraction_results, output, ticker)

        return output

    async def _fetch_pages(self, urls: list[str]) -> list[FetchResult]:
        """
        Fetch multiple URLs in parallel with error handling.

        Args:
            urls: List of URLs to fetch

        Returns:
            List of FetchResult objects
        """
        client = await self._get_http_client()
        tasks = [self._fetch_single(client, url) for url in urls]
        return await asyncio.gather(*tasks)

    async def _fetch_single(self, client: httpx.AsyncClient, url: str) -> FetchResult:
        """
        Fetch a single URL with timeout and error handling.

        Args:
            client: httpx.AsyncClient
            url: URL to fetch

        Returns:
            FetchResult with content or error
        """
        try:
            logger.debug(f"Fetching {url}")
            response = await client.get(url, follow_redirects=True)
            content_text = response.text[:10000]  # Truncate large responses

            # Calculate content hash for deduplication
            content_hash = hashlib.sha256(content_text.encode()).hexdigest()

            return FetchResult(
                url=url,
                status_code=response.status_code,
                content_text=content_text,
                content_hash=content_hash,
                fetched_at=datetime.now(timezone.utc),
            )
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url}")
            return FetchResult(
                url=url,
                status_code=0,
                error="Timeout",
            )
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            return FetchResult(
                url=url,
                status_code=0,
                error=str(e),
            )

    async def _extract_structured(
        self,
        fetch_results: list[FetchResult],
    ) -> list[ExtractionResult]:
        """
        Extract structured data from fetched pages.

        MVP: Simple HTML-to-text extraction. Can be extended to use ScrapeGraphAI.

        Args:
            fetch_results: List of FetchResult from _fetch_pages

        Returns:
            List of ExtractionResult objects
        """
        results = []

        for fetch in fetch_results:
            if fetch.error:
                results.append(
                    ExtractionResult(
                        url=fetch.url,
                        status="failed",
                        error=fetch.error,
                    )
                )
                continue

            # MVP: Simple text extraction (no ScrapeGraphAI yet)
            extraction = ExtractionResult(
                url=fetch.url,
                structured_data={
                    "raw_text": fetch.content_text[:2000],  # Keep first 2000 chars
                    "content_hash": fetch.content_hash,
                    "status_code": fetch.status_code,
                },
                extraction_schema="html_to_text",
                status="extracted",
            )
            results.append(extraction)

        return results

    async def _reason(
        self,
        query: str,
        extractions: list[ExtractionResult],
        *,
        ticker: Optional[str] = None,
    ) -> ResearchOutput:
        """
        Use Claude to reason over extracted content and generate research contract.

        Args:
            query: Original search query
            extractions: List of ExtractionResult from extraction step
            ticker: Optional ticker for context

        Returns:
            ResearchOutput with final contract
        """
        if not extractions:
            return ResearchOutput(
                query=query,
                ticker=ticker,
                timestamp_utc=datetime.now(timezone.utc),
                summary="No content to reason about.",
            )

        # Prepare context for Claude
        extracted_texts = []
        for i, ext in enumerate(extractions):
            if ext.status == "extracted" and ext.structured_data:
                text = ext.structured_data.get("raw_text", "")[:500]
                extracted_texts.append(f"[Source {i+1}] ({ext.url})\n{text}")

        context = "\n\n".join(extracted_texts)

        system_prompt = """당신은 금융 리서치 전문가입니다.
제공된 웹 검색 결과와 기사 내용을 분석하여 투자 관점의 인사이트를 제공하십시오.
응답은 JSON 형식이어야 합니다."""

        prompt = f"""Query: {query}
Ticker: {ticker or 'N/A'}

위의 쿼리에 대한 검색 결과를 분석하고 다음 JSON을 반환하세요:
{{
  "sentiment": "bullish" | "bearish" | "neutral" | "mixed",
  "confidence": 0.0-1.0,
  "key_facts": ["fact1", "fact2", ...],
  "risk_factors": ["risk1", "risk2", ...],
  "summary": "2-3 문장 요약"
}}"""

        try:
            response_json = await self.reasoning.reason_with_json_output(
                prompt,
                context=context,
                system=system_prompt,
            )

            return ResearchOutput(
                ticker=ticker,
                query=query,
                timestamp_utc=datetime.now(timezone.utc),
                sources=[
                    {
                        "url": ext.url,
                        "extraction_status": ext.status,
                    }
                    for ext in extractions
                    if ext.status == "extracted"
                ],
                sentiment=response_json.get("sentiment", "neutral"),
                confidence=float(response_json.get("confidence", 0.5)),
                key_facts=response_json.get("key_facts", []),
                risk_factors=response_json.get("risk_factors", []),
                summary=response_json.get("summary", ""),
                model_used="claude-3-5-sonnet-latest",
            )
        except Exception as e:
            logger.error(f"Claude reasoning failed: {e}")
            # Return partial result on reasoning failure
            return ResearchOutput(
                ticker=ticker,
                query=query,
                timestamp_utc=datetime.now(timezone.utc),
                sources=[{"url": ext.url, "extraction_status": ext.status} for ext in extractions],
                summary=f"Reasoning failed: {str(e)}",
            )

    async def _store_research(
        self,
        query: str,
        search_results: list[SearchResult],
        extraction_results: list[ExtractionResult],
        output: ResearchOutput,
        ticker: Optional[str] = None,
    ) -> None:
        """
        Store research results in PostgreSQL (4-table structure).

        Args:
            query: Original query
            search_results: SearXNG results
            extraction_results: Extracted content
            output: Final research output
            ticker: Optional ticker
        """
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                # Insert into search_queries
                query_id = await conn.fetchval(
                    """
                    INSERT INTO search_queries (query, ticker, category, status, result_count)
                    VALUES ($1, $2, 'general', 'completed', $3)
                    RETURNING id
                    """,
                    query,
                    ticker,
                    len(search_results),
                )

                # Insert into search_results
                for i, sr in enumerate(search_results):
                    await conn.execute(
                        """
                        INSERT INTO search_results
                        (query_id, url, canonical_url, title, snippet, engine, rank, status)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, 'fetched')
                        """,
                        query_id,
                        sr.url,
                        sr.url,
                        sr.title,
                        sr.snippet,
                        sr.engine,
                        i + 1,
                    )

                # Insert into page_extractions
                extraction_ids = []
                for ext in extraction_results:
                    ext_id = await conn.fetchval(
                        """
                        INSERT INTO page_extractions
                        (search_result_id, structured_data, extraction_schema, status)
                        SELECT id, $1, $2, $3
                        FROM search_results
                        WHERE query_id = $4 AND url = $5
                        RETURNING id
                        """,
                        json.dumps(ext.structured_data),
                        ext.extraction_schema,
                        ext.status,
                        query_id,
                        ext.url,
                    )
                    if ext_id:
                        extraction_ids.append(ext_id)

                # Insert into research_outputs
                await conn.execute(
                    """
                    INSERT INTO research_outputs
                    (query_id, ticker, extraction_ids, output_data, model_used, status)
                    VALUES ($1, $2, $3, $4, $5, 'completed')
                    """,
                    query_id,
                    ticker,
                    extraction_ids,
                    json.dumps(output.dict(default=str)),
                    output.model_used,
                )

                logger.info(f"Research stored: query_id={query_id}, extraction_ids={extraction_ids}")

        except Exception as e:
            logger.error(f"Failed to store research results: {e}")
