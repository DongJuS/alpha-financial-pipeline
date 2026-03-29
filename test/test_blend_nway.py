from __future__ import annotations

"""
test/test_blend_nway.py — N-way 블렌딩 + StrategyRegistry + RL V2 시그널 매핑 통합 테스트
"""

import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.blending import BlendInput, BlendResult, NWayBlendResult, blend_signals, blend_strategy_signals, normalize_weights
from src.agents.strategy_runner import StrategyRegistry, StrategyRunner
from src.agents.rl_trading_v2 import map_v2_action_to_signal, normalize_q_confidence
from src.db.models import PredictionSignal


# ────────────────────────── 테스트용 Mock Runner ──────────────────────────


class MockRunner:
    """테스트용 StrategyRunner."""

    def __init__(self, name: str, signal: str = "BUY", confidence: float = 0.8) -> None:
        self.name = name
        self._signal = signal
        self._confidence = confidence

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        return [
            PredictionSignal(
                agent_id=f"mock_{self.name}",
                llm_model=f"mock_{self.name}",
                strategy=self.name if len(self.name) <= 2 else "A",
                ticker=ticker,
                signal=self._signal,
                confidence=self._confidence,
                trading_date=date.today(),
            )
            for ticker in tickers
        ]


class FailingRunner:
    """실행 중 예외를 던지는 Runner."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        raise RuntimeError(f"{self.name} runner 실패!")


# ────────────────────────── blend_signals() 테스트 ──────────────────────────


class TestBlendSignals(unittest.TestCase):
    """N-way blend_signals() 함수 테스트."""

    def test_empty_inputs(self):
        result = blend_signals([])
        self.assertEqual(result.signal, "HOLD")
        self.assertEqual(result.confidence, 0.0)
        self.assertFalse(result.conflict)
        self.assertEqual(result.participating_strategies, [])

    def test_single_strategy_buy(self):
        inputs = [BlendInput(strategy="A", signal="BUY", confidence=0.9, weight=1.0)]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")
        self.assertGreater(result.confidence, 0.0)
        self.assertFalse(result.conflict)

    def test_single_strategy_sell(self):
        inputs = [BlendInput(strategy="A", signal="SELL", confidence=0.9, weight=1.0)]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "SELL")

    def test_two_strategies_agree_buy(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.5),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.5),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")
        self.assertFalse(result.conflict)

    def test_two_strategies_conflict(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.5),
            BlendInput(strategy="B", signal="SELL", confidence=0.8, weight=0.5),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "HOLD")  # BUY와 SELL이 같은 가중치로 상쇄
        self.assertTrue(result.conflict)

    def test_three_strategies_nway(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.35),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.35),
            BlendInput(strategy="RL", signal="HOLD", confidence=0.5, weight=0.30),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")
        self.assertIn("A", result.participating_strategies)
        self.assertIn("B", result.participating_strategies)
        self.assertIn("RL", result.participating_strategies)
        self.assertFalse(result.conflict)

    def test_three_strategies_majority_sell(self):
        inputs = [
            BlendInput(strategy="A", signal="SELL", confidence=0.9, weight=0.4),
            BlendInput(strategy="B", signal="SELL", confidence=0.7, weight=0.3),
            BlendInput(strategy="RL", signal="BUY", confidence=0.5, weight=0.3),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "SELL")
        self.assertTrue(result.conflict)

    def test_weight_normalization(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=7.0),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=3.0),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")
        # 가중치가 합 1.0으로 정규화됨
        self.assertAlmostEqual(
            sum(result.meta["weights"].values()), 1.0, places=3
        )

    def test_zero_weight_normalization(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.0),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.0),
        ]
        normalized = normalize_weights(inputs)
        total = sum(inp.weight for inp in normalized)
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_invalid_signal_normalized_to_hold(self):
        inputs = [BlendInput(strategy="A", signal="INVALID", confidence=0.8, weight=1.0)]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "HOLD")

    def test_meta_contains_all_info(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.6),
            BlendInput(strategy="RL", signal="SELL", confidence=0.7, weight=0.4),
        ]
        result = blend_signals(inputs)
        self.assertIn("weights", result.meta)
        self.assertIn("signals", result.meta)
        self.assertIn("confidences", result.meta)
        self.assertIn("A", result.meta["weights"])
        self.assertIn("RL", result.meta["weights"])


# ────────────────────────── 기존 2-way 래퍼 하위 호환 ──────────────────────────


class TestBlendStrategySignalsCompat(unittest.TestCase):
    """기존 blend_strategy_signals() 함수가 하위 호환으로 동작하는지 테스트."""

    def test_both_buy(self):
        result = blend_strategy_signals("BUY", 0.8, "BUY", 0.7, 0.5)
        self.assertEqual(result.combined_signal, "BUY")
        self.assertFalse(result.conflict)

    def test_conflict_buy_sell(self):
        result = blend_strategy_signals("BUY", 0.8, "SELL", 0.8, 0.5)
        self.assertEqual(result.combined_signal, "HOLD")
        self.assertTrue(result.conflict)

    def test_a_only(self):
        result = blend_strategy_signals("BUY", 0.9, None, None, 0.3)
        self.assertEqual(result.combined_signal, "BUY")

    def test_b_only(self):
        result = blend_strategy_signals(None, None, "SELL", 0.9, 0.7)
        self.assertEqual(result.combined_signal, "SELL")


# ────────────────────────── StrategyRegistry 테스트 ──────────────────────────


class TestStrategyRegistry(unittest.IsolatedAsyncioTestCase):
    """StrategyRegistry 테스트."""

    def test_register_and_list(self):
        reg = StrategyRegistry()
        reg.register(MockRunner("A"))
        reg.register(MockRunner("B"))
        self.assertEqual(reg.active_names, ["A", "B"])
        self.assertEqual(reg.runner_count, 2)

    def test_unregister(self):
        reg = StrategyRegistry()
        reg.register(MockRunner("A"))
        reg.register(MockRunner("B"))
        reg.unregister("A")
        self.assertEqual(reg.active_names, ["B"])

    async def test_run_all(self):
        reg = StrategyRegistry()
        reg.register(MockRunner("A", "BUY", 0.8))
        reg.register(MockRunner("B", "SELL", 0.7))

        results = await reg.run_all(["005930", "035720"])
        self.assertIn("A", results)
        self.assertIn("B", results)
        self.assertEqual(len(results["A"]), 2)
        self.assertEqual(len(results["B"]), 2)
        self.assertEqual(results["A"][0].signal, "BUY")
        self.assertEqual(results["B"][0].signal, "SELL")

    async def test_run_selected(self):
        reg = StrategyRegistry()
        reg.register(MockRunner("A"))
        reg.register(MockRunner("B"))
        reg.register(MockRunner("RL", "HOLD", 0.5))

        results = await reg.run_selected(["005930"], ["A", "RL"])
        self.assertIn("A", results)
        self.assertIn("RL", results)
        self.assertNotIn("B", results)

    async def test_failing_runner_returns_empty(self):
        reg = StrategyRegistry()
        reg.register(MockRunner("A", "BUY", 0.8))
        reg.register(FailingRunner("B"))

        results = await reg.run_all(["005930"])
        self.assertEqual(len(results["A"]), 1)
        self.assertEqual(len(results["B"]), 0)  # 실패한 Runner는 빈 리스트

    async def test_empty_registry_returns_empty(self):
        reg = StrategyRegistry()
        results = await reg.run_all(["005930"])
        self.assertEqual(results, {})

    async def test_run_selected_missing_strategy(self):
        reg = StrategyRegistry()
        reg.register(MockRunner("A"))

        results = await reg.run_selected(["005930"], ["A", "NONEXISTENT"])
        self.assertIn("A", results)
        self.assertNotIn("NONEXISTENT", results)


# ────────────────────────── RL V2 시그널 매핑 테스트 ──────────────────────────


class TestRLV2SignalMapping(unittest.TestCase):
    """map_v2_action_to_signal() 테스트."""

    def test_buy(self):
        self.assertEqual(map_v2_action_to_signal("BUY"), "BUY")

    def test_sell(self):
        self.assertEqual(map_v2_action_to_signal("SELL"), "SELL")

    def test_hold(self):
        self.assertEqual(map_v2_action_to_signal("HOLD"), "HOLD")

    def test_close_maps_to_hold(self):
        self.assertEqual(map_v2_action_to_signal("CLOSE"), "HOLD")

    def test_unknown_maps_to_hold(self):
        self.assertEqual(map_v2_action_to_signal("UNKNOWN"), "HOLD")

    def test_case_insensitive(self):
        self.assertEqual(map_v2_action_to_signal("buy"), "BUY")
        self.assertEqual(map_v2_action_to_signal("Sell"), "SELL")
        self.assertEqual(map_v2_action_to_signal("close"), "HOLD")


# ────────────────────────── normalize_q_confidence 테스트 ──────────────────────────


class TestNormalizeQConfidence(unittest.TestCase):
    """normalize_q_confidence() 테스트."""

    def test_empty_q_values(self):
        self.assertEqual(normalize_q_confidence({}), 0.5)

    def test_equal_q_values(self):
        result = normalize_q_confidence({"BUY": 0.1, "SELL": 0.1, "HOLD": 0.1})
        self.assertEqual(result, 0.5)

    def test_large_spread_high_confidence(self):
        result = normalize_q_confidence({"BUY": 0.5, "SELL": -0.3, "HOLD": 0.0})
        self.assertGreater(result, 0.8)
        self.assertLessEqual(result, 0.95)

    def test_small_spread_low_confidence(self):
        result = normalize_q_confidence({"BUY": 0.01, "SELL": 0.0, "HOLD": 0.005})
        self.assertGreaterEqual(result, 0.3)
        self.assertLess(result, 0.7)

    def test_confidence_range(self):
        """confidence는 항상 0.3~0.95 범위."""
        for spread in [0.0, 0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 10.0]:
            result = normalize_q_confidence({"BUY": spread, "SELL": 0.0})
            self.assertGreaterEqual(result, 0.3)
            self.assertLessEqual(result, 0.95)


# ────────────────────────── 가중치 정규화 검증 ──────────────────────────


class TestWeightNormalization(unittest.TestCase):
    """가중치 자동 정규화 검증."""

    def test_already_normalized(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.5),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.5),
        ]
        normalized = normalize_weights(inputs)
        total = sum(inp.weight for inp in normalized)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_unnormalized(self):
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=3.5),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=3.5),
            BlendInput(strategy="RL", signal="HOLD", confidence=0.5, weight=3.0),
        ]
        normalized = normalize_weights(inputs)
        total = sum(inp.weight for inp in normalized)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_single_weight(self):
        inputs = [BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=5.0)]
        normalized = normalize_weights(inputs)
        self.assertAlmostEqual(normalized[0].weight, 1.0, places=6)


# ────────────────────────── PredictionSignal / PaperOrderRequest 모델 테스트 ──────────────────────────


class TestModelUpdates(unittest.TestCase):
    """models.py 변경사항 테스트."""

    def test_prediction_signal_new_strategies(self):
        """strategy에 'S', 'L' 허용 확인."""
        for strat in ("A", "B", "RL", "S", "L"):
            sig = PredictionSignal(
                agent_id="test",
                llm_model="test",
                strategy=strat,
                ticker="005930",
                signal="HOLD",
                trading_date=date.today(),
            )
            self.assertEqual(sig.strategy, strat)

    def test_prediction_signal_is_shadow(self):
        """is_shadow 필드 기본값 테스트."""
        sig = PredictionSignal(
            agent_id="test",
            llm_model="test",
            ticker="005930",
            signal="BUY",
            trading_date=date.today(),
        )
        self.assertFalse(sig.is_shadow)

        sig_shadow = PredictionSignal(
            agent_id="test",
            llm_model="test",
            ticker="005930",
            signal="BUY",
            trading_date=date.today(),
            is_shadow=True,
        )
        self.assertTrue(sig_shadow.is_shadow)

    def test_paper_order_blend_meta(self):
        """PaperOrderRequest에 blend_meta 필드 확인."""
        from src.db.models import PaperOrderRequest

        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            price=70000,
            blend_meta={"strategies": ["A", "B", "RL"], "weights": {"A": 0.35, "B": 0.35, "RL": 0.30}},
        )
        self.assertIsNotNone(order.blend_meta)
        self.assertEqual(order.blend_meta["strategies"], ["A", "B", "RL"])

    def test_paper_order_no_blend_meta(self):
        """blend_meta 없이도 동작 확인."""
        from src.db.models import PaperOrderRequest

        order = PaperOrderRequest(
            ticker="005930",
            name="삼성전자",
            signal="BUY",
            price=70000,
        )
        self.assertIsNone(order.blend_meta)


# ────────────────────────── RL 독립 실행 패턴 테스트 ──────────────────────────


class TestRLIndependentExecution(unittest.TestCase):
    """RL이 블렌딩에 참여하지 않고 독립적으로 실행되는 패턴을 테스트한다.

    Orchestrator에서 RL을 분리하여 실행하는 로직의 단위 테스트.
    """

    def test_rl_separated_from_blend_inputs(self):
        """A, B, RL 3개 전략 결과에서 RL을 분리하면 A/B만 블렌딩에 참여한다."""
        # 전략 실행 결과 (Orchestrator.registry.run_all() 결과와 동일 형태)
        all_predictions = {
            "A": [PredictionSignal(
                agent_id="mock_A", llm_model="mock", strategy="A",
                ticker="005930", signal="BUY", confidence=0.8, trading_date=date.today(),
            )],
            "B": [PredictionSignal(
                agent_id="mock_B", llm_model="mock", strategy="B",
                ticker="005930", signal="BUY", confidence=0.7, trading_date=date.today(),
            )],
            "RL": [PredictionSignal(
                agent_id="rl_agent", llm_model="tabular-q", strategy="RL",
                ticker="005930", signal="SELL", confidence=0.9, trading_date=date.today(),
            )],
        }

        # RL 분리
        rl_predictions = all_predictions.pop("RL", [])
        non_rl_predictions = all_predictions

        # RL이 분리되었는지 확인
        self.assertEqual(len(rl_predictions), 1)
        self.assertEqual(rl_predictions[0].signal, "SELL")
        self.assertNotIn("RL", non_rl_predictions)

        # A/B만 블렌딩
        blend_inputs = []
        weights = {"A": 0.5, "B": 0.5}
        for strategy_name, preds in non_rl_predictions.items():
            for pred in preds:
                blend_inputs.append(BlendInput(
                    strategy=strategy_name,
                    signal=pred.signal,
                    confidence=pred.confidence or 0.5,
                    weight=weights.get(strategy_name, 0.5),
                ))

        result = blend_signals(blend_inputs)
        # A/B 둘 다 BUY이므로 블렌딩 결과도 BUY
        self.assertEqual(result.signal, "BUY")
        # RL은 블렌딩에 참여하지 않음
        self.assertNotIn("RL", result.participating_strategies)
        self.assertEqual(sorted(result.participating_strategies), ["A", "B"])

    def test_rl_independent_signal_preserved(self):
        """RL의 독립 시그널이 블렌딩에 의해 변형되지 않는다."""
        # RL이 SELL을 결정했지만 A/B가 BUY인 경우
        rl_signal = PredictionSignal(
            agent_id="rl_agent", llm_model="tabular-q", strategy="RL",
            ticker="005930", signal="SELL", confidence=0.95, trading_date=date.today(),
        )

        # RL 시그널은 그대로 유지됨 (블렌딩 없음)
        self.assertEqual(rl_signal.signal, "SELL")
        self.assertEqual(rl_signal.confidence, 0.95)

    def test_rl_only_mode_no_blending(self):
        """RL만 단독 실행 시 블렌딩 없이 직접 전달된다."""
        all_predictions = {
            "RL": [PredictionSignal(
                agent_id="rl_agent", llm_model="tabular-q", strategy="RL",
                ticker="005930", signal="BUY", confidence=0.85, trading_date=date.today(),
            )],
        }

        rl_predictions = all_predictions.pop("RL", [])
        non_rl_predictions = all_predictions

        # 비-RL 전략이 없으므로 블렌딩 불필요
        self.assertEqual(len(non_rl_predictions), 0)
        # RL 시그널만 직접 PortfolioManager에 전달
        self.assertEqual(len(rl_predictions), 1)
        self.assertEqual(rl_predictions[0].signal, "BUY")

    def test_ab_blend_rl_independent_different_decisions(self):
        """A/B 블렌딩 결과와 RL 독립 결정이 서로 다를 수 있다."""
        # A: BUY, B: SELL → 블렌딩 결과 HOLD
        ab_inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.5),
            BlendInput(strategy="B", signal="SELL", confidence=0.8, weight=0.5),
        ]
        blend_result = blend_signals(ab_inputs)
        self.assertEqual(blend_result.signal, "HOLD")

        # RL: BUY (독립 결정)
        rl_signal = "BUY"

        # 블렌딩 결과(HOLD)와 RL 결정(BUY)이 서로 다름 → 정상 동작
        # RL은 자기 Q-table 기반으로 스스로 결정하므로 블렌딩과 무관
        self.assertNotEqual(blend_result.signal, rl_signal)


if __name__ == "__main__":
    unittest.main()



# ────────────────────────── RL 독립 실행 테스트 ──────────────────────────

class TestRLIndependentExecution(unittest.TestCase):
    """RL이 N-way 블렌딩에서 분리되어 독립적으로 실행되는지 검증한다."""

    def _make_signal(self, ticker, signal, confidence, strategy="A"):
        return PredictionSignal(
            agent_id="test", llm_model="test", strategy=strategy,
            ticker=ticker, signal=signal, confidence=confidence,
            target_price=None, stop_loss=None, reasoning_summary="test",
            trading_date=date.today(),
        )

    def test_rl_separated_from_blend_inputs(self):
        """A, B, RL 3개 전략 결과에서 RL을 분리하면 A/B만 블렌딩에 참여한다."""
        all_predictions = {
            "A": [self._make_signal("005930", "BUY", 0.8, "A")],
            "B": [self._make_signal("005930", "BUY", 0.7, "B")],
            "RL": [self._make_signal("005930", "SELL", 0.9, "RL")],
        }
        rl_predictions = all_predictions.pop("RL", [])
        non_rl = all_predictions

        self.assertEqual(len(rl_predictions), 1)
        self.assertNotIn("RL", non_rl)
        self.assertIn("A", non_rl)
        self.assertIn("B", non_rl)

    def test_rl_independent_signal_preserved(self):
        """RL의 독립 시그널이 블렌딩에 의해 변형되지 않는다."""
        rl_pred = self._make_signal("005930", "SELL", 0.9, "RL")
        all_predictions = {
            "A": [self._make_signal("005930", "BUY", 0.8, "A")],
            "B": [self._make_signal("005930", "BUY", 0.7, "B")],
            "RL": [rl_pred],
        }
        rl_predictions = all_predictions.pop("RL", [])

        self.assertEqual(rl_predictions[0].signal, "SELL")
        self.assertEqual(rl_predictions[0].confidence, 0.9)
        self.assertIs(rl_predictions[0], rl_pred)

    def test_rl_only_mode_no_blending(self):
        """RL만 단독 실행 시 블렌딩 없이 직접 전달된다."""
        all_predictions = {
            "RL": [self._make_signal("005930", "BUY", 0.85, "RL")],
        }
        rl_predictions = all_predictions.pop("RL", [])
        non_rl = all_predictions

        self.assertEqual(len(non_rl), 0)
        self.assertEqual(len(rl_predictions), 1)
        self.assertEqual(rl_predictions[0].signal, "BUY")

    def test_ab_blend_rl_independent_different_decisions(self):
        """A/B 블렌딩 결과와 RL 독립 결정이 서로 다를 수 있다."""
        all_predictions = {
            "A": [self._make_signal("005930", "BUY", 0.8, "A")],
            "B": [self._make_signal("005930", "BUY", 0.75, "B")],
            "RL": [self._make_signal("005930", "SELL", 0.9, "RL")],
        }
        rl_predictions = all_predictions.pop("RL", [])
        non_rl = all_predictions

        # A/B are both BUY, RL is SELL - they should be independent
        self.assertEqual(non_rl["A"][0].signal, "BUY")
        self.assertEqual(non_rl["B"][0].signal, "BUY")
        self.assertEqual(rl_predictions[0].signal, "SELL")
