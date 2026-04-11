"""
test/test_rl_walk_forward.py — Walk-Forward 평가 테스트

WalkForwardEvaluator의 fold 분할, 학습/평가 파이프라인, 요약 통계를 검증합니다.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.agents.rl_trading import RLDataset, RLEvaluationMetrics
from src.agents.rl_walk_forward import (
    WalkForwardEvaluator,
    WalkForwardResult,
    FoldResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _uptrend_closes(length: int = 200) -> list[float]:
    return [100.0 + i * 0.5 for i in range(length)]


def _flat_closes(length: int = 200) -> list[float]:
    return [100.0] * length


def _make_good_metrics(return_pct: float = 5.0) -> RLEvaluationMetrics:
    return RLEvaluationMetrics(
        total_return_pct=return_pct,
        baseline_return_pct=2.0,
        excess_return_pct=return_pct - 2.0,
        max_drawdown_pct=-10.0,
        trades=20,
        win_rate=0.6,
        holdout_steps=40,
        approved=return_pct >= 5.0,
    )


def _make_bad_metrics() -> RLEvaluationMetrics:
    return RLEvaluationMetrics(
        total_return_pct=-5.0,
        baseline_return_pct=2.0,
        excess_return_pct=-7.0,
        max_drawdown_pct=-30.0,
        trades=20,
        win_rate=0.3,
        holdout_steps=40,
        approved=False,
    )


class FakeTrainer:
    """TrainerProtocol 구현 fake."""

    def __init__(
        self,
        metrics: RLEvaluationMetrics | None = None,
        train_result: dict | None = None,
        raise_on_train: bool = False,
        raise_on_evaluate: bool = False,
    ):
        self._metrics = metrics or _make_good_metrics()
        self._train_result = train_result or {"state": {"BUY": 0.5}}
        self._raise_on_train = raise_on_train
        self._raise_on_evaluate = raise_on_evaluate

    def train(self, data):
        if self._raise_on_train:
            raise RuntimeError("train failed")
        return self._train_result

    def evaluate(self, arg1, arg2) -> RLEvaluationMetrics:
        if self._raise_on_evaluate:
            raise RuntimeError("evaluate failed")
        return self._metrics


class DatasetPreferringTrainer(FakeTrainer):
    """train()의 첫 번째 파라미터 이름이 dataset인 트레이너."""

    def train(self, dataset):
        if self._raise_on_train:
            raise RuntimeError("train failed")
        return self._train_result


class QTablePreferringTrainer(FakeTrainer):
    """evaluate()의 첫 번째 파라미터 이름이 q_table인 트레이너."""

    def evaluate(self, q_table, closes) -> RLEvaluationMetrics:
        if self._raise_on_evaluate:
            raise RuntimeError("evaluate failed")
        return self._metrics


# ── Basic Evaluation Tests ───────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestWalkForwardBasic:
    """WalkForward 기본 평가 테스트."""

    def test_evaluate_returns_result(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        closes = _uptrend_closes(200)
        trainer = FakeTrainer()
        result = evaluator.evaluate(closes, trainer)
        assert isinstance(result, WalkForwardResult)
        assert result.n_folds > 0

    def test_fold_count(self):
        evaluator = WalkForwardEvaluator(n_folds=5)
        closes = _uptrend_closes(300)
        trainer = FakeTrainer()
        result = evaluator.evaluate(closes, trainer)
        assert len(result.folds) <= 5

    def test_overall_approved_with_good_metrics(self):
        evaluator = WalkForwardEvaluator(
            n_folds=3,
            approval_threshold_pct=0.0,
            consistency_threshold=0.5,
        )
        trainer = FakeTrainer(metrics=_make_good_metrics(10.0))
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        assert result.overall_approved is True
        assert result.approved is True  # alias

    def test_overall_rejected_with_bad_metrics(self):
        evaluator = WalkForwardEvaluator(
            n_folds=3,
            approval_threshold_pct=5.0,
            consistency_threshold=0.8,
        )
        trainer = FakeTrainer(metrics=_make_bad_metrics())
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        assert result.overall_approved is False

    def test_result_to_dict(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        d = result.to_dict()
        assert "n_folds" in d
        assert "avg_return_pct" in d
        assert "folds" in d
        assert "approved" in d
        assert "overall_approved" in d


# ── Fold Configuration Tests ─────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestFoldConfiguration:
    """Fold 분할 설정 테스트."""

    def test_expanding_window(self):
        evaluator = WalkForwardEvaluator(n_folds=3, expanding_window=True)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        for fold in result.folds:
            assert fold.train_start_idx == 0  # expanding 이면 항상 0부터

    def test_sliding_window(self):
        evaluator = WalkForwardEvaluator(n_folds=3, expanding_window=False)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        # sliding window에서는 모든 fold의 train_start가 0이 아닐 수 있음
        assert len(result.folds) > 0

    def test_min_train_ratio(self):
        evaluator = WalkForwardEvaluator(n_folds=3, min_train_ratio=0.5)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        for fold in result.folds:
            assert fold.train_size >= 40  # max(n*ratio, 40)


# ── Summary Statistics Tests ─────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestSummaryStatistics:
    """요약 통계 정확성 테스트."""

    def test_avg_return_calculated(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        result = evaluator.evaluate(
            _uptrend_closes(200),
            FakeTrainer(metrics=_make_good_metrics(10.0)),
        )
        assert result.avg_return_pct == pytest.approx(10.0)

    def test_consistency_score_range(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        assert 0 <= result.consistency_score <= 1.0

    def test_approved_folds_count(self):
        evaluator = WalkForwardEvaluator(
            n_folds=3,
            approval_threshold_pct=0.0,
        )
        result = evaluator.evaluate(
            _uptrend_closes(200),
            FakeTrainer(metrics=_make_good_metrics(10.0)),
        )
        assert result.approved_folds == len(result.folds)

    def test_created_at_populated(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        assert result.created_at != ""


# ── Error Handling Tests ─────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestErrorHandling:
    """에러 핸들링 테스트."""

    def test_insufficient_data_raises(self):
        evaluator = WalkForwardEvaluator(n_folds=5)
        with pytest.raises(ValueError, match="데이터 부족"):
            evaluator.evaluate([100.0] * 10, FakeTrainer())

    def test_zero_folds_raises(self):
        evaluator = WalkForwardEvaluator(n_folds=0)
        with pytest.raises(ValueError):
            evaluator.evaluate(_uptrend_closes(200), FakeTrainer())

    def test_train_failure_skips_fold(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        trainer = FakeTrainer(raise_on_train=True)
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        # 모든 fold가 실패하면 빈 결과
        assert len(result.folds) == 0
        assert result.overall_approved is False

    def test_evaluate_failure_skips_fold(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        trainer = FakeTrainer(raise_on_evaluate=True)
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        assert len(result.folds) == 0

    def test_empty_folds_result(self):
        """모든 fold가 실패하면 빈 WalkForwardResult."""
        evaluator = WalkForwardEvaluator(n_folds=3)
        trainer = FakeTrainer(raise_on_train=True)
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        assert result.folds == []
        assert result.avg_return_pct == 0.0
        assert result.consistency_score == 0.0


# ── Trainer Protocol Compatibility Tests ──────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestTrainerCompatibility:
    """다양한 trainer 인��페이스 호환성 테스트."""

    def test_dataset_preferring_trainer(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        trainer = DatasetPreferringTrainer()
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        assert len(result.folds) > 0

    def test_q_table_preferring_evaluator(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        trainer = QTablePreferringTrainer()
        result = evaluator.evaluate(_uptrend_closes(200), trainer)
        assert len(result.folds) > 0

    def test_extract_q_table_from_dict(self):
        result = WalkForwardEvaluator._extract_q_table({"state": {"BUY": 0.5}})
        assert isinstance(result, dict)

    def test_extract_q_table_from_object(self):
        obj = MagicMock()
        obj.q_table = {"state": {"BUY": 0.5}}
        result = WalkForwardEvaluator._extract_q_table(obj)
        assert result == {"state": {"BUY": 0.5}}

    def test_extract_q_table_invalid_raises(self):
        with pytest.raises(TypeError, match="q_table"):
            WalkForwardEvaluator._extract_q_table("invalid")

    def test_build_dataset(self):
        closes = [100.0, 101.0, 102.0]
        ds = WalkForwardEvaluator._build_dataset(closes, fold_idx=0)
        assert isinstance(ds, RLDataset)
        assert ds.ticker == "WALK_FORWARD_FOLD_0"
        assert len(ds.closes) == 3


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestWalkForwardEdgeCases:
    """Walk-Forward 에지 케이스."""

    def test_single_fold(self):
        evaluator = WalkForwardEvaluator(n_folds=1)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        assert len(result.folds) <= 1

    def test_large_number_of_folds(self):
        evaluator = WalkForwardEvaluator(n_folds=20)
        result = evaluator.evaluate(_uptrend_closes(500), FakeTrainer())
        assert len(result.folds) <= 20

    def test_min_max_return(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        result = evaluator.evaluate(
            _uptrend_closes(200),
            FakeTrainer(metrics=_make_good_metrics(10.0)),
        )
        assert result.min_return_pct <= result.max_return_pct
        assert result.min_return_pct <= result.avg_return_pct <= result.max_return_pct

    def test_std_return_non_negative(self):
        evaluator = WalkForwardEvaluator(n_folds=3)
        result = evaluator.evaluate(_uptrend_closes(200), FakeTrainer())
        assert result.std_return_pct >= 0
