import unittest
from unittest.mock import AsyncMock

from src.agents.strategy_b_consensus import StrategyBConsensus
from src.llm.router import LLMRouter


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
        runner.router = LLMRouter()
        runner.router.ask_json = AsyncMock()
        return runner

    async def test_synthesize_rejects_low_confidence_below_threshold(self) -> None:
        runner = self._runner(threshold=0.67)
        runner.router.ask_json.return_value = {
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
        runner.router.ask_json.return_value = {
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


class StrategyBConsensusEdgeCaseTest(unittest.IsolatedAsyncioTestCase):
    """에지 케이스: 경계값, 예외 상황."""

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
        runner.router = LLMRouter()
        runner.router.ask_json = AsyncMock()
        return runner

    async def test_synthesize_exact_threshold_confidence_passes(self) -> None:
        """confidence가 threshold와 정확히 같으면 consensus 통과 (>=)."""
        runner = self._runner(threshold=0.70)
        runner.router.ask_json.return_value = {
            "final_signal": "BUY",
            "confidence": 0.70,
            "consensus_reached": True,
            "summary": "exactly at threshold",
            "no_consensus_reason": None,
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.70, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        # confidence >= threshold → consensus reached
        self.assertTrue(result.consensus_reached)

    async def test_synthesize_just_below_threshold_fails(self) -> None:
        """confidence가 threshold보다 약간 낮으면 consensus 미달."""
        runner = self._runner(threshold=0.70)
        runner.router.ask_json.return_value = {
            "final_signal": "BUY",
            "confidence": 0.69,
            "consensus_reached": True,
            "summary": "just below threshold",
            "no_consensus_reason": None,
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.69, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertFalse(result.consensus_reached)
        self.assertEqual(result.no_consensus_reason, "confidence_below_threshold")

    async def test_synthesize_hold_signal(self) -> None:
        """HOLD 시그널도 정상 처리."""
        runner = self._runner(threshold=0.50)
        runner.router.ask_json.return_value = {
            "final_signal": "HOLD",
            "confidence": 0.85,
            "consensus_reached": True,
            "summary": "hold recommendation",
            "no_consensus_reason": None,
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "HOLD", "confidence": 0.85, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertEqual(result.signal, "HOLD")
        self.assertTrue(result.consensus_reached)

    async def test_synthesize_consensus_false_with_high_confidence(self) -> None:
        """LLM이 consensus_reached=False 반환하면 confidence 높아도 미합의."""
        runner = self._runner(threshold=0.50)
        runner.router.ask_json.return_value = {
            "final_signal": "BUY",
            "confidence": 0.95,
            "consensus_reached": False,
            "summary": "disagreement",
            "no_consensus_reason": "fundamental disagreement",
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.95, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertFalse(result.consensus_reached)

    async def test_run_all_tickers_fail(self) -> None:
        """모든 티커가 실패하면 빈 리스트."""
        runner = StrategyBConsensus.__new__(StrategyBConsensus)
        runner._ensure_role_configs = AsyncMock(return_value={})
        runner.run_for_ticker = AsyncMock(side_effect=RuntimeError("fail"))
        results = await runner.run(["005930", "000660"])
        self.assertEqual(results, [])

    async def test_run_empty_tickers(self) -> None:
        """빈 티커 목록 → 빈 결과."""
        runner = StrategyBConsensus.__new__(StrategyBConsensus)
        runner._ensure_role_configs = AsyncMock(return_value={})
        results = await runner.run([])
        self.assertEqual(results, [])


class StrategyBClampConfidenceTest(unittest.TestCase):
    """_clamp_confidence 경계값 테스트."""

    def test_clamp_negative_value(self) -> None:
        """음수 → 0.0으로 클램핑."""
        self.assertEqual(StrategyBConsensus._clamp_confidence(-0.5), 0.0)

    def test_clamp_zero(self) -> None:
        self.assertEqual(StrategyBConsensus._clamp_confidence(0.0), 0.0)

    def test_clamp_one(self) -> None:
        self.assertEqual(StrategyBConsensus._clamp_confidence(1.0), 1.0)

    def test_clamp_above_one(self) -> None:
        """1.0 초과 → 1.0으로 클램핑."""
        self.assertEqual(StrategyBConsensus._clamp_confidence(1.5), 1.0)

    def test_clamp_large_value(self) -> None:
        self.assertEqual(StrategyBConsensus._clamp_confidence(999.0), 1.0)

    def test_clamp_normal_value(self) -> None:
        self.assertAlmostEqual(StrategyBConsensus._clamp_confidence(0.73), 0.73)

    def test_clamp_very_small_positive(self) -> None:
        result = StrategyBConsensus._clamp_confidence(0.0001)
        self.assertAlmostEqual(result, 0.0001)


class StrategyBSynthesizeEdgeCaseTest(unittest.IsolatedAsyncioTestCase):
    """_synthesize 불일치 판정 에지케이스."""

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
        runner.router = LLMRouter()
        runner.router.ask_json = AsyncMock()
        return runner

    async def test_synthesize_invalid_signal_falls_back_to_hold(self) -> None:
        """LLM이 유효하지 않은 signal을 반환하면 HOLD로 대체."""
        runner = self._runner(threshold=0.50)
        runner.router.ask_json.return_value = {
            "final_signal": "STRONG_BUY",
            "confidence": 0.80,
            "consensus_reached": True,
            "summary": "invalid signal",
            "no_consensus_reason": None,
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.80, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertEqual(result.signal, "HOLD")

    async def test_synthesize_missing_confidence_uses_fallback(self) -> None:
        """LLM이 confidence를 누락하면 proposer의 fallback confidence 사용."""
        runner = self._runner(threshold=0.50)
        runner.router.ask_json.return_value = {
            "final_signal": "BUY",
            # "confidence" 키 누락
            "consensus_reached": True,
            "summary": "missing confidence",
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.65, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        # fallback confidence는 proposer의 0.65
        self.assertAlmostEqual(result.confidence, 0.65)

    async def test_synthesize_zero_threshold_always_consensus(self) -> None:
        """threshold=0.0이면 confidence > 0이면 항상 consensus."""
        runner = self._runner(threshold=0.0)
        runner.router.ask_json.return_value = {
            "final_signal": "SELL",
            "confidence": 0.01,
            "consensus_reached": True,
            "summary": "very low confidence",
            "no_consensus_reason": None,
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "SELL", "confidence": 0.01, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertTrue(result.consensus_reached)

    async def test_synthesize_threshold_one_always_fails(self) -> None:
        """threshold=1.0이면 confidence < 1.0인 한 항상 실패."""
        runner = self._runner(threshold=1.0)
        runner.router.ask_json.return_value = {
            "final_signal": "BUY",
            "confidence": 0.99,
            "consensus_reached": True,
            "summary": "nearly perfect",
            "no_consensus_reason": None,
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "BUY", "confidence": 0.99, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertFalse(result.consensus_reached)
        self.assertEqual(result.no_consensus_reason, "confidence_below_threshold")

    async def test_synthesize_no_consensus_reason_set_when_llm_says_no(self) -> None:
        """LLM이 consensus_reached=False + custom reason을 반환하면 이유가 보존된다."""
        runner = self._runner(threshold=0.50)
        runner.router.ask_json.return_value = {
            "final_signal": "SELL",
            "confidence": 0.90,
            "consensus_reached": False,
            "summary": "big disagreement",
            "no_consensus_reason": "fundamental_disagreement",
        }
        result = await runner._synthesize(
            ticker="005930",
            proposer={"signal": "SELL", "confidence": 0.90, "argument": "arg"},
            challenger1="c1",
            challenger2="c2",
            round_no=1,
        )
        self.assertFalse(result.consensus_reached)
        self.assertEqual(result.no_consensus_reason, "fundamental_disagreement")


if __name__ == "__main__":
    unittest.main()
