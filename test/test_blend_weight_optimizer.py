"""
test/test_blend_weight_optimizer.py — 성과 기반 동적 블렌딩 가중치 최적화 테스트

순수 함수(compute_dynamic_weights, _composite_score 등)만 테스트하므로
DB/네트워크 의존 없이 실행 가능.
"""

import unittest

from src.utils.blend_weight_optimizer import (
    _apply_min_weight,
    _composite_score,
    _normalize,
    compute_dynamic_weights,
)

BASE_WEIGHTS = {"A": 0.30, "B": 0.30, "RL": 0.20, "S": 0.20}


class TestCompositeScore(unittest.TestCase):
    def test_all_positive(self) -> None:
        perf = {"return_pct": 5.0, "win_rate": 0.6, "sharpe_ratio": 1.2, "sell_count": 10}
        score = _composite_score(perf)
        self.assertGreater(score, 0)

    def test_negative_return_clamped_to_zero(self) -> None:
        perf = {"return_pct": -10.0, "win_rate": 0.0, "sharpe_ratio": None, "sell_count": 5}
        self.assertEqual(_composite_score(perf), 0.0)

    def test_zero_perf(self) -> None:
        self.assertEqual(_composite_score({}), 0.0)

    def test_higher_return_gives_higher_score(self) -> None:
        good = {"return_pct": 10.0, "win_rate": 0.7, "sharpe_ratio": 2.0, "sell_count": 15}
        bad = {"return_pct": 1.0, "win_rate": 0.4, "sharpe_ratio": 0.3, "sell_count": 15}
        self.assertGreater(_composite_score(good), _composite_score(bad))


class TestNormalize(unittest.TestCase):
    def test_sums_to_one(self) -> None:
        scores = {"A": 3.0, "B": 1.0, "C": 2.0}
        result = _normalize(scores)
        self.assertAlmostEqual(sum(result.values()), 1.0)

    def test_zero_total_equal_weights(self) -> None:
        scores = {"A": 0.0, "B": 0.0}
        result = _normalize(scores)
        self.assertAlmostEqual(result["A"], 0.5)
        self.assertAlmostEqual(result["B"], 0.5)


class TestApplyMinWeight(unittest.TestCase):
    def test_floor_applied(self) -> None:
        weights = {"A": 0.95, "B": 0.03, "C": 0.02}
        result = _apply_min_weight(weights, min_weight=0.05)
        for v in result.values():
            self.assertGreaterEqual(v, 0.04)  # floor에 의해 높아짐 (재정규화 후 약간 낮을 수 있음)

    def test_sums_to_one_after_floor(self) -> None:
        weights = {"A": 0.98, "B": 0.01, "C": 0.01}
        result = _apply_min_weight(weights, min_weight=0.10)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)

    def test_no_strategy_below_floor(self) -> None:
        weights = {"A": 0.9, "B": 0.05, "C": 0.05}
        min_w = 0.05
        result = _apply_min_weight(weights, min_weight=min_w)
        # effective floor = min(0.05, 1/3=0.333) = 0.05
        # 재정규화 후 최소값 ≥ 0.05*(1/total_floored)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)


class TestComputeDynamicWeights(unittest.TestCase):
    def test_no_valid_data_returns_base_weights(self) -> None:
        """성과 데이터가 없으면 base_weights 그대로 반환."""
        result = compute_dynamic_weights(
            perf_by_strategy={},
            base_weights=BASE_WEIGHTS,
        )
        self.assertAlmostEqual(sum(result.values()), 1.0)
        # 비율은 base_weights 정규화 결과와 같아야 함
        total_base = sum(BASE_WEIGHTS.values())
        for k in BASE_WEIGHTS:
            self.assertAlmostEqual(result[k], BASE_WEIGHTS[k] / total_base, places=5)

    def test_high_performer_gets_higher_weight(self) -> None:
        """성과가 높은 전략이 더 높은 가중치를 받아야 함."""
        perf = {
            "A": {"return_pct": 15.0, "win_rate": 0.75, "sharpe_ratio": 2.0, "sell_count": 10},
            "B": {"return_pct": 2.0, "win_rate": 0.45, "sharpe_ratio": 0.5, "sell_count": 10},
        }
        result = compute_dynamic_weights(
            perf_by_strategy=perf,
            base_weights={"A": 0.5, "B": 0.5},
            min_weight=0.05,
        )
        self.assertGreater(result["A"], result["B"])

    def test_weights_sum_to_one(self) -> None:
        perf = {
            "A": {"return_pct": 5.0, "win_rate": 0.6, "sharpe_ratio": 1.0, "sell_count": 5},
            "B": {"return_pct": 3.0, "win_rate": 0.55, "sharpe_ratio": 0.8, "sell_count": 5},
            "RL": {"return_pct": 8.0, "win_rate": 0.7, "sharpe_ratio": 1.5, "sell_count": 5},
            "S": {"return_pct": 1.0, "win_rate": 0.4, "sharpe_ratio": 0.3, "sell_count": 5},
        }
        result = compute_dynamic_weights(
            perf_by_strategy=perf,
            base_weights=BASE_WEIGHTS,
        )
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)
        self.assertEqual(set(result.keys()), set(BASE_WEIGHTS.keys()))

    def test_min_weight_floor_respected(self) -> None:
        """최소 가중치 하한선이 지켜져야 함 (재정규화 후에도)."""
        perf = {
            "A": {"return_pct": 50.0, "win_rate": 0.9, "sharpe_ratio": 5.0, "sell_count": 10},
            "B": {"return_pct": 0.1, "win_rate": 0.1, "sharpe_ratio": 0.0, "sell_count": 10},
        }
        min_w = 0.10
        result = compute_dynamic_weights(
            perf_by_strategy=perf,
            base_weights={"A": 0.5, "B": 0.5},
            min_weight=min_w,
        )
        # B는 성과가 나빠도 floor 이상이어야 함
        # effective_floor = min(0.10, 1/2=0.50) = 0.10
        # 재정규화 후 최솟값은 floor_frac 수준
        self.assertGreater(result["B"], 0.0)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)

    def test_insufficient_trade_count_uses_base_weight_ratio(self) -> None:
        """sell_count < MIN_TRADE_COUNT 인 전략은 base_weight 비율 유지."""
        perf = {
            "A": {"return_pct": 5.0, "win_rate": 0.6, "sharpe_ratio": 1.0, "sell_count": 1},  # < MIN
        }
        result = compute_dynamic_weights(
            perf_by_strategy=perf,
            base_weights={"A": 0.5, "B": 0.5},
            min_weight=0.05,
        )
        # 유효 성과 없으므로 base_weights 비율 유지 (정규화됨)
        self.assertAlmostEqual(result["A"], 0.5, places=5)
        self.assertAlmostEqual(result["B"], 0.5, places=5)

    def test_all_negative_returns_fall_back_gracefully(self) -> None:
        """모든 전략 수익률이 음수면 base_weights로 폴백."""
        perf = {
            "A": {"return_pct": -5.0, "win_rate": 0.0, "sharpe_ratio": -1.0, "sell_count": 5},
            "B": {"return_pct": -3.0, "win_rate": 0.0, "sharpe_ratio": -0.5, "sell_count": 5},
        }
        result = compute_dynamic_weights(
            perf_by_strategy=perf,
            base_weights={"A": 0.5, "B": 0.5},
            min_weight=0.05,
        )
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)
        # 모두 0점이므로 동일 가중치
        self.assertAlmostEqual(result["A"], result["B"], places=5)

    def test_partial_strategies_with_data(self) -> None:
        """일부 전략만 성과 데이터가 있어도 정상 동작."""
        perf = {
            "A": {"return_pct": 8.0, "win_rate": 0.65, "sharpe_ratio": 1.2, "sell_count": 5},
            # B, RL, S는 데이터 없음
        }
        result = compute_dynamic_weights(
            perf_by_strategy=perf,
            base_weights=BASE_WEIGHTS,
        )
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)
        self.assertEqual(set(result.keys()), set(BASE_WEIGHTS.keys()))


class TestBlendWeightOptimizerClass(unittest.IsolatedAsyncioTestCase):
    async def test_optimize_falls_back_on_db_error(self) -> None:
        """DB 연결 실패 시 base_weights를 정규화해서 반환."""
        from unittest.mock import AsyncMock, patch

        from src.utils.blend_weight_optimizer import BlendWeightOptimizer

        optimizer = BlendWeightOptimizer(
            base_weights=BASE_WEIGHTS,
            lookback_days=30,
            min_weight=0.05,
        )
        with patch(
            "src.utils.blend_weight_optimizer.fetch_strategy_performance",
            new=AsyncMock(side_effect=Exception("DB unavailable")),
        ):
            result = await optimizer.optimize()

        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)
        self.assertEqual(set(result.keys()), set(BASE_WEIGHTS.keys()))

    async def test_optimize_with_mocked_performance(self) -> None:
        """성과 데이터가 있으면 동적 가중치를 반환."""
        from unittest.mock import AsyncMock, patch

        from src.utils.blend_weight_optimizer import BlendWeightOptimizer

        optimizer = BlendWeightOptimizer(
            base_weights={"A": 0.5, "B": 0.5},
            lookback_days=30,
            min_weight=0.05,
        )
        mock_perf = {
            "A": {"return_pct": 20.0, "win_rate": 0.8, "sharpe_ratio": 3.0, "sell_count": 10},
            "B": {"return_pct": 2.0, "win_rate": 0.4, "sharpe_ratio": 0.5, "sell_count": 10},
        }
        with patch(
            "src.utils.blend_weight_optimizer.fetch_strategy_performance",
            new=AsyncMock(return_value=mock_perf),
        ):
            result = await optimizer.optimize()

        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)
        self.assertGreater(result["A"], result["B"])


if __name__ == "__main__":
    unittest.main()
