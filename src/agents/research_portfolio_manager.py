"""
src/agents/research_portfolio_manager.py — ResearchPortfolioManager

검색/스크래핑 리서치 파이프라인을 관리하는 포트폴리오 매니저 에이전트.
SearchAgent를 사용해 종목별 리서치를 수행하고,
ResearchOutput을 PredictionSignal로 변환하여 N-way 블렌딩에 참여한다.

아키텍처:
- SearchAgent를 래핑하여 종목별 연구 조율
- 리서치 결과를 sentiment → signal 매핑으로 PredictionSignal 변환
- Redis 캐싱으로 동일 쿼리 중복 실행 방지
- 기존 PortfolioManagerAgent의 주문 권한을 침범하지 않음 (시그널만 생성)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

import asyncpg

from src.agents.search_agent import SearchAgent, ResearchOutput
from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import insert_heartbeat
from src.utils.logging import get_logger
from src.utils.redis_client import get_redis, set_heartbeat

logger = get_logger(__name__)


# ───────────────────────────────────────── Sentiment → Signal 매핑 ────────────────────────────────────────

SENTIMENT_TO_SIGNAL = {
    "bullish": "BUY",
    "bearish": "SELL",
    "neutral": "HOLD",
    "mixed": "HOLD",
}

# confidence 하한: 이 이하의 confidence면 HOLD로 fallback
MIN_CONFIDENCE_THRESHOLD = 0.3


def research_output_to_signal(
    output: ResearchOutput,
    ticker: str,
    trading_date: date,
) -> PredictionSignal:
    """ResearchOutput을 PredictionSignal로 변환한다.

    매핑 규칙:
    - sentiment → signal (bullish=BUY, bearish=SELL, neutral/mixed=HOLD)
    - confidence < MIN_CONFIDENCE_THRESHOLD → HOLD로 fallback
    - sources가 0개면 confidence를 0.3으로 하향
    """
    raw_signal = SENTIMENT_TO_SIGNAL.get(output.sentiment, "HOLD")
    confidence = max(0.0, min(1.0, output.confidence))

    # 소스가 없으면 confidence 하향
    if not output.sources:
        confidence = min(confidence, 0.3)

    # confidence가 너무 낮으면 HOLD로 fallback
    if confidence < MIN_CONFIDENCE_THRESHOLD:
        final_signal = "HOLD"
    else:
        final_signal = raw_signal

    # reasoning 요약: key_facts + risk_factors 압축
    key_facts_str = "; ".join(output.key_facts[:3]) if output.key_facts else "없음"
    risk_str = "; ".join(output.risk_factors[:2]) if output.risk_factors else "없음"
    reasoning = (
        f"[Search] sentiment={output.sentiment}, "
        f"sources={len(output.sources)}, "
        f"facts=[{key_facts_str}], "
        f"risks=[{risk_str}]"
    )

    return PredictionSignal(
        agent_id="research_portfolio_manager",
        llm_model=output.model_used,
        strategy="S",
        ticker=ticker,
        signal=final_signal,
        confidence=round(confidence, 4),
        target_price=None,
        stop_loss=None,
        reasoning_summary=reasoning[:500],
        trading_date=trading_date,
    )


# ───────────────────────────────────────── ResearchPortfolioManager ────────────────────────────────────────


class ResearchPortfolioManager:
    """검색/스크래핑 리서치 파이프라인을 관리하는 에이전트.

    역할:
    1. 종목별 리서치 쿼리 생성 및 SearchAgent 호출
    2. ResearchOutput → PredictionSignal 변환
    3. 캐시 관리 (Redis, TTL 4시간)
    4. 헬스비트 보고

    주의:
    - 직접 주문 권한 없음 (시그널만 생성)
    - 주문은 PortfolioManagerAgent를 통해서만 실행
    """

    CACHE_TTL_SECONDS = 4 * 3600  # 4시간
    CACHE_KEY_PREFIX = "research:signal:"

    def __init__(
        self,
        agent_id: str = "research_portfolio_manager",
        search_agent: Optional[SearchAgent] = None,
        db_pool: Optional[asyncpg.pool.Pool] = None,
        max_concurrent_searches: int = 3,
        search_categories: str = "news",
        max_sources_per_ticker: int = 5,
    ) -> None:
        self.agent_id = agent_id
        self.search_agent = search_agent or SearchAgent(db_pool=db_pool)
        self.max_concurrent = max_concurrent_searches
        self.search_categories = search_categories
        self.max_sources = max_sources_per_ticker
        self._semaphore = asyncio.Semaphore(max_concurrent_searches)

    async def close(self) -> None:
        """리소스 정리."""
        await self.search_agent.close()

    def _build_query(self, ticker: str, name: Optional[str] = None) -> str:
        """종목에 대한 검색 쿼리를 생성한다.

        Args:
            ticker: 종목코드 (예: "005930")
            name: 종목명 (예: "삼성전자"). None이면 ticker만 사용.

        Returns:
            검색 쿼리 문자열
        """
        if name:
            return f"{name} {ticker} 주식 투자 전망 최신"
        return f"{ticker} 한국 주식 투자 전망 최신"

    async def _get_cached_signal(self, ticker: str) -> Optional[PredictionSignal]:
        """Redis 캐시에서 기존 리서치 시그널을 조회한다."""
        try:
            redis = await get_redis()
            key = f"{self.CACHE_KEY_PREFIX}{ticker}"
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                return PredictionSignal(**data)
        except Exception as e:
            logger.debug("캐시 조회 실패 [%s]: %s", ticker, e)
        return None

    async def _cache_signal(self, ticker: str, signal: PredictionSignal) -> None:
        """PredictionSignal을 Redis에 캐싱한다."""
        try:
            redis = await get_redis()
            key = f"{self.CACHE_KEY_PREFIX}{ticker}"
            data = signal.model_dump(mode="json")
            await redis.set(key, json.dumps(data, default=str), ex=self.CACHE_TTL_SECONDS)
        except Exception as e:
            logger.debug("캐시 저장 실패 [%s]: %s", ticker, e)

    async def _research_single_ticker(
        self,
        ticker: str,
        name: Optional[str] = None,
    ) -> PredictionSignal:
        """단일 종목에 대해 리서치를 수행하고 PredictionSignal을 반환한다.

        캐시가 있으면 캐시를 사용하고, 없으면 SearchAgent를 호출한다.
        """
        # 캐시 확인
        cached = await self._get_cached_signal(ticker)
        if cached:
            logger.info("캐시 적중: ticker=%s, signal=%s", ticker, cached.signal)
            return cached

        # SearchAgent로 리서치 실행
        query = self._build_query(ticker, name)
        async with self._semaphore:
            try:
                output: ResearchOutput = await self.search_agent.run_research(
                    query,
                    ticker=ticker,
                    category=self.search_categories,
                    max_sources=self.max_sources,
                )
            except Exception as e:
                logger.error("리서치 실패 [%s]: %s", ticker, e)
                # 실패 시 HOLD 반환
                return PredictionSignal(
                    agent_id=self.agent_id,
                    llm_model="search_fallback",
                    strategy="S",
                    ticker=ticker,
                    signal="HOLD",
                    confidence=0.0,
                    reasoning_summary=f"[Search] 리서치 실패: {str(e)[:200]}",
                    trading_date=date.today(),
                )

        # ResearchOutput → PredictionSignal 변환
        signal = research_output_to_signal(output, ticker, date.today())

        # 캐시 저장
        await self._cache_signal(ticker, signal)

        logger.info(
            "리서치 완료: ticker=%s, sentiment=%s, signal=%s, confidence=%.2f",
            ticker,
            output.sentiment,
            signal.signal,
            signal.confidence or 0,
        )
        return signal

    async def run_research_cycle(
        self,
        tickers: list[str],
        ticker_names: Optional[dict[str, str]] = None,
    ) -> list[PredictionSignal]:
        """여러 종목에 대해 병렬로 리서치를 수행한다.

        Args:
            tickers: 종목코드 리스트
            ticker_names: {종목코드: 종목명} 딕셔너리 (선택)

        Returns:
            종목별 PredictionSignal 리스트
        """
        if not tickers:
            return []

        ticker_names = ticker_names or {}
        start_time = datetime.now(timezone.utc)

        tasks = [
            self._research_single_ticker(
                ticker,
                name=ticker_names.get(ticker),
            )
            for ticker in tickers
        ]

        signals = await asyncio.gather(*tasks, return_exceptions=True)

        # 예외를 HOLD 시그널로 변환
        results: list[PredictionSignal] = []
        errors = 0
        for ticker, result in zip(tickers, signals):
            if isinstance(result, Exception):
                logger.error("리서치 예외 [%s]: %s", ticker, result)
                errors += 1
                results.append(
                    PredictionSignal(
                        agent_id=self.agent_id,
                        llm_model="search_error",
                        strategy="S",
                        ticker=ticker,
                        signal="HOLD",
                        confidence=0.0,
                        reasoning_summary=f"[Search] 리서치 예외: {str(result)[:200]}",
                        trading_date=date.today(),
                    )
                )
            else:
                results.append(result)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        # 헬스비트 기록
        status = "healthy" if errors == 0 else ("degraded" if errors < len(tickers) else "error")
        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status=status,
                last_action=(
                    f"리서치 사이클 완료: {len(tickers)}종목, "
                    f"{errors}건 오류, {elapsed:.1f}s"
                ),
                metrics={
                    "tickers": len(tickers),
                    "errors": errors,
                    "elapsed_seconds": round(elapsed, 2),
                    "signals": {
                        "BUY": sum(1 for s in results if s.signal == "BUY"),
                        "SELL": sum(1 for s in results if s.signal == "SELL"),
                        "HOLD": sum(1 for s in results if s.signal == "HOLD"),
                    },
                },
            )
        )

        logger.info(
            "ResearchPortfolioManager 사이클 완료: %d종목, %d오류, %.1fs",
            len(tickers),
            errors,
            elapsed,
        )
        return results

    async def get_research_summary(self, ticker: str) -> Optional[dict]:
        """특정 종목의 최근 리서치 요약을 반환한다 (대시보드용)."""
        cached = await self._get_cached_signal(ticker)
        if cached:
            return {
                "ticker": ticker,
                "signal": cached.signal,
                "confidence": cached.confidence,
                "reasoning": cached.reasoning_summary,
                "strategy": "S",
                "agent_id": cached.agent_id,
            }
        return None
