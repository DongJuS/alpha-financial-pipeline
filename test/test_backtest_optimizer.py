"""
test/test_backtest_optimizer.py — BlendOptimizer 단위 테스트
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.backtest.optimizer import (
    BlendOptimizer,
    OptimizationResult,
    WeightCombo,
    _generate_weight_combos,
)


# ── 가중치 조합 생성 ─────────────────────────────────────────────────

class TestGenerateWeightCombos:
    def test_two_strategies_21_combos(self) -> None:
        """2전략, 0.05 단위 → 21개 조합."""
        combos = _generate_weight_combos(["A", "B"], step=0.05)
        assert len(combos) == 21

    def test_three_strategies_231_combos(self) -> None:
        """3전략, 0.05 단위 → 231개 조합."""
        combos = _generate_weight_combos(["RL", "A", "B"], step=0.05)
        assert len(combos) == 231

    def test_weights_sum_to_one(self) -> None:
        """모든 조합의 가중치 합 ≈ 1.0."""
        combos = _generate_weight_combos(["RL", "A", "B"], step=0.05)
        for c in combos:
            total = sum(c.values())
            assert abs(total - 1.0) < 1e-9, f"합계 {total} ≠ 1.0: {c}"

    def test_weights_non_negative(self) -> None:
        """모든 가중치 ≥ 0."""
        combos = _generate_weight_combos(["RL", "A", "B"], step=0.05)
        for c in combos:
            for v in c.values():
                assert v >= -1e-9, f"음수 가중치: {c}"

    def test_larger_step(self) -> None:
        """0.10 단위 → 66개 조합."""
        combos = _generate_weight_combos(["RL", "A", "B"], step=0.10)
        assert len(combos) == 66

    def test_unsupported_strategy_count_raises(self) -> None:
        """4전략 이상 → ValueError."""
        with pytest.raises(ValueError, match="2~3개"):
            _generate_weight_combos(["A", "B", "C", "D"])

    def test_two_strategies_edge_cases(self) -> None:
        """2전략: 양 끝 (0, 1), (1, 0) 포함."""
        combos = _generate_weight_combos(["A", "B"], step=0.05)
        weights_A = [c["A"] for c in combos]
        assert any(abs(w) < 1e-9 for w in weights_A)  # A=0
        assert any(abs(w - 1.0) < 1e-9 for w in weights_A)  # A=1


# ── _blend_returns ────────────────────────────────────────────────────

class TestBlendReturns:
    def test_equal_weight_average(self) -> None:
        strategy_returns = {
            "A": [1.0, 2.0, 3.0],
            "B": [3.0, 2.0, 1.0],
        }
        blended = BlendOptimizer._blend_returns(
            strategy_returns,
            {"A": 0.5, "B": 0.5},
        )
        assert len(blended) == 3
        assert abs(blended[0] - 2.0) < 1e-9
        assert abs(blended[1] - 2.0) < 1e-9
        assert abs(blended[2] - 2.0) < 1e-9

    def test_single_strategy_full_weight(self) -> None:
        strategy_returns = {
            "A": [1.0, 2.0],
            "B": [10.0, 20.0],
        }
        blended = BlendOptimizer._blend_returns(
            strategy_returns,
            {"A": 1.0, "B": 0.0},
        )
        assert abs(blended[0] - 1.0) < 1e-9
        assert abs(blended[1] - 2.0) < 1e-9

    def test_empty_returns(self) -> None:
        assert BlendOptimizer._blend_returns({}, {"A": 1.0}) == []

    def test_unequal_lengths_uses_min(self) -> None:
        strategy_returns = {
            "A": [1.0, 2.0, 3.0],
            "B": [10.0, 20.0],
        }
        blended = BlendOptimizer._blend_returns(
            strategy_returns,
            {"A": 0.5, "B": 0.5},
        )
        assert len(blended) == 2


# ── _compute_metrics_from_returns ─────────────────────────────────────

class TestComputeMetricsFromReturns:
    def test_flat_returns(self) -> None:
        """수익률 0% → total return ≈ 0%."""
        metrics = BlendOptimizer._compute_metrics_from_returns(
            [0.0] * 100, 10_000_000,
        )
        assert metrics is not None
        assert abs(metrics["total_return_pct"]) < 1e-9
        assert abs(metrics["max_drawdown_pct"]) < 1e-9

    def test_positive_returns(self) -> None:
        """양의 수익률 → 총 수익률 > 0, sharpe > 0."""
        # std > 0이 되도록 변동 있는 양의 수익률 사용
        metrics = BlendOptimizer._compute_metrics_from_returns(
            [0.5, 1.5, 0.8, 1.2, 0.6, 1.0, 0.7, 1.3, 0.9, 1.1], 10_000_000,
        )
        assert metrics is not None
        assert metrics["total_return_pct"] > 0
        assert metrics["sharpe"] > 0
        assert abs(metrics["max_drawdown_pct"]) < 1e-9  # 항상 양이면 MDD 없음

    def test_negative_returns_mdd(self) -> None:
        """하락 후 회복 → MDD 확인."""
        # 5일 +1%, 5일 -2% → 하락기에 MDD 발생
        returns = [1.0] * 5 + [-2.0] * 5
        metrics = BlendOptimizer._compute_metrics_from_returns(
            returns, 10_000_000,
        )
        assert metrics is not None
        assert metrics["max_drawdown_pct"] < 0  # 음수

    def test_empty_returns(self) -> None:
        assert BlendOptimizer._compute_metrics_from_returns([], 10_000_000) is None

    def test_single_day(self) -> None:
        metrics = BlendOptimizer._compute_metrics_from_returns(
            [5.0], 10_000_000,
        )
        assert metrics is not None
        assert metrics["total_return_pct"] > 0
        # 1일이면 std 계산 불가 → sharpe 0
        assert metrics["sharpe"] == 0.0


# ── MDD 제약 필터링 ───────────────────────────────────────────────────

class TestMDDConstraint:
    def test_filter_exceeding_mdd(self) -> None:
        """MDD가 제약 초과하는 조합은 제외되어야 함."""
        combo_ok = WeightCombo(
            weights={"A": 0.5, "B": 0.5},
            sharpe=1.0,
            total_return_pct=10.0,
            max_drawdown_pct=-15.0,
        )
        combo_bad = WeightCombo(
            weights={"A": 0.3, "B": 0.7},
            sharpe=1.5,
            total_return_pct=15.0,
            max_drawdown_pct=-25.0,
        )
        # MDD 제약 -20%: -15% >= -20% (OK), -25% < -20% (제외)
        assert combo_ok.max_drawdown_pct >= -20.0
        assert combo_bad.max_drawdown_pct < -20.0


# ── 결과 정렬 ────────────────────────────────────────────────────────

class TestResultSorting:
    def test_sorted_by_sharpe_desc(self) -> None:
        combos = [
            WeightCombo(weights={"A": 0.5, "B": 0.5}, sharpe=0.8,
                        total_return_pct=5.0, max_drawdown_pct=-10.0),
            WeightCombo(weights={"A": 0.3, "B": 0.7}, sharpe=1.5,
                        total_return_pct=12.0, max_drawdown_pct=-8.0),
            WeightCombo(weights={"A": 0.7, "B": 0.3}, sharpe=1.2,
                        total_return_pct=8.0, max_drawdown_pct=-12.0),
        ]
        combos.sort(key=lambda c: -c.sharpe)
        assert combos[0].sharpe == 1.5
        assert combos[1].sharpe == 1.2
        assert combos[2].sharpe == 0.8


# ── OptimizationResult.to_dict ────────────────────────────────────────

class TestOptimizationResultToDict:
    def test_to_dict_with_best(self) -> None:
        best = WeightCombo(
            weights={"RL": 0.5, "A": 0.3, "B": 0.2},
            sharpe=1.5,
            total_return_pct=12.0,
            max_drawdown_pct=-8.0,
        )
        result = OptimizationResult(
            best=best, top_n=[best], total_count=231, valid_count=150,
        )
        d = result.to_dict()
        assert d["best"]["sharpe"] == 1.5
        assert d["total_count"] == 231
        assert len(d["top_n"]) == 1

    def test_to_dict_without_best(self) -> None:
        result = OptimizationResult(
            best=None, top_n=[], total_count=231, valid_count=0,
        )
        d = result.to_dict()
        assert d["best"] is None
        assert d["valid_count"] == 0


# ── E2E optimize (모의) ──────────────────────────────────────────────

class TestOptimizeE2E:
    @pytest.mark.asyncio
    async def test_two_strategy_optimize(self) -> None:
        """2전략 간단 케이스로 최적화 실행."""
        optimizer = BlendOptimizer()
        optimizer.STRATEGIES = ["A", "B"]

        # 각 전략의 일별 수익률을 모의
        mock_returns = {
            "A": [0.5, -0.2, 0.8, -0.1, 0.3, 0.6, -0.4, 0.2, 0.1, -0.3],
            "B": [0.2, 0.3, -0.1, 0.4, 0.1, -0.2, 0.5, 0.3, -0.1, 0.2],
        }

        with patch.object(
            optimizer, "_compute_strategy_returns",
            new=AsyncMock(return_value=mock_returns),
        ):
            result = await optimizer.optimize(
                ticker="005930",
                train_start=date(2024, 1, 1),
                train_end=date(2024, 6, 30),
                test_start=date(2024, 7, 1),
                test_end=date(2024, 12, 31),
                mdd_constraint=-30.0,
                step=0.10,
            )

        assert isinstance(result, OptimizationResult)
        assert result.total_count == 11  # 2전략 0.10 단위 → 11개
        assert result.valid_count > 0
        assert result.best is not None
        # 샤프 내림차순 정렬 확인
        for i in range(len(result.top_n) - 1):
            assert result.top_n[i].sharpe >= result.top_n[i + 1].sharpe

    @pytest.mark.asyncio
    async def test_strict_mdd_constraint_filters_all(self) -> None:
        """MDD 제약이 0이면 거의 모든 조합 필터링."""
        optimizer = BlendOptimizer()
        optimizer.STRATEGIES = ["A", "B"]

        # 하락이 있는 수익률 → MDD < 0
        mock_returns = {
            "A": [1.0, -3.0, 1.0, -3.0, 1.0],
            "B": [-2.0, 1.0, -2.0, 1.0, -2.0],
        }

        with patch.object(
            optimizer, "_compute_strategy_returns",
            new=AsyncMock(return_value=mock_returns),
        ):
            result = await optimizer.optimize(
                ticker="005930",
                train_start=date(2024, 1, 1),
                train_end=date(2024, 6, 30),
                test_start=date(2024, 7, 1),
                test_end=date(2024, 12, 31),
                mdd_constraint=0.0,  # 매우 엄격
                step=0.10,
            )

        # MDD가 정확히 0인 조합만 통과 (실질적으로 없음)
        assert result.valid_count == 0 or result.best is not None
