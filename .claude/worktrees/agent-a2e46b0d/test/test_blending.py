import unittest

from src.agents.blending import blend_strategy_signals


class BlendSignalsTest(unittest.TestCase):
    def test_blend_same_signal_keeps_signal_and_weighted_confidence(self) -> None:
        result = blend_strategy_signals(
            strategy_a_signal="BUY",
            strategy_a_confidence=0.8,
            strategy_b_signal="BUY",
            strategy_b_confidence=0.6,
            blend_ratio=0.25,
        )
        self.assertEqual(result.combined_signal, "BUY")
        self.assertFalse(result.conflict)
        self.assertEqual(result.combined_confidence, 0.75)

    def test_blend_conflict_returns_hold(self) -> None:
        result = blend_strategy_signals(
            strategy_a_signal="BUY",
            strategy_a_confidence=0.7,
            strategy_b_signal="SELL",
            strategy_b_confidence=0.9,
            blend_ratio=0.5,
        )
        self.assertEqual(result.combined_signal, "HOLD")
        self.assertTrue(result.conflict)
        self.assertEqual(result.combined_confidence, 0.8)

    def test_blend_invalid_signal_falls_back_to_hold_side(self) -> None:
        result = blend_strategy_signals(
            strategy_a_signal="INVALID",
            strategy_a_confidence=0.4,
            strategy_b_signal="BUY",
            strategy_b_confidence=0.6,
            blend_ratio=0.8,
        )
        self.assertEqual(result.combined_signal, "BUY")
        self.assertFalse(result.conflict)
        self.assertEqual(result.combined_confidence, 0.56)


if __name__ == "__main__":
    unittest.main()
