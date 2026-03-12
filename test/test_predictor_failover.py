import types
import unittest
from unittest.mock import AsyncMock

from src.agents.predictor import PredictorAgent


def _build_candles(count: int = 20) -> list[dict]:
    candles: list[dict] = []
    for idx in range(count):
        price = 100_000 + (count - idx) * 100
        candles.append(
            {
                "timestamp_kst": f"2026-03-{count - idx:02d}T15:30:00+09:00",
                "open": price - 50,
                "high": price + 100,
                "low": price - 100,
                "close": price,
                "volume": 100_000 + idx,
            }
        )
    return candles


class PredictorFailoverTest(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_to_secondary_provider_when_primary_fails(self) -> None:
        agent = PredictorAgent(llm_model="gpt-4o-mini")
        agent.gpt = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(side_effect=RuntimeError("insufficient_quota")),
        )
        agent.claude = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(
                return_value={
                    "signal": "BUY",
                    "confidence": 0.79,
                    "target_price": 123456,
                    "stop_loss": 120000,
                    "reasoning_summary": "secondary claude success",
                }
            ),
        )
        agent.gemini = types.SimpleNamespace(
            is_configured=True,
            ask_json=AsyncMock(return_value={"signal": "SELL", "confidence": 0.6}),
        )

        result = await agent._llm_signal("005930", _build_candles())
        self.assertEqual(result["signal"], "BUY")
        self.assertEqual(result["target_price"], 123456)
        self.assertEqual(result["stop_loss"], 120000)
        agent.gpt.ask_json.assert_awaited_once()
        agent.claude.ask_json.assert_awaited_once()
        agent.gemini.ask_json.assert_not_awaited()

    async def test_returns_rule_signal_when_all_providers_unavailable(self) -> None:
        candles = _build_candles()
        agent = PredictorAgent(llm_model="claude-3-5-sonnet-latest")
        agent.claude = types.SimpleNamespace(is_configured=False, ask_json=AsyncMock())
        agent.gpt = types.SimpleNamespace(is_configured=False, ask_json=AsyncMock())
        agent.gemini = types.SimpleNamespace(is_configured=False, ask_json=AsyncMock())

        expected = agent._rule_based_signal(candles)
        result = await agent._llm_signal("005930", candles)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
