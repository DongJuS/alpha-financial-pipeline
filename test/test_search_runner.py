from __future__ import annotations

"""
test/test_search_runner.py — SearchRunner + ResearchPortfolioManager 통합 테스트

SearchRunner의 StrategyRunner 프로토콜 준수, ResearchOutput → PredictionSignal 매핑,
캐싱 동작, 에러 핸들링을 검증합니다.
"""

import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.research_portfolio_manager import (
    ResearchPortfolioManager,
    research_output_to_signal,
)
from src.agents.search_agent import ResearchOutput, SearchAgent
from src.db.models import PredictionSignal


# ─────────────────────────────────────────────── 테스트용 Mock ──────────────────────────────────────────────


class MockSearchAgent:
    """테스트용 SearchAgent Mock."""

    def __init__(self, outputs: dict[str, ResearchOutput] | None = None):
        self.outputs = outputs or {}
        self.call_count = 0

    async def run_research(
        self,
        query: str,
        ticker: Optional[str] = None,
        category: str = "news",
        max_sources: int = 5,
    ) -> ResearchOutput:
        self.call_count += 1
        if ticker and ticker in self.outputs:
            return self.outputs[ticker]
        # 기본값: neutral sentiment
        return ResearchOutput(
            ticker=ticker,
            query=query,
            sentiment="neutral",
            confidence=0.5,
            sources=[],
            key_facts=[],
            risk_factors=[],
        )

    async def close(self) -> None:
        pass


# ─────────────────────────────────────────────── ResearchOutput → Signal 매핑 테스트 ──────────────────────────────────────────────


class TestResearchOutputToSignal(unittest.TestCase):
    """research_output_to_signal() 함수 테스트."""

    def test_bullish_sentiment_to_buy(self):
        """Bullish → BUY 매핑."""
        output = ResearchOutput(
            query="test",
            sentiment="bullish",
            confidence=0.9,
            sources=[{"url": "test", "title": "test"}],
            key_facts=["fact1"],
            risk_factors=[],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.signal, "BUY")
        self.assertEqual(signal.strategy, "S")
        self.assertGreater(signal.confidence, 0)

    def test_bearish_sentiment_to_sell(self):
        """Bearish → SELL 매핑."""
        output = ResearchOutput(
            query="test",
            sentiment="bearish",
            confidence=0.8,
            sources=[{"url": "test", "title": "test"}],
            key_facts=[],
            risk_factors=["risk1"],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.signal, "SELL")
        self.assertEqual(signal.confidence, 0.8)

    def test_neutral_sentiment_to_hold(self):
        """Neutral → HOLD 매핑."""
        output = ResearchOutput(
            query="test",
            sentiment="neutral",
            confidence=0.5,
            sources=[],
            key_facts=[],
            risk_factors=[],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.signal, "HOLD")

    def test_mixed_sentiment_to_hold(self):
        """Mixed → HOLD 매핑."""
        output = ResearchOutput(
            query="test",
            sentiment="mixed",
            confidence=0.6,
            sources=[{"url": "test", "title": "test"}],
            key_facts=["fact1"],
            risk_factors=["risk1"],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.signal, "HOLD")

    def test_low_confidence_threshold(self):
        """confidence < 0.3 → HOLD fallback."""
        output = ResearchOutput(
            query="test",
            sentiment="bullish",
            confidence=0.2,  # < 0.3
            sources=[{"url": "test", "title": "test"}],
            key_facts=[],
            risk_factors=[],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.signal, "HOLD")
        self.assertEqual(signal.confidence, 0.2)

    def test_no_sources_caps_confidence(self):
        """sources가 0개 → confidence를 0.3 이하로 하향."""
        output = ResearchOutput(
            query="test",
            sentiment="bullish",
            confidence=0.8,
            sources=[],  # 빈 리스트
            key_facts=["fact"],
            risk_factors=[],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertLessEqual(signal.confidence, 0.3)

    def test_confidence_normalization(self):
        """confidence가 1.0을 초과하면 클립."""
        output = ResearchOutput(
            query="test",
            sentiment="bullish",
            confidence=1.5,  # > 1.0
            sources=[{"url": "test", "title": "test"}],
            key_facts=[],
            risk_factors=[],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.confidence, 1.0)

    def test_confidence_rounding(self):
        """confidence는 4자리로 반올림."""
        output = ResearchOutput(
            query="test",
            sentiment="bullish",
            confidence=0.123456789,
            sources=[{"url": "test", "title": "test"}],
            key_facts=[],
            risk_factors=[],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        # 4자리 반올림 확인
        self.assertAlmostEqual(signal.confidence, 0.1235, places=4)

    def test_signal_metadata(self):
        """시그널 메타데이터 확인."""
        output = ResearchOutput(
            query="삼성전자",
            sentiment="bullish",
            confidence=0.8,
            sources=[{"url": "url1", "title": "title1"}, {"url": "url2", "title": "title2"}],
            key_facts=["fact1", "fact2", "fact3"],
            risk_factors=["risk1"],
        )
        signal = research_output_to_signal(output, "005930", date.today())
        self.assertEqual(signal.agent_id, "research_portfolio_manager")
        self.assertEqual(signal.strategy, "S")
        self.assertEqual(signal.ticker, "005930")
        self.assertIn("sentiment=bullish", signal.reasoning_summary)
        self.assertIn("sources=2", signal.reasoning_summary)


# ─────────────────────────────────────────────── ResearchPortfolioManager 테스트 ──────────────────────────────────────────────


class TestResearchPortfolioManager(unittest.IsolatedAsyncioTestCase):
    """ResearchPortfolioManager 테스트."""

    async def asyncSetUp(self):
        """각 테스트 전 초기화."""
        self.mock_search = MockSearchAgent()
        self.rpm = ResearchPortfolioManager(
            agent_id="test_research_portfolio_manager",
            search_agent=self.mock_search,
            max_concurrent_searches=2,
        )

    async def asyncTearDown(self):
        """각 테스트 후 정리."""
        await self.rpm.close()

    async def test_run_research_cycle_empty_tickers(self):
        """빈 티커 리스트 처리."""
        signals = await self.rpm.run_research_cycle([])
        self.assertEqual(signals, [])

    async def test_run_research_cycle_single_ticker(self):
        """단일 티커 리서치."""
        self.mock_search.outputs = {
            "005930": ResearchOutput(
                query="test",
                sentiment="bullish",
                confidence=0.9,
                sources=[{"url": "test", "title": "test"}],
                key_facts=[],
                risk_factors=[],
            )
        }
        signals = await self.rpm.run_research_cycle(["005930"])
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, "BUY")
        self.assertEqual(signals[0].strategy, "S")

    async def test_run_research_cycle_multiple_tickers(self):
        """다중 티커 병렬 리서치."""
        self.mock_search.outputs = {
            "005930": ResearchOutput(
                query="test", sentiment="bullish", confidence=0.9, sources=[{"url": "test", "title": "test"}]
            ),
            "000660": ResearchOutput(
                query="test", sentiment="bearish", confidence=0.8, sources=[{"url": "test", "title": "test"}]
            ),
        }
        signals = await self.rpm.run_research_cycle(["005930", "000660"])
        self.assertEqual(len(signals), 2)
        by_ticker = {s.ticker: s for s in signals}
        self.assertEqual(by_ticker["005930"].signal, "BUY")
        self.assertEqual(by_ticker["000660"].signal, "SELL")

    async def test_run_research_cycle_with_ticker_names(self):
        """ticker_names 파라미터 전달."""
        ticker_names = {"005930": "삼성전자"}
        self.mock_search.outputs = {
            "005930": ResearchOutput(
                query="test", sentiment="bullish", confidence=0.9, sources=[{"url": "test", "title": "test"}]
            )
        }
        signals = await self.rpm.run_research_cycle(["005930"], ticker_names=ticker_names)
        self.assertEqual(len(signals), 1)
        # query 생성에 ticker_name이 사용되는지 확인
        self.assertIn("삼성전자", self.mock_search.outputs["005930"].query)

    async def test_build_query_with_name(self):
        """쿼리 생성 with ticker name."""
        query = self.rpm._build_query("005930", "삼성전자")
        self.assertIn("삼성전자", query)
        self.assertIn("005930", query)
        self.assertIn("주식", query)

    async def test_build_query_without_name(self):
        """쿼리 생성 without ticker name."""
        query = self.rpm._build_query("005930")
        self.assertIn("005930", query)
        self.assertNotIn("삼성전자", query)

    async def test_error_handling_single_ticker_failure(self):
        """단일 티커 리서치 실패 → HOLD."""

        async def failing_research(*args, **kwargs):
            raise RuntimeError("검색 실패!")

        self.mock_search.run_research = failing_research
        signals = await self.rpm.run_research_cycle(["005930"])
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, "HOLD")
        self.assertEqual(signals[0].confidence, 0.0)
        self.assertIn("검색 실패", signals[0].reasoning_summary)

    async def test_error_handling_partial_failure(self):
        """일부 티커 실패 → 성공한 것만 정상."""
        call_count = [0]

        async def partial_failing_research(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("검색 실패!")
            return ResearchOutput(
                query="test", sentiment="bullish", confidence=0.9, sources=[{"url": "test", "title": "test"}]
            )

        self.mock_search.run_research = partial_failing_research
        signals = await self.rpm.run_research_cycle(["005930", "000660"])
        self.assertEqual(len(signals), 2)
        # 하나는 성공, 하나는 HOLD
        buy_signals = [s for s in signals if s.signal == "BUY"]
        hold_signals = [s for s in signals if s.signal == "HOLD"]
        self.assertEqual(len(buy_signals), 1)
        self.assertEqual(len(hold_signals), 1)

    @patch("src.agents.research_portfolio_manager.get_redis")
    async def test_caching_cache_hit(self, mock_get_redis):
        """캐시 히트 → SearchAgent 호출 안 함."""
        cached_signal = PredictionSignal(
            agent_id="research_portfolio_manager",
            llm_model="cached",
            strategy="S",
            ticker="005930",
            signal="BUY",
            confidence=0.9,
            trading_date=date.today(),
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(
            return_value='{"agent_id": "research_portfolio_manager", "llm_model": "cached", "strategy": "S", "ticker": "005930", "signal": "BUY", "confidence": 0.9, "trading_date": "2026-03-15"}'
        )
        mock_get_redis.return_value = mock_redis

        initial_call_count = self.mock_search.call_count
        signals = await self.rpm.run_research_cycle(["005930"])
        # SearchAgent 호출 안 됨 (캐시에서 로드)
        self.assertEqual(self.mock_search.call_count, initial_call_count)
        self.assertEqual(len(signals), 1)

    @patch("src.agents.research_portfolio_manager.get_redis")
    async def test_caching_cache_miss(self, mock_get_redis):
        """캐시 미스 → SearchAgent 호출."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_get_redis.return_value = mock_redis

        self.mock_search.outputs = {
            "005930": ResearchOutput(
                query="test", sentiment="bullish", confidence=0.9, sources=[{"url": "test", "title": "test"}]
            )
        }

        signals = await self.rpm.run_research_cycle(["005930"])
        # SearchAgent 호출됨
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, "BUY")
        # 캐시 저장 확인
        mock_redis.set.assert_called_once()


# ─────────────────────────────────────────────── SearchRunner StrategyRunner 준수 테스트 ──────────────────────────────────────────────


class TestSearchRunnerProtocol(unittest.IsolatedAsyncioTestCase):
    """SearchRunner가 StrategyRunner 프로토콜을 준수하는지 테스트."""

    async def asyncSetUp(self):
        """각 테스트 전 초기화."""
        from src.agents.search_runner import SearchRunner

        self.mock_search_agent = MockSearchAgent()
        self.rpm = ResearchPortfolioManager(
            search_agent=self.mock_search_agent,
        )
        self.runner = SearchRunner(self.rpm)

    async def asyncTearDown(self):
        """각 테스트 후 정리."""
        await self.rpm.close()

    async def test_runner_has_name(self):
        """Runner가 name 속성을 가짐."""
        self.assertEqual(self.runner.name, "S")

    async def test_runner_has_run_method(self):
        """Runner가 run() 메서드를 가짐."""
        self.assertTrue(hasattr(self.runner, "run"))
        self.assertTrue(callable(self.runner.run))

    async def test_runner_run_returns_prediction_signals(self):
        """run()이 PredictionSignal 리스트를 반환."""
        self.mock_search_agent.outputs = {
            "005930": ResearchOutput(
                query="test", sentiment="bullish", confidence=0.9, sources=[{"url": "test", "title": "test"}]
            )
        }
        tickers = ["005930"]
        signals = await self.runner.run(tickers)
        self.assertIsInstance(signals, list)
        self.assertTrue(all(isinstance(s, PredictionSignal) for s in signals))

    async def test_runner_run_with_multiple_tickers(self):
        """run()이 다중 티커를 처리."""
        self.mock_search_agent.outputs = {
            "005930": ResearchOutput(
                query="test", sentiment="bullish", confidence=0.9, sources=[{"url": "test", "title": "test"}]
            ),
            "000660": ResearchOutput(
                query="test", sentiment="bearish", confidence=0.8, sources=[{"url": "test", "title": "test"}]
            ),
        }
        signals = await self.runner.run(["005930", "000660"])
        self.assertEqual(len(signals), 2)


if __name__ == "__main__":
    unittest.main()
