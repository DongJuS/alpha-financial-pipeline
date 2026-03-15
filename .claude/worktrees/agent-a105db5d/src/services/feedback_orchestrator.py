"""
src/services/feedback_orchestrator.py — 피드백 루프 오케스트레이터

모든 피드백 파이프라인을 통합 실행하는 오케스트레이터입니다.

일일 배치 (장 마감 후):
    1. LLM 피드백 컨텍스트 갱신 (predictions + outcomes → 프롬프트 컨텍스트)
    2. RL 재학습 (daily_bars → Q-learning 재학습 → 정책 비교 → 승격)
    3. 백테스트 실행 (전략 간 성과 비교)
    4. 결과를 Redis 캐시 + S3에 저장

사용 예:
    results = await run_daily_feedback()
    results = await run_feedback_cycle(scope="full")
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FeedbackCycleResult:
    """피드백 사이클 실행 결과."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scope: str = "full"
    llm_feedback: dict[str, Any] = field(default_factory=dict)
    rl_retrain: dict[str, Any] = field(default_factory=dict)
    backtest: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


async def _run_llm_feedback(lookback_days: int = 14) -> dict[str, Any]:
    """LLM 피드백 컨텍스트를 생성하고 Redis에 캐시합니다."""
    from src.services.llm_feedback import build_feedback_context, analyze_performance

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=lookback_days)

    # 전략별 피드백 컨텍스트 생성
    contexts: dict[str, str] = {}
    accuracy_stats: dict[str, Any] = {}

    for strategy in ["A", "B", "RL"]:
        ctx = await build_feedback_context(strategy=strategy, lookback_days=lookback_days)
        if ctx:
            contexts[strategy] = ctx

        perf = await analyze_performance(start, end, strategy=strategy)
        accuracy_stats[strategy] = {
            "total": perf.total_predictions,
            "evaluated": perf.evaluated_predictions,
            "accuracy": perf.overall_accuracy,
            "avg_pnl_pct": perf.avg_pnl_pct,
        }

    # Redis에 캐시 (PredictorAgent가 읽음)
    try:
        from src.utils.redis_client import get_redis
        redis = await get_redis()
        for strategy, ctx in contexts.items():
            await redis.set(
                f"feedback:llm_context:{strategy}",
                ctx,
                ex=86400,  # 24시간 TTL
            )
        await redis.set(
            "feedback:accuracy_stats",
            json.dumps(accuracy_stats, ensure_ascii=False),
            ex=86400,
        )
    except Exception as e:
        logger.warning("Redis 피드백 캐시 실패: %s", e)

    return {
        "strategies_updated": list(contexts.keys()),
        "accuracy": accuracy_stats,
    }


async def _run_rl_retrain(
    days: int = 180,
    auto_deploy: bool = False,
) -> dict[str, Any]:
    """RL 모델 일괄 재학습을 실행합니다."""
    from src.services.rl_retrain_pipeline import retrain_all_tickers

    results = await retrain_all_tickers(days=days, auto_deploy=auto_deploy)

    summary = {
        "total_tickers": len(results),
        "success": sum(1 for r in results if r.status == "success"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "deployed": sum(1 for r in results if r.deployed),
        "avg_excess_return_pct": 0.0,
    }

    success_results = [r for r in results if r.status == "success"]
    if success_results:
        summary["avg_excess_return_pct"] = round(
            sum(r.excess_return_pct for r in success_results) / len(success_results), 2
        )

    return summary


async def _run_backtest_comparison(days: int = 30) -> dict[str, Any]:
    """전략 간 백테스트 성과 비교를 실행합니다."""
    from src.services.backtest_engine import compare_strategies

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)

    comparison = await compare_strategies(start, end)
    return comparison


async def run_feedback_cycle(
    scope: Literal["full", "llm_only", "rl_only", "backtest_only"] = "full",
    rl_auto_deploy: bool = False,
) -> FeedbackCycleResult:
    """피드백 사이클을 실행합니다.

    Args:
        scope: 실행 범위
            - full: LLM 피드백 + RL 재학습 + 백테스트 (전체)
            - llm_only: LLM 피드백 컨텍스트만 갱신
            - rl_only: RL 재학습만 실행
            - backtest_only: 백테스트 비교만 실행
        rl_auto_deploy: RL 재학습 시 자동 배포 여부

    Returns:
        FeedbackCycleResult
    """
    result = FeedbackCycleResult(scope=scope)
    logger.info("피드백 사이클 시작 (scope=%s)", scope)

    # 1. LLM 피드백
    if scope in ("full", "llm_only"):
        try:
            result.llm_feedback = await _run_llm_feedback()
            logger.info("LLM 피드백 완료: %s", result.llm_feedback.get("strategies_updated"))
        except Exception as e:
            msg = f"LLM 피드백 실패: {e}"
            logger.error(msg)
            result.errors.append(msg)

    # 2. RL 재학습
    if scope in ("full", "rl_only"):
        try:
            result.rl_retrain = await _run_rl_retrain(auto_deploy=rl_auto_deploy)
            logger.info("RL 재학습 완료: %s", result.rl_retrain)
        except Exception as e:
            msg = f"RL 재학습 실패: {e}"
            logger.error(msg)
            result.errors.append(msg)

    # 3. 백테스트
    if scope in ("full", "backtest_only"):
        try:
            result.backtest = await _run_backtest_comparison()
            logger.info("백테스트 비교 완료: ranking=%s", result.backtest.get("ranking"))
        except Exception as e:
            msg = f"백테스트 실패: {e}"
            logger.error(msg)
            result.errors.append(msg)

    # 4. 결과를 S3에 보관
    try:
        from src.services.datalake import store_records, DataType
        await store_records(
            DataType.RESEARCH,
            [{
                "ticker": "SYSTEM",
                "timestamp": datetime.now(),
                "model": "feedback_orchestrator",
                "summary": json.dumps(asdict(result), ensure_ascii=False, default=str)[:2000],
                "sentiment": "neutral",
                "confidence": 0.0,
                "raw_output": json.dumps(asdict(result), ensure_ascii=False, default=str),
            }],
            filename="feedback_cycle",
        )
    except Exception:
        logger.debug("피드백 결과 S3 저장 실패 (비필수)")

    logger.info("피드백 사이클 완료 (errors=%d)", len(result.errors))
    return result


async def run_daily_feedback() -> FeedbackCycleResult:
    """일일 피드백 배치를 실행합니다 (장 마감 후 호출)."""
    return await run_feedback_cycle(scope="full", rl_auto_deploy=False)
