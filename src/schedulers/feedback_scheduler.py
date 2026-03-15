"""
src/schedulers/feedback_scheduler.py — 피드백 루프 스케줄러

APScheduler를 사용하여 다음 작업을 자동 실행합니다:
  1. 16:00 KST (월~금): run_daily_feedback() — 장 마감 후 전체 피드백 배치
  2. 08:30 KST (월~금): run_feedback_cycle(scope="llm_only") — 장 개장 전 LLM 컨텍스트 갱신
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.services.feedback_orchestrator import run_daily_feedback, run_feedback_cycle
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None


async def _run_llm_context_update() -> None:
    """장 개장 전 LLM 컨텍스트를 갱신합니다."""
    try:
        result = await run_feedback_cycle(scope="llm_only", rl_auto_deploy=False)
        logger.info(
            "LLM 컨텍스트 갱신 완료: %d strategies updated",
            len(result.llm_feedback.get("strategies_updated", [])),
        )
    except Exception as exc:
        logger.warning("LLM 컨텍스트 갱신 실패: %s", exc)


async def _run_daily_feedback_batch() -> None:
    """장 마감 후 일일 피드백 배치를 실행합니다."""
    try:
        result = await run_daily_feedback()
        logger.info(
            "일일 피드백 배치 완료: llm=%s, rl=%s, backtest=%s, errors=%d",
            bool(result.llm_feedback),
            bool(result.rl_retrain),
            bool(result.backtest),
            len(result.errors),
        )
    except Exception as exc:
        logger.warning("일일 피드백 배치 실패: %s", exc)


async def get_scheduler() -> AsyncIOScheduler:
    """스케줄러 싱글톤을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_feedback_scheduler() -> None:
    """피드백 루프 스케줄러를 시작합니다."""
    global _scheduler

    scheduler = await get_scheduler()

    if scheduler.running:
        logger.info("Feedback scheduler already running")
        return

    # 08:30 KST (월~금): 장 개장 전 LLM 컨텍스트 갱신
    scheduler.add_job(
        _run_llm_context_update,
        CronTrigger(hour=8, minute=30, day_of_week="0-4", timezone=str(KST)),
        id="feedback_llm_context",
        name="LLM context update (08:30 KST)",
        misfire_grace_time=10,
    )

    # 16:00 KST (월~금): 장 마감 후 일일 피드백 배치
    scheduler.add_job(
        _run_daily_feedback_batch,
        CronTrigger(hour=16, minute=0, day_of_week="0-4", timezone=str(KST)),
        id="feedback_daily_batch",
        name="Daily feedback batch (16:00 KST)",
        misfire_grace_time=10,
    )

    scheduler.start()
    logger.info("✅ Feedback scheduler started")


async def stop_feedback_scheduler() -> None:
    """피드백 루프 스케줄러를 정지합니다."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 Feedback scheduler stopped")
