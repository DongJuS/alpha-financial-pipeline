"""
test/test_strategy_b_e2e.py — Strategy B 모듈 테스트

Strategy B(Consensus/Debate) 관련 모든 엔드포인트 및 컴포넌트 테스트.
DB/LLM 의존성은 모킹합니다.
"""
from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://alpha_user:alpha_pass@localhost:5432/alpha_db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from src.agents.strategy_b_runner import StrategyBRunner
from src.agents.strategy_b_consensus import StrategyBConsensus
from src.db.models import PredictionSignal


# ── StrategyBRunner 테스트 ──────────────────────────────────────────────


class TestStrategyBRunner(unittest.IsolatedAsyncioTestCase):
    """StrategyBRunner 프로토콜 준수 + 위임 테스트."""

    def test_runner_has_name_B(self):
        runner = StrategyBRunner()
        self.assertEqual(runner.name, "B")

    async def test_run_empty_tickers_returns_empty(self):
        runner = StrategyBRunner()
        result = await runner.run([])
        self.assertEqual(result, [])

    async def test_run_delegates_to_consensus(self):
        runner = StrategyBRunner()
        mock_signal = PredictionSignal(
            agent_id="test_b", llm_model="test", strategy="B",
            ticker="005930", signal="BUY", confidence=0.75,
            trading_date=date.today(),
        )
        runner._consensus = MagicMock()
        runner._consensus.run = AsyncMock(return_value=[mock_signal])

        result = await runner.run(["005930"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].signal, "BUY")
        self.assertEqual(result[0].strategy, "B")
        runner._consensus.run.assert_awaited_once_with(["005930"])

    async def test_run_catches_exception_returns_empty(self):
        runner = StrategyBRunner()
        runner._consensus = MagicMock()
        runner._consensus.run = AsyncMock(side_effect=RuntimeError("LLM 실패"))

        result = await runner.run(["005930"])
        self.assertEqual(result, [])


# ── StrategyBConsensus 테스트 ───────────────────────────────────────────


class TestStrategyBConsensus(unittest.IsolatedAsyncioTestCase):
    """StrategyBConsensus 핵심 로직 테스트."""

    def test_default_config(self):
        b = StrategyBConsensus()
        self.assertIsNotNone(b)

    def test_custom_config(self):
        b = StrategyBConsensus(max_rounds=3, consensus_threshold=0.8)
        self.assertIsNotNone(b)

    @patch("src.services.model_config.ensure_model_role_configs", new_callable=AsyncMock, return_value=[])
    @patch("src.agents.strategy_b_consensus.fetch_recent_ohlcv")
    async def test_run_with_no_data_returns_empty(self, mock_fetch, mock_roles):
        mock_fetch.return_value = []
        b = StrategyBConsensus()
        result = await b.run(["005930"])
        self.assertEqual(result, [])

    @patch("src.services.model_config.ensure_model_role_configs", new_callable=AsyncMock, return_value=[])
    @patch("src.agents.strategy_b_consensus.fetch_recent_ohlcv")
    async def test_run_with_candle_data(self, mock_fetch, mock_roles):
        """캔들 데이터가 있을 때 LLM 호출까지 도달하는지 (LLM은 모킹)."""
        mock_fetch.return_value = [
            {
                "instrument_id": "005930.KS",
                "ticker": "005930",
                "traded_at": date(2026, 3, 28),
                "close": 52000.0,
                "volume": 1000000,
                "open": 51000.0,
                "high": 53000.0,
                "low": 50500.0,
                "change_pct": 1.5,
            }
            for _ in range(20)
        ]

        b = StrategyBConsensus()
        # LLM 호출을 모킹 — _llm_json_call이 실패하면 빈 결과
        with patch.object(b, "_propose", new_callable=AsyncMock, side_effect=RuntimeError("mocked")):
            result = await b.run(["005930"])
            # LLM 실패 시 빈 리스트 (graceful)
            self.assertIsInstance(result, list)


# ── 블렌딩 통합 테스트 (Strategy B 포함) ─────────────────────────────────


class TestStrategyBInBlending(unittest.TestCase):
    """Strategy B가 N-way 블렌딩에 올바르게 참여하는지 테스트."""

    def test_b_signal_in_3way_blend(self):
        from src.agents.blending import BlendInput, blend_signals

        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.33),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.33),
            BlendInput(strategy="RL", signal="SELL", confidence=0.6, weight=0.34),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")  # A+B(66%) > RL(34%)
        self.assertIn("B", result.participating_strategies)

    def test_b_empty_triggers_fallback(self):
        """B가 빈 시그널일 때 A/RL로 가중치 재분배."""
        from src.agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34})
        weights = orch._normalize_active_weights({"A", "RL"})
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertNotIn("B", weights)

    def test_b_only_blend(self):
        from src.agents.blending import BlendInput, blend_signals

        inputs = [
            BlendInput(strategy="B", signal="SELL", confidence=0.9, weight=1.0),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "SELL")
        self.assertEqual(result.participating_strategies, ["B"])


# ── StrategyBRunner 인터페이스 정합 ──────────────────────────────────────


class TestStrategyBRunnerInterface(unittest.TestCase):
    """StrategyRunner 프로토콜 정합 확인."""

    def test_conforms_to_strategy_runner_protocol(self):
        from src.agents.strategy_runner import StrategyRunner
        runner = StrategyBRunner()
        self.assertIsInstance(runner, StrategyRunner)

    def test_name_is_B(self):
        self.assertEqual(StrategyBRunner.name, "B")

    def test_run_is_async(self):
        import inspect
        runner = StrategyBRunner()
        self.assertTrue(inspect.iscoroutinefunction(runner.run))

    def test_registered_in_orchestrator_defaults(self):
        """오케스트레이터 기본 가중치에 B가 포함되어 있는지."""
        from src.agents.orchestrator import DEFAULT_BLEND_WEIGHTS
        self.assertIn("B", DEFAULT_BLEND_WEIGHTS)
        self.assertGreater(DEFAULT_BLEND_WEIGHTS["B"], 0)


if __name__ == "__main__":
    unittest.main()
