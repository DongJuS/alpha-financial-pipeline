"""
src/agents/rl_walk_forward.py — Walk-Forward / Out-of-Sample 평가

시계열 데이터에서 walk-forward validation을 수행하여
RL 정책의 과적합 위험을 정량적으로 평가합니다.

Walk-Forward 방식:
  전체 데이터를 N개 fold로 분할 → 각 fold마다 이전 데이터로 학습, 해당 fold로 평가.
  최종 결과: fold별 수익률 분포 → 평균/표준편차/최소/최대, 일관성 점수.

Usage:
    evaluator = WalkForwardEvaluator(n_folds=5)
    result = evaluator.evaluate(closes, trainer_factory)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from src.agents.rl_trading import RLEvaluationMetrics, RLSplitMetadata
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ── 프로토콜 정의 ─────────────────────────────────────────────────────────


class TrainerProtocol(Protocol):
    """학습기 프로토콜 (TabularQTrainer/V2 호환)."""

    def train(self, closes: list[float]) -> dict[str, dict[str, float]]:
        ...

    def evaluate(
        self, q_table: dict[str, dict[str, float]], closes: list[float]
    ) -> RLEvaluationMetrics:
        ...


# ── 결과 데이터 ───────────────────────────────────────────────────────────


@dataclass
class FoldResult:
    """단일 fold 평가 결과."""

    fold_idx: int
    train_size: int
    test_size: int
    train_start_idx: int
    train_end_idx: int
    test_start_idx: int
    test_end_idx: int
    metrics: RLEvaluationMetrics
    approved: bool


@dataclass
class WalkForwardResult:
    """Walk-Forward 전체 결과."""

    n_folds: int
    total_data_points: int
    folds: list[FoldResult]

    # 요약 통계
    avg_return_pct: float = 0.0
    std_return_pct: float = 0.0
    min_return_pct: float = 0.0
    max_return_pct: float = 0.0
    avg_excess_return_pct: float = 0.0
    avg_max_drawdown_pct: float = 0.0
    avg_win_rate: float = 0.0
    approved_folds: int = 0
    consistency_score: float = 0.0  # 0~1, 일관성 점수
    overall_approved: bool = False

    created_at: str = ""

    def to_dict(self) -> dict:
        result = {
            "n_folds": self.n_folds,
            "total_data_points": self.total_data_points,
            "avg_return_pct": self.avg_return_pct,
            "std_return_pct": self.std_return_pct,
            "min_return_pct": self.min_return_pct,
            "max_return_pct": self.max_return_pct,
            "avg_excess_return_pct": self.avg_excess_return_pct,
            "avg_max_drawdown_pct": self.avg_max_drawdown_pct,
            "avg_win_rate": self.avg_win_rate,
            "approved_folds": self.approved_folds,
            "consistency_score": self.consistency_score,
            "overall_approved": self.overall_approved,
            "created_at": self.created_at,
            "folds": [asdict(f) for f in self.folds],
        }
        return result


# ── Walk-Forward 평가기 ───────────────────────────────────────────────────


class WalkForwardEvaluator:
    """Walk-Forward Validation으로 RL 정책을 평가.

    Args:
        n_folds: fold 수 (기본 5)
        min_train_ratio: 최소 학습 데이터 비율 (기본 0.3)
        expanding_window: True면 expanding window, False면 sliding window
        approval_threshold_pct: fold 승인 기준 수익률 (%)
        consistency_threshold: 전체 승인에 필요한 fold 승인 비율 (0~1)
    """

    def __init__(
        self,
        n_folds: int = 5,
        min_train_ratio: float = 0.3,
        expanding_window: bool = True,
        approval_threshold_pct: float = 0.0,
        consistency_threshold: float = 0.6,
    ) -> None:
        self.n_folds = n_folds
        self.min_train_ratio = min_train_ratio
        self.expanding_window = expanding_window
        self.approval_threshold_pct = approval_threshold_pct
        self.consistency_threshold = consistency_threshold

    def evaluate(
        self,
        closes: list[float],
        trainer: TrainerProtocol,
    ) -> WalkForwardResult:
        """Walk-forward 평가 실행.

        Args:
            closes: 전체 종가 시계열
            trainer: train()/evaluate() 메서드를 가진 학습기
        """
        n = len(closes)
        min_train = max(int(n * self.min_train_ratio), 40)

        # fold 크기 계산 (test 구간)
        available = n - min_train
        if available <= 0 or self.n_folds <= 0:
            raise ValueError(
                f"데이터 부족: total={n}, min_train={min_train}, n_folds={self.n_folds}"
            )

        fold_size = max(1, available // self.n_folds)
        folds: list[FoldResult] = []

        for i in range(self.n_folds):
            test_end = n - (self.n_folds - 1 - i) * fold_size
            test_start = test_end - fold_size

            if test_start < min_train:
                continue

            if self.expanding_window:
                train_start = 0
            else:
                train_start = max(0, test_start - min_train)

            train_end = test_start

            train_closes = closes[train_start:train_end]
            test_closes = closes[test_start:test_end]

            if len(train_closes) < 40 or len(test_closes) < 5:
                continue

            try:
                # 학습
                q_table = trainer.train(train_closes)
                # 평가
                metrics = trainer.evaluate(q_table, test_closes)

                fold_approved = (
                    metrics.total_return_pct >= self.approval_threshold_pct
                    and metrics.max_drawdown_pct >= -50.0
                )

                folds.append(
                    FoldResult(
                        fold_idx=i,
                        train_size=len(train_closes),
                        test_size=len(test_closes),
                        train_start_idx=train_start,
                        train_end_idx=train_end,
                        test_start_idx=test_start,
                        test_end_idx=test_end,
                        metrics=metrics,
                        approved=fold_approved,
                    )
                )
            except Exception as e:
                logger.warning("Fold %d 평가 실패: %s", i, e)
                continue

        # 요약 통계 계산
        result = self._summarize(closes, folds)
        return result

    def _summarize(
        self, closes: list[float], folds: list[FoldResult]
    ) -> WalkForwardResult:
        """fold 결과를 종합."""
        if not folds:
            return WalkForwardResult(
                n_folds=self.n_folds,
                total_data_points=len(closes),
                folds=[],
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        returns = [f.metrics.total_return_pct for f in folds]
        excess_returns = [f.metrics.excess_return_pct for f in folds]
        drawdowns = [f.metrics.max_drawdown_pct for f in folds]
        win_rates = [f.metrics.win_rate for f in folds]
        approved_count = sum(1 for f in folds if f.approved)

        n = len(returns)
        avg_ret = sum(returns) / n
        std_ret = (sum((r - avg_ret) ** 2 for r in returns) / max(n - 1, 1)) ** 0.5

        # 일관성 점수: 양수 수익률 fold 비율 × (1 - CV)
        positive_ratio = sum(1 for r in returns if r > 0) / n
        cv = std_ret / abs(avg_ret) if abs(avg_ret) > 1e-6 else 1.0
        consistency = positive_ratio * max(0, 1 - min(cv, 2.0) / 2.0)

        overall = (
            approved_count / n >= self.consistency_threshold
            and avg_ret >= self.approval_threshold_pct
        )

        return WalkForwardResult(
            n_folds=len(folds),
            total_data_points=len(closes),
            folds=folds,
            avg_return_pct=round(avg_ret, 4),
            std_return_pct=round(std_ret, 4),
            min_return_pct=round(min(returns), 4),
            max_return_pct=round(max(returns), 4),
            avg_excess_return_pct=round(sum(excess_returns) / n, 4),
            avg_max_drawdown_pct=round(sum(drawdowns) / n, 4),
            avg_win_rate=round(sum(win_rates) / n, 4),
            approved_folds=approved_count,
            consistency_score=round(consistency, 4),
            overall_approved=overall,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


# ── Walk-Forward API 연동 엔드포인트 모델 ──────────────────────────────────


@dataclass
class WalkForwardRequest:
    """Walk-Forward 평가 요청."""

    ticker: str
    n_folds: int = 5
    expanding_window: bool = True
    trainer_version: str = "v2"  # "v1" | "v2"
    dataset_days: int = 120


@dataclass
class WalkForwardSummary:
    """Walk-Forward 평가 결과 요약 (API 응답용)."""

    ticker: str
    n_folds: int
    avg_return_pct: float
    std_return_pct: float
    consistency_score: float
    overall_approved: bool
    approved_folds: int
    total_folds: int
    created_at: str
