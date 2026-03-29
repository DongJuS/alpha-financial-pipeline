"""
src/utils/searxng_client.py — SearXNG JSON API Client

Provides async HTTP client for SearXNG search engine with rate limiting,
URL canonicalization, and error handling.
"""

import asyncio
import logging
import time
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    """Single search result from SearXNG API."""
    url: str
    title: str
    snippet: str
    engine: str
    category: str = "general"
    score: float = 0.0


class SearXNGClient:
    """Async SearXNG JSON API client with rate limiting and URL canonicalization."""

    def __init__(
        self,
        base_url: str = "http://localhost:8888",
        timeout: float = 10.0,
        rate_limit_delay: float = 1.0,
    ):
        """
        Initialize SearXNG client.

        Args:
            base_url: Base URL of SearXNG instance
            timeout: HTTP request timeout in seconds
            rate_limit_delay: Minimum delay (seconds) between requests to same domain
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self._domain_timestamps: dict[str, float] = {}
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """
        Canonicalize URL by removing tracking parameters and normalizing.

        Args:
            url: Raw URL string

        Returns:
            Canonical URL (stripped of common tracking params)
        """
        try:
            parsed = urlparse(url)
            # Remove common tracking parameters
            tracking_params = {
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_content",
                "utm_term",
                "fbclid",
                "gclid",
                "msclkid",
            }
            query_params = parse_qs(parsed.query, keep_blank_values=False)
            filtered_params = {
                k: v for k, v in query_params.items() if k not in tracking_params
            }
            # Reconstruct query string
            new_query = urlencode(filtered_params, doseq=True)
            canonical = (
                f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                f"{'?' + new_query if new_query else ''}"
            )
            return canonical
        except Exception as e:
            logger.warning(f"Failed to canonicalize URL {url}: {e}")
            return url

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL for rate limiting."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ""

    async def _apply_rate_limit(self, domain: str) -> None:
        """
        Apply rate limit: 1 request per second per domain.

        Args:
            domain: Domain name
        """
        now = time.time()
        last_request = self._domain_timestamps.get(domain, 0)
        elapsed = now - last_request
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._domain_timestamps[domain] = time.time()

    async def search(
        self,
        query: str,
        *,
        categories: str = "general",
        language: str = "ko",
        max_results: int = 10,
        max_retries: int = 3,
    ) -> list[SearchResult]:
        """
        Search via SearXNG JSON API with error handling and retries.

        Args:
            query: Search query string
            categories: SearXNG categories (e.g., "general", "news", "finance")
            language: Language code (e.g., "ko", "en")
            max_results: Maximum number of results to return
            max_retries: Number of retry attempts on failure

        Returns:
            List of SearchResult objects
        """
        client = await self._get_client()
        url = f"{self.base_url}/search"
        params = {
            "q": query,
            "format": "json",
            "categories": categories,
            "language": language,
            "pageno": 1,
        }

        for attempt in range(max_retries):
            try:
                # Apply rate limit before SearXNG domain
                await self._apply_rate_limit("searxng")

                logger.info(f"SearXNG search: {query} (attempt {attempt + 1}/{max_retries})")
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                results = []

                for item in data.get("results", [])[:max_results]:
                    # Canonicalize result URL
                    canonical_url = self._canonicalize_url(item.get("url", ""))
                    result = SearchResult(
                        url=canonical_url,
                        title=item.get("title", ""),
                        snippet=item.get("content", "")[:500],  # Truncate snippet
                        engine=item.get("engine", "unknown"),
                        category=categories,
                        score=float(item.get("score", 0.0)),
                    )
                    results.append(result)

                logger.info(f"SearXNG returned {len(results)} results")
                return results

            except httpx.HTTPError as e:
                logger.warning(f"SearXNG request failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"SearXNG search failed after {max_retries} retries: {e}")
                    return []
            except Exception as e:
                logger.error(f"Unexpected error in SearXNG search: {e}")
                return []

        return []

    async def search_batch(
        self,
        queries: list[str],
        *,
        categories: str = "general",
        language: str = "ko",
        max_results: int = 10,
    ) -> dict[str, list[SearchResult]]:
        """
        Execute multiple searches concurrently (respecting rate limits).

        Args:
            queries: List of search queries
            categories: SearXNG categories
            language: Language code
            max_results: Max results per query

        Returns:
            Dict mapping query to list of SearchResult objects
        """
        tasks = [
            self.search(
                q,
                categories=categories,
                language=language,
                max_results=max_results,
            )
            for q in queries
        ]
        results = await asyncio.gather(*tasks)
        return dict(zip(queries, results))
