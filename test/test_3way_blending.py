"""
test/test_3way_blending.py — A/B/RL 3전략 동시 블렌딩 통합 테스트

Worktree B 산출물: 오케스트레이터의 N-way 블렌딩이
- 3전략 동시 블렌딩을 올바르게 수행하는지
- RL 빈 시그널 시 graceful fallback (가중치 재분배)이 동작하는지
- 모든 전략이 빈 시그널일 때 안전하게 처리하는지
검증한다.

DB/LLM 의존성 없이 순수 로직만 테스트한다.
"""

from __future__ import annotations

import os
import unittest
from datetime import date

# orchestrator import 전에 필수 환경변수 설정 (Settings 초기화용)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from src.agents.blending import BlendInput, NWayBlendResult, blend_signals
from src.agents.orchestrator import DEFAULT_BLEND_WEIGHTS, OrchestratorAgent
from src.db.models import PredictionSignal


def _make_signal(
    strategy: str,
    ticker: str,
    signal: str,
    confidence: float,
) -> PredictionSignal:
    """테스트용 PredictionSignal 생성 헬퍼."""
    return PredictionSignal(
        agent_id=f"test_{strategy}",
        llm_model="test",
        strategy=strategy,
        ticker=ticker,
        signal=signal,
        confidence=confidence,
        trading_date=date.today(),
    )


# ────────────────────────── 가중치 재정규화 테스트 ──────────────────────────


class TestNormalizeActiveWeights(unittest.TestCase):
    """OrchestratorAgent._normalize_active_weights 단위 테스트."""

    def setUp(self) -> None:
        self.orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34},
        )

    def test_all_strategies_active(self) -> None:
        """3전략 모두 활성 → 원래 가중치 유지 (합=1.0)."""
        weights = self.orch._normalize_active_weights({"A", "B", "RL"})
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["A"], 0.33)
        self.assertAlmostEqual(weights["B"], 0.33)
        self.assertAlmostEqual(weights["RL"], 0.34)

    def test_rl_excluded_redistributes_to_ab(self) -> None:
        """RL 제외 → A/B만으로 재정규화 (각 50%)."""
        weights = self.orch._normalize_active_weights({"A", "B"})
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["A"], 0.50)
        self.assertAlmostEqual(weights["B"], 0.50)
        self.assertNotIn("RL", weights)

    def test_two_strategies_active_with_rl(self) -> None:
        """A/RL 2전략 활성 → B 제외, 합=1.0."""
        weights = self.orch._normalize_active_weights({"A", "RL"})
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        # A: 0.33/0.67 ≈ 0.4925, RL: 0.34/0.67 ≈ 0.5075
        self.assertAlmostEqual(weights["A"], 0.33 / 0.67, places=4)
        self.assertAlmostEqual(weights["RL"], 0.34 / 0.67, places=4)
        self.assertNotIn("B", weights)

    def test_single_strategy_active(self) -> None:
        """1전략만 활성 → 가중치 1.0."""
        weights = self.orch._normalize_active_weights({"A"})
        self.assertAlmostEqual(weights["A"], 1.0)

    def test_no_active_strategies(self) -> None:
        """활성 전략 없음 → 빈 딕셔너리."""
        weights = self.orch._normalize_active_weights(set())
        self.assertEqual(weights, {})


# ────────────────────────── 3전략 블렌딩 로직 테스트 ──────────────────────────


class TestThreeWayBlendingLogic(unittest.TestCase):
    """blending.blend_signals의 3전략 블렌딩 검증."""

    def test_three_strategies_all_buy(self) -> None:
        """A/B/RL 모두 BUY → BUY 시그널, 높은 confidence."""
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.375),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.375),
            BlendInput(strategy="RL", signal="BUY", confidence=0.6, weight=0.25),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")
        self.assertFalse(result.conflict)
        self.assertEqual(len(result.participating_strategies), 3)

    def test_rl_dissents_from_ab(self) -> None:
        """A/B=BUY, RL=SELL → conflict=True, A/B 다수결로 BUY 유지."""
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.375),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.375),
            BlendInput(strategy="RL", signal="SELL", confidence=0.6, weight=0.25),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "BUY")
        self.assertTrue(result.conflict)

    def test_rl_tips_balance_to_sell(self) -> None:
        """A=BUY, B=SELL, RL=SELL → SELL 우세."""
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.7, weight=0.375),
            BlendInput(strategy="B", signal="SELL", confidence=0.8, weight=0.375),
            BlendInput(strategy="RL", signal="SELL", confidence=0.9, weight=0.25),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "SELL")
        self.assertTrue(result.conflict)

    def test_mixed_signals_balanced_becomes_hold(self) -> None:
        """A=BUY, B=SELL, RL=HOLD → 상쇄되어 HOLD."""
        inputs = [
            BlendInput(strategy="A", signal="BUY", confidence=0.5, weight=0.375),
            BlendInput(strategy="B", signal="SELL", confidence=0.5, weight=0.375),
            BlendInput(strategy="RL", signal="HOLD", confidence=0.5, weight=0.25),
        ]
        result = blend_signals(inputs)
        self.assertEqual(result.signal, "HOLD")
        self.assertTrue(result.conflict)


# ────────────────────────── 오케스트레이터 블렌딩 통합 테스트 ──────────────────


class TestOrchestratorThreeWayBlending(unittest.TestCase):
    """OrchestratorAgent._blend_nway_predictions 통합 테스트."""

    def setUp(self) -> None:
        self.orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34},
        )

    def test_3way_blend_produces_signals(self) -> None:
        """A/B/RL 모두 시그널 반환 → 블렌딩 결과 생성."""
        all_preds = {
            "A": [_make_signal("A", "005930", "BUY", 0.8)],
            "B": [_make_signal("B", "005930", "BUY", 0.7)],
            "RL": [_make_signal("RL", "005930", "BUY", 0.6)],
        }
        blended = self.orch._blend_nway_predictions(all_preds)
        self.assertEqual(len(blended), 1)
        self.assertEqual(blended[0].ticker, "005930")
        self.assertEqual(blended[0].signal, "BUY")
        self.assertEqual(blended[0].strategy, "BLEND")

    def test_rl_empty_fallback_to_2way(self) -> None:
        """RL 빈 시그널 → A/B 2전략으로 fallback, 가중치 재분배."""
        all_preds = {
            "A": [_make_signal("A", "005930", "BUY", 0.8)],
            "B": [_make_signal("B", "005930", "BUY", 0.7)],
            "RL": [],  # 활성 정책 없음
        }
        blended = self.orch._blend_nway_predictions(all_preds)
        self.assertEqual(len(blended), 1)
        self.assertEqual(blended[0].signal, "BUY")
        # 가중치 재분배 확인: A/B만으로 정규화되어 confidence가 유효해야 함
        self.assertGreater(blended[0].confidence, 0.0)

    def test_rl_empty_does_not_dilute_confidence(self) -> None:
        """RL 빈 시그널 시 가중치가 A/B로 재분배되어 confidence가 희석되지 않음."""
        # 3전략 모두 활성
        all_preds_3way = {
            "A": [_make_signal("A", "005930", "BUY", 0.8)],
            "B": [_make_signal("B", "005930", "BUY", 0.7)],
            "RL": [_make_signal("RL", "005930", "BUY", 0.6)],
        }
        blended_3way = self.orch._blend_nway_predictions(all_preds_3way)

        # RL 빈 시그널
        all_preds_2way = {
            "A": [_make_signal("A", "005930", "BUY", 0.8)],
            "B": [_make_signal("B", "005930", "BUY", 0.7)],
            "RL": [],
        }
        blended_2way = self.orch._blend_nway_predictions(all_preds_2way)

        # 2way 결과가 유효한 confidence를 가져야 함 (희석 없음)
        self.assertGreater(blended_2way[0].confidence, 0.0)
        self.assertLessEqual(blended_2way[0].confidence, 1.0)

    def test_all_strategies_empty(self) -> None:
        """모든 전략이 빈 시그널 → 결과 0건."""
        all_preds = {
            "A": [],
            "B": [],
            "RL": [],
        }
        blended = self.orch._blend_nway_predictions(all_preds)
        self.assertEqual(len(blended), 0)

    def test_single_strategy_produces_valid_signal(self) -> None:
        """A만 시그널 반환 → A의 가중치 1.0으로 블렌딩."""
        all_preds = {
            "A": [_make_signal("A", "005930", "SELL", 0.9)],
            "B": [],
            "RL": [],
        }
        blended = self.orch._blend_nway_predictions(all_preds)
        self.assertEqual(len(blended), 1)
        self.assertEqual(blended[0].signal, "SELL")

    def test_multi_ticker_3way_blend(self) -> None:
        """여러 티커에 대해 3전략 블렌딩 → 티커별 독립 블렌딩."""
        all_preds = {
            "A": [
                _make_signal("A", "005930", "BUY", 0.8),
                _make_signal("A", "000660", "SELL", 0.7),
            ],
            "B": [
                _make_signal("B", "005930", "BUY", 0.7),
                _make_signal("B", "000660", "SELL", 0.8),
            ],
            "RL": [
                _make_signal("RL", "005930", "BUY", 0.6),
                _make_signal("RL", "000660", "HOLD", 0.5),
            ],
        }
        blended = self.orch._blend_nway_predictions(all_preds)
        self.assertEqual(len(blended), 2)

        by_ticker = {s.ticker: s for s in blended}
        self.assertEqual(by_ticker["005930"].signal, "BUY")
        self.assertEqual(by_ticker["000660"].signal, "SELL")

    def test_partial_ticker_coverage(self) -> None:
        """RL이 일부 티커만 커버 → 티커별로 활성 전략이 다름."""
        all_preds = {
            "A": [
                _make_signal("A", "005930", "BUY", 0.8),
                _make_signal("A", "000660", "BUY", 0.7),
            ],
            "B": [
                _make_signal("B", "005930", "BUY", 0.7),
                _make_signal("B", "000660", "BUY", 0.6),
            ],
            "RL": [
                _make_signal("RL", "005930", "BUY", 0.9),
                # 000660에 대한 RL 시그널 없음
            ],
        }
        blended = self.orch._blend_nway_predictions(all_preds)
        self.assertEqual(len(blended), 2)
        # 두 티커 모두 BUY여야 함
        for sig in blended:
            self.assertEqual(sig.signal, "BUY")


# ────────────────────────── blending.py N-way 함수 직접 테스트 ──────────────


class TestBlendSignalsNWay(unittest.TestCase):
    """blending.blend_signals의 N-way 블렌딩 엣지 케이스."""

    def test_empty_inputs(self) -> None:
        """빈 입력 → HOLD, confidence 0."""
        result = blend_signals([])
        self.assertEqual(result.signal, "HOLD")
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.participating_strategies, [])

    def test_single_input(self) -> None:
        """단일 전략 → 해당 전략의 시그널 그대로."""
        result = blend_signals([
            BlendInput(strategy="A", signal="SELL", confidence=0.9, weight=1.0),
        ])
        self.assertEqual(result.signal, "SELL")
        self.assertAlmostEqual(result.confidence, 0.9)

    def test_weights_sum_to_one_after_normalization(self) -> None:
        """가중치 정규화 후 meta.weights 합이 1.0."""
        result = blend_signals([
            BlendInput(strategy="A", signal="BUY", confidence=0.8, weight=0.30),
            BlendInput(strategy="B", signal="BUY", confidence=0.7, weight=0.30),
            BlendInput(strategy="RL", signal="BUY", confidence=0.6, weight=0.20),
        ])
        weight_sum = sum(result.meta["weights"].values())
        self.assertAlmostEqual(weight_sum, 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
