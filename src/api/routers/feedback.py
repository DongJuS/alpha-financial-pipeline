"""
src/api/routers/feedback.py — 피드백 루프 API 라우터

전략 정확도 통계, LLM 피드백 컨텍스트, 백테스트, RL 재학습, 피드백 사이클 실행 엔드포인트.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.agents.rl_continuous_improver import RLContinuousImprover
from src.agents.rl_experiment_manager import RLExperimentManager
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS = ROOT / "artifacts" / "rl"
_rl_improver: RLContinuousImprover | None = None


def _get_rl_improver() -> RLContinuousImprover:
    global _rl_improver
    if _rl_improver is None:
        _rl_improver = RLContinuousImprover(
            experiment_manager=RLExperimentManager(artifacts_dir=DEFAULT_ARTIFACTS),
            policy_store=RLPolicyStoreV2(models_dir=DEFAULT_ARTIFACTS / "models"),
        )
    return _rl_improver


# ── Response Models ──────────────────────────────────────────────────────


class AccuracyStats(BaseModel):
    strategy: str
    total_predictions: int
    correct_predictions: int
    accuracy: float
    signal_distribution: dict[str, int]
    period_start: str
    period_end: str


class LLMFeedbackContext(BaseModel):
    strategy: str
    feedback_text: str
    error_patterns: list[str]
    signal_bias: dict[str, float]
    generated_at: str
    cached: bool


class BacktestRequest(BaseModel):
    strategy: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = Field(default=10_000_000, gt=0)


class BacktestResult(BaseModel):
    strategy: str
    period: dict[str, str]
    initial_capital: float
    final_capital: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: Optional[float] = None
    win_rate: float
    profit_factor: Optional[float] = None
    total_trades: int
    avg_holding_days: Optional[float] = None


class StrategyComparison(BaseModel):
    strategies: list[BacktestResult]
    best_strategy: str
    ranking: list[dict[str, Any]]


class RetrainResultItem(BaseModel):
    ticker: str
    success: bool
    new_policy_id: Optional[str] = None
    excess_return: Optional[float] = None
    walk_forward_passed: bool = False
    deployed: bool = False
    error: Optional[str] = None


class RetrainBatchResponse(BaseModel):
    total_tickers: int
    successful: int
    failed: int
    results: list[RetrainResultItem]


class FeedbackCycleResponse(BaseModel):
    scope: str
    llm_feedback: Optional[dict[str, Any]] = None
    rl_retrain: Optional[dict[str, Any]] = None
    backtest: Optional[dict[str, Any]] = None
    duration_seconds: float
    saved_to_s3: bool


# ── 정확도 조회 ──────────────────────────────────────────────────────────


@router.get("/accuracy", response_model=list[AccuracyStats])
async def get_accuracy(
    strategy: Optional[str] = Query(None, description="전략 필터 (strategy_a, strategy_b)"),
    days: int = Query(default=30, ge=1, le=365, description="조회 기간 (일)"),
) -> list[AccuracyStats]:
    """전략별 예측 정확도 통계를 반환합니다."""
    now = datetime.now(timezone.utc)

    try:
        from src.utils.db_client import fetch

        # strategy 파라미터 매핑: strategy_a -> 'A', strategy_b -> 'B'
        _strategy_map = {"strategy_a": "A", "strategy_b": "B"}
        raw_strategies = [strategy] if strategy else ["strategy_a", "strategy_b"]
        result: list[AccuracyStats] = []

        for strat in raw_strategies:
            db_strategy = _strategy_map.get(strat, strat[-1:].upper())
            rows = await fetch(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE was_correct) AS correct,
                    signal
                FROM predictions
                WHERE strategy = $1
                  AND was_correct IS NOT NULL
                  AND timestamp_utc >= NOW() - ($2 || ' days')::interval
                GROUP BY signal
                """,
                db_strategy,
                str(days),
            )

            if rows:
                total = sum(r["total"] for r in rows)
                correct = sum(r["correct"] for r in rows)
                dist = {r["signal"]: int(r["total"]) for r in rows}
                result.append(
                    AccuracyStats(
                        strategy=strat,
                        total_predictions=total,
                        correct_predictions=correct,
                        accuracy=round(correct / total, 4) if total > 0 else 0.0,
                        signal_distribution=dist,
                        period_start=(now.isoformat()),
                        period_end=now.isoformat(),
                    )
                )
            else:
                result.append(
                    AccuracyStats(
                        strategy=strat,
                        total_predictions=0,
                        correct_predictions=0,
                        accuracy=0.0,
                        signal_distribution={},
                        period_start=now.isoformat(),
                        period_end=now.isoformat(),
                    )
                )

        return result
    except Exception as e:
        logger.warning("정확도 통계 조회 실패 (DB 미연결): %s", e)
        # DB 미연결 시 빈 데이터 반환
        strategies = [strategy] if strategy else ["strategy_a", "strategy_b"]
        return [
            AccuracyStats(
                strategy=s,
                total_predictions=0,
                correct_predictions=0,
                accuracy=0.0,
                signal_distribution={},
                period_start=now.isoformat(),
                period_end=now.isoformat(),
            )
            for s in strategies
        ]


# ── LLM 피드백 컨텍스트 ──────────────────────────────────────────────────


@router.get("/llm-context/{strategy}", response_model=LLMFeedbackContext)
async def get_llm_context(strategy: str) -> LLMFeedbackContext:
    """전략의 LLM 피드백 컨텍스트를 반환합니다."""
    now = datetime.now(timezone.utc)

    try:
        from src.utils.redis_client import get_redis

        redis = await get_redis()
        cached_key = f"feedback:llm_context:{strategy}"
        cached = await redis.get(cached_key)

        if cached:
            import json

            data = json.loads(cached)
            data["cached"] = True
            return LLMFeedbackContext(**data)
    except Exception as e:
        logger.warning("LLM 컨텍스트 캐시 조회 실패: %s", e)

    return LLMFeedbackContext(
        strategy=strategy,
        feedback_text="피드백 데이터가 아직 생성되지 않았습니다.",
        error_patterns=[],
        signal_bias={},
        generated_at=now.isoformat(),
        cached=False,
    )


# ── 백테스트 ─────────────────────────────────────────────────────────────


@router.post("/backtest", response_model=BacktestResult)
async def run_backtest(req: BacktestRequest) -> BacktestResult:
    """전략 백테스트를 실행합니다."""
    now = datetime.now(timezone.utc)
    return BacktestResult(
        strategy=req.strategy,
        period={
            "start": req.start_date or "2025-01-01",
            "end": req.end_date or now.strftime("%Y-%m-%d"),
        },
        initial_capital=req.initial_capital,
        final_capital=req.initial_capital,
        total_return=0.0,
        annualized_return=0.0,
        max_drawdown=0.0,
        sharpe_ratio=None,
        win_rate=0.0,
        profit_factor=None,
        total_trades=0,
        avg_holding_days=None,
    )


@router.post("/backtest/compare", response_model=StrategyComparison)
async def compare_strategies(
    payload: dict[str, Any] | None = None,
) -> StrategyComparison:
    """전략간 백테스트 비교를 실행합니다."""
    strategies = (payload or {}).get("strategies", ["strategy_a", "strategy_b"])
    now = datetime.now(timezone.utc)

    results = []
    for s in strategies:
        results.append(
            BacktestResult(
                strategy=s,
                period={"start": "2025-01-01", "end": now.strftime("%Y-%m-%d")},
                initial_capital=10_000_000,
                final_capital=10_000_000,
                total_return=0.0,
                annualized_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=None,
                win_rate=0.0,
                profit_factor=None,
                total_trades=0,
                avg_holding_days=None,
            )
        )

    return StrategyComparison(
        strategies=results,
        best_strategy=strategies[0] if strategies else "unknown",
        ranking=[
            {"strategy": s, "total_return": 0.0, "rank": i + 1}
            for i, s in enumerate(strategies)
        ],
    )


# ── RL 재학습 ────────────────────────────────────────────────────────────


@router.post("/rl/retrain/{ticker}", response_model=RetrainResultItem)
async def retrain_ticker(ticker: str) -> RetrainResultItem:
    """단일 종목 RL 모델을 재학습합니다."""
    logger.info("RL 재학습 요청: %s", ticker)
    outcome = await _get_rl_improver().retrain_ticker(ticker)
    return RetrainResultItem(
        ticker=outcome.ticker,
        success=outcome.success,
        new_policy_id=outcome.new_policy_id,
        excess_return=outcome.excess_return,
        walk_forward_passed=outcome.walk_forward_passed,
        deployed=outcome.deployed,
        error=outcome.error,
    )


@router.post("/rl/retrain-all", response_model=RetrainBatchResponse)
async def retrain_all() -> RetrainBatchResponse:
    """전체 종목 RL 재학습을 실행합니다."""
    logger.info("전체 RL 재학습 요청")
    outcomes = await _get_rl_improver().retrain_all()
    results = [
        RetrainResultItem(
            ticker=outcome.ticker,
            success=outcome.success,
            new_policy_id=outcome.new_policy_id,
            excess_return=outcome.excess_return,
            walk_forward_passed=outcome.walk_forward_passed,
            deployed=outcome.deployed,
            error=outcome.error,
        )
        for outcome in outcomes
    ]
    successful = sum(1 for item in results if item.success)
    return RetrainBatchResponse(
        total_tickers=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )


# ── 피드백 사이클 ────────────────────────────────────────────────────────


@router.post("/cycle", response_model=FeedbackCycleResponse)
async def run_feedback_cycle(
    payload: dict[str, Any] | None = None,
) -> FeedbackCycleResponse:
    """피드백 사이클을 실행합니다."""
    started = datetime.now(timezone.utc)
    scope = (payload or {}).get("scope", "full")
    logger.info("피드백 사이클 실행: scope=%s", scope)

    rl_summary: dict[str, Any] | None = None
    if scope in ("full", "rl_only"):
        improver = _get_rl_improver()
        tickers = (payload or {}).get("tickers")
        profile_ids = (payload or {}).get("profiles")
        dataset_days = int((payload or {}).get("dataset_days", 180))
        outcomes = await improver.retrain_all(
            tickers=tickers,
            profile_ids=profile_ids,
            dataset_days=dataset_days,
        )
        rl_summary = {
            "tickers_retrained": len(outcomes),
            "successful": sum(1 for item in outcomes if item.success),
            "deployed": sum(1 for item in outcomes if item.deployed),
        }

    return FeedbackCycleResponse(
        scope=scope,
        llm_feedback={"strategies_processed": 0, "cached": False}
        if scope in ("full", "llm_only")
        else None,
        rl_retrain=rl_summary,
        backtest={"strategies_compared": 0, "best_strategy": "N/A"}
        if scope in ("full", "backtest_only")
        else None,
        duration_seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 3),
        saved_to_s3=False,
    )
