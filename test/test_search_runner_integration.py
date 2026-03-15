"""
test/test_search_runner_integration.py — SearchRunner Integration Tests

SearchRunner의 StrategyRunner 프로토콜 준수, 통합 등록, 가중치 설정을 검증합니다.
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.research_portfolio_manager import ResearchPortfolioManager
from src.agents.search_agent import ResearchOutput, SearchAgent
from src.agents.search_runner import SearchRunner
from src.agents.strategy_runner import StrategyRunner
from src.db.models import PredictionSignal
from src.utils.config import get_settings


# ─────────────────────────────────────────────── Mock SearchAgent ──────────────────────────────────────────────


class MockSearchAgent:
    """テスト用 SearchAgent Mock."""

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


# ─────────────────────────────────────────────── SearchRunner Protocol 준수 테스트 ──────────────────────────────────────────────


class TestSearchRunnerProtocol(unittest.IsolatedAsyncioTestCase):
    """SearchRunner가 StrategyRunner 프로토콜을 준수하는지 테스트."""

    async def asyncSetUp(self):
        """각 테스트 전 초기화."""
        self.mock_search_agent = MockSearchAgent()
        self.rpm = ResearchPortfolioManager(
            search_agent=self.mock_search_agent,
        )
        self.runner = SearchRunner(self.rpm)

    async def asyncTearDown(self):
        """각 테스트 후 정리."""
        await self.rpm.close()

    async def test_runner_implements_protocol(self):
        """SearchRunner가 StrategyRunner 프로토콜을 구현하는지 확인."""
        # StrategyRunner 프로토콜 확인: name, run() 메서드
        self.assertTrue(hasattr(self.runner, "name"))
        self.assertEqual(self.runner.name, "S")
        self.assertTrue(callable(self.runner.run))

    async def test_runner_name_is_s(self):
        """Runner의 name 속성이 'S'."""
        self.assertEqual(self.runner.name, "S")

    async def test_runner_run_returns_prediction_signals(self):
        """run()이 PredictionSignal 리스트를 반환."""
        self.mock_search_agent.outputs = {
            "005930": ResearchOutput(
                query="test",
                sentiment="bullish",
                confidence=0.9,
                sources=[{"url": "test", "title": "test"}],
                key_facts=["fact1"],
                risk_factors=[],
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
                query="test",
                sentiment="bullish",
                confidence=0.9,
                sources=[{"url": "test", "title": "test"}],
                key_facts=[],
                risk_factors=[],
            ),
            "000660": ResearchOutput(
                query="test",
                sentiment="bearish",
                confidence=0.8,
                sources=[{"url": "test", "title": "test"}],
                key_facts=[],
                risk_factors=["risk1"],
            ),
        }
        signals = await self.runner.run(["005930", "000660"])
        self.assertEqual(len(signals), 2)
        by_ticker = {s.ticker: s for s in signals}
        self.assertEqual(by_ticker["005930"].signal, "BUY")
        self.assertEqual(by_ticker["000660"].signal, "SELL")

    async def test_runner_run_empty_tickers(self):
        """빈 티커 리스트 처리."""
        signals = await self.runner.run([])
        self.assertEqual(signals, [])

    async def test_runner_error_handling(self):
        """리서치 실패 시 빈 리스트 반환."""

        async def failing_research(*args, **kwargs):
            raise RuntimeError("검색 실패!")

        self.mock_search_agent.run_research = failing_research
        signals = await self.runner.run(["005930"])
        # 에러 핸들링: 빈 리스트 반환
        self.assertEqual(signals, [])

    async def test_runner_partial_failure(self):
        """일부 티커 실패 시에도 성공한 신호 반환."""
        call_count = [0]

        async def partial_failing_research(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("검색 실패!")
            return ResearchOutput(
                query="test",
                sentiment="bullish",
                confidence=0.9,
                sources=[{"url": "test", "title": "test"}],
                key_facts=[],
                risk_factors=[],
            )

        self.mock_search_agent.run_research = partial_failing_research
        signals = await self.runner.run(["005930", "000660"])
        # 하나는 성공, 하나는 실패 but 결과는 모두 반환 (HOLD로 처리됨)
        self.assertEqual(len(signals), 2)


# ─────────────────────────────────────────────── Strategy Blend Weights 테스트 ──────────────────────────────────────────────


class TestStrategyBlendWeights(unittest.TestCase):
    """Strategy S 가중치가 블렌딩 설정에 포함되었는지 확인."""

    def test_strategy_s_in_config(self):
        """config.py의 STRATEGY_BLEND_WEIGHTS에 'S'가 포함되는지 확인."""
        settings = get_settings()
        # strategy_blend_weights는 JSON 문자열로 저장됨
        weights_str = settings.strategy_blend_weights
        weights = json.loads(weights_str)
        self.assertIn("S", weights)
        self.assertEqual(weights["S"], 0.20)

    def test_blend_weights_sum_to_one(self):
        """블렌드 가중치의 합이 1.0이어야 함."""
        settings = get_settings()
        weights_str = settings.strategy_blend_weights
        weights = json.loads(weights_str)
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_all_expected_strategies_present(self):
        """A, B, S, RL 전략이 모두 포함되어 있어야 함."""
        settings = get_settings()
        weights_str = settings.strategy_blend_weights
        weights = json.loads(weights_str)
        expected_strategies = ["A", "B", "S", "RL"]
        for strategy in expected_strategies:
            self.assertIn(strategy, weights)

    def test_strategy_s_weight_is_0_20(self):
        """Strategy S의 가중치가 0.20이어야 함."""
        settings = get_settings()
        weights_str = settings.strategy_blend_weights
        weights = json.loads(weights_str)
        self.assertEqual(weights["S"], 0.20)


# ─────────────────────────────────────────────── Orchestrator 통합 테스트 ──────────────────────────────────────────────


class TestOrchestratorSearchRunnerIntegration(unittest.IsolatedAsyncioTestCase):
    """Orchestrator에 SearchRunner 통합 시 정상 작동 확인."""

    async def asyncSetUp(self):
        """각 테스트 전 초기화."""
        from src.agents.orchestrator import OrchestratorAgent

        self.orchestrator = OrchestratorAgent()
        self.mock_search_agent = MockSearchAgent()
        self.rpm = ResearchPortfolioManager(
            search_agent=self.mock_search_agent,
        )
        self.runner = SearchRunner(self.rpm)

    async def asyncTearDown(self):
        """각 테스트 후 정리."""
        await self.rpm.close()

    async def test_register_search_runner(self):
        """Orchestrator에 SearchRunner 등록."""
        self.orchestrator.register_strategy(self.runner)
        registered = self.orchestrator.registry.get("S")
        self.assertIsNotNone(registered)
        self.assertEqual(registered.name, "S")

    async def test_list_runners_includes_search_runner(self):
        """등록된 러너 목록에 S가 포함됨."""
        self.orchestrator.register_strategy(self.runner)
        runners = self.orchestrator.registry.list_runners()
        self.assertIn("S", runners)

    async def test_run_strategies_with_search_runner(self):
        """Orchestrator가 SearchRunner를 포함하여 run_strategies 실행."""
        self.mock_search_agent.outputs = {
            "005930": ResearchOutput(
                query="test",
                sentiment="bullish",
                confidence=0.9,
                sources=[{"url": "test", "title": "test"}],
                key_facts=[],
                risk_factors=[],
            )
        }
        self.orchestrator.register_strategy(self.runner)
        results = await self.orchestrator.run_strategies(["005930"])
        self.assertIn("S", results)
        self.assertEqual(len(results["S"]), 1)
        self.assertEqual(results["S"][0].signal, "BUY")

    async def test_run_strategies_blend_weights_include_s(self):
        """Orchestrator의 blend_weights에 S가 포함됨."""
        self.assertIn("S", self.orchestrator.strategy_blend_weights)
        self.assertEqual(self.orchestrator.strategy_blend_weights["S"], 0.20)


if __name__ == "__main__":
    unittest.main()
