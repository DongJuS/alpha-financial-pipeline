import unittest
from unittest.mock import AsyncMock

from src.agents.strategy_b_consensus import StrategyBConsensus


class StrategyBConsensusTest(unittest.IsolatedAsyncioTestCase):
    def _runner(self, threshold: float) -> StrategyBConsensus:
        runner = StrategyBConsensus.__new__(StrategyBConsensus)
        runner.consensus_threshold = threshold
        runner._role_config = AsyncMock(
            return_value={
                "agent_id": "consensus_synthesizer",
                "llm_model": "claude-3-5-sonnet-latest",
                "persona": "조정자",
            }
        )
        runner._ask_json_with_fallback = AsyncMock()
        return runner

    async def test_synthesize_rejects_low_confidence_below_threshold(self) -> None:
        runner = self._runner(threshold=0.67)
        runner._ask_json_with_fallback.return_value = {
            "final_signal": "BUY",
            "confidence": 0.61,
            "consensus_reached": True,
            "summary": "low confidence",
            "no_consensus_reason": None,
        }

        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.61, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertEqual(result.signal, "BUY")
        self.assertFalse(result.consensus_reached)
        self.assertEqual(result.no_consensus_reason, "confidence_below_threshold")

    async def test_synthesize_accepts_high_confidence_when_consensus_true(self) -> None:
        runner = self._runner(threshold=0.67)
        runner._ask_json_with_fallback.return_value = {
            "final_signal": "SELL",
            "confidence": 0.81,
            "consensus_reached": True,
            "summary": "high confidence",
            "no_consensus_reason": None,
        }

        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "SELL", "confidence": 0.81, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertEqual(result.signal, "SELL")
        self.assertTrue(result.consensus_reached)
        self.assertIsNone(result.no_consensus_reason)

    async def test_run_filters_failed_tickers(self) -> None:
        runner = StrategyBConsensus.__new__(StrategyBConsensus)
        runner._ensure_role_configs = AsyncMock(return_value={})
        runner.run_for_ticker = AsyncMock(side_effect=[RuntimeError("gemini quota"), "ok"])

        results = await runner.run(["005930", "000660"])

        self.assertEqual(results, ["ok"])


if __name__ == "__main__":
    unittest.main()
