"""
src/api/routers/feedback.py — 피드백 루프 API 엔드포인트

LLM 피드백, RL 재학습, 백테스트, 성과 분석 API를 제공합니다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_current_user

router = APIRouter(prefix="/feedback", tags=["feedback"])


# ── Response Models ──────────────────────────────────────────────────────


class AccuracyStats(BaseModel):
    period: dict[str, str]
    total: int
    evaluated: int
    correct: int
    accuracy: float
    avg_pnl_pct: float
    by_strategy: dict[str, Any]
    by_signal: dict[str, Any]


class BacktestResultResponse(BaseModel):
    strategy: str
    period_start: str
    period_end: str
    initial_capital: int
    final_equity: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: Optional[float]
    win_rate: float
    total_trades: int
    avg_holding_days: float
    profit_factor: Optional[float]
    benchmark_return_pct: float = 0.0


class StrategyComparisonResponse(BaseModel):
    period: dict[str, str]
    initial_capital: int
    strategies: dict[str, Any]
    ranking: list[str]


class RetrainResultItem(BaseModel):
    ticker: str
    status: str
    data_points: int
    excess_return_pct: float
    walk_forward_passed: bool
    deployed: bool


class RetrainBatchResponse(BaseModel):
    total_tickers: int
    success: int
    skipped: int
    failed: int
    deployed: int
    avg_excess_return_pct: float


class FeedbackCycleResponse(BaseModel):
    timestamp: str
    scope: str
    llm_feedback: dict[str, Any]
    rl_retrain: dict[str, Any]
    backtest: dict[str, Any]
    errors: list[str]


class LLMFeedbackContextResponse(BaseModel):
    strategy: str
    context: str
    has_feedback: bool


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/accuracy", response_model=AccuracyStats)
async def get_prediction_accuracy(
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=14, ge=1, le=365),
    strategy: Optional[str] = Query(default=None),
) -> AccuracyStats:
    """기간별 예측 정확도 및 P&L 통계를 반환합니다."""
    from src.services.datalake_reader import compute_strategy_accuracy

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    stats = await compute_strategy_accuracy(start, end, strategy=strategy)
    return AccuracyStats(**stats)


@router.get("/llm-context/{strategy}", response_model=LLMFeedbackContextResponse)
async def get_llm_feedback_context(
    strategy: str,
    _: Annotated[dict, Depends(get_current_user)],
    lookback_days: int = Query(default=14, ge=1, le=90),
) -> LLMFeedbackContextResponse:
    """LLM에 주입되는 피드백 컨텍스트를 확인합니다."""
    from src.services.llm_feedback import build_feedback_context

    context = await build_feedback_context(strategy=strategy, lookback_days=lookback_days)
    return LLMFeedbackContextResponse(
        strategy=strategy,
        context=context,
        has_feedback=bool(context),
    )


@router.post("/backtest", response_model=BacktestResultResponse)
async def run_backtest_endpoint(
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=30, ge=7, le=365),
    strategy: Optional[str] = Query(default=None),
    initial_capital: int = Query(default=100_000_000, ge=1_000_000),
) -> BacktestResultResponse:
    """S3 히스토리컬 데이터로 백테스트를 실행합니다."""
    from src.services.backtest_engine import run_backtest

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    result = await run_backtest(start, end, strategy=strategy, initial_capital=initial_capital)

    return BacktestResultResponse(
        strategy=result.strategy,
        period_start=result.period_start,
        period_end=result.period_end,
        initial_capital=result.initial_capital,
        final_equity=result.final_equity,
        total_return_pct=result.total_return_pct,
        annualized_return_pct=result.annualized_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        sharpe_ratio=result.sharpe_ratio,
        win_rate=result.win_rate,
        total_trades=result.total_trades,
        avg_holding_days=result.avg_holding_days,
        profit_factor=result.profit_factor,
    )


@router.post("/backtest/compare", response_model=StrategyComparisonResponse)
async def compare_strategies_endpoint(
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=30, ge=7, le=365),
    initial_capital: int = Query(default=100_000_000, ge=1_000_000),
) -> StrategyComparisonResponse:
    """전략 간 백테스트 성과를 비교합니다."""
    from src.services.backtest_engine import compare_strategies

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    comparison = await compare_strategies(start, end, initial_capital=initial_capital)

    return StrategyComparisonResponse(**comparison)


@router.post("/rl/retrain/{ticker}", response_model=RetrainResultItem)
async def retrain_single_ticker(
    ticker: str,
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=180, ge=30, le=730),
    auto_deploy: bool = Query(default=False),
) -> RetrainResultItem:
    """특정 종목의 RL 모델을 S3 데이터로 재학습합니다."""
    from src.services.rl_retrain_pipeline import retrain_from_datalake

    result = await retrain_from_datalake(
        ticker=ticker, days=days, auto_deploy=auto_deploy,
    )
    return RetrainResultItem(
        ticker=result.ticker,
        status=result.status,
        data_points=result.data_points,
        excess_return_pct=result.excess_return_pct,
        walk_forward_passed=result.walk_forward_passed,
        deployed=result.deployed,
    )


@router.post("/rl/retrain-all", response_model=RetrainBatchResponse)
async def retrain_all_endpoint(
    _: Annotated[dict, Depends(get_current_user)],
    days: int = Query(default=180, ge=30, le=730),
    auto_deploy: bool = Query(default=False),
) -> RetrainBatchResponse:
    """S3에 데이터가 있는 모든 종목의 RL 모델을 일괄 재학습합니다."""
    from src.services.rl_retrain_pipeline import retrain_all_tickers

    results = await retrain_all_tickers(days=days, auto_deploy=auto_deploy)

    success = [r for r in results if r.status == "success"]
    return RetrainBatchResponse(
        total_tickers=len(results),
        success=len(success),
        skipped=sum(1 for r in results if r.status == "skipped"),
        failed=sum(1 for r in results if r.status == "failed"),
        deployed=sum(1 for r in results if r.deployed),
        avg_excess_return_pct=round(
            sum(r.excess_return_pct for r in success) / len(success), 2
        ) if success else 0.0,
    )


@router.post("/cycle", response_model=FeedbackCycleResponse)
async def run_feedback_cycle_endpoint(
    _: Annotated[dict, Depends(get_current_user)],
    scope: Literal["full", "llm_only", "rl_only", "backtest_only"] = Query(default="full"),
    rl_auto_deploy: bool = Query(default=False),
) -> FeedbackCycleResponse:
    """피드백 루프 사이클을 수동 실행합니다."""
    from src.services.feedback_orchestrator import run_feedback_cycle

    result = await run_feedback_cycle(scope=scope, rl_auto_deploy=rl_auto_deploy)
    return FeedbackCycleResponse(
        timestamp=result.timestamp,
        scope=result.scope,
        llm_feedback=result.llm_feedback,
        rl_retrain=result.rl_retrain,
        backtest=result.backtest,
        errors=result.errors,
    )
