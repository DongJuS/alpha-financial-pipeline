"""
src/schedulers/collector_agent_scheduler.py — CollectorAgent 일봉 스케줄러

APScheduler를 사용하여 매일 08:30 KST에 CollectorAgent를 실행합니다.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.collector import CollectorAgent
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None
_agent: CollectorAgent | None = None


async def _run_collector() -> None:
    """CollectorAgent를 실행합니다."""
    if _agent is None:
        return
    try:
        await _agent.run()
    except Exception as exc:
        logger.warning("CollectorAgent 스케줄 실행 중 에러: %s", exc)


async def get_scheduler() -> AsyncIOScheduler:
    """스케줄러 싱글턴을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_collector_scheduler() -> None:
    """CollectorAgent 스케줄러를 시작합니다."""
    global _agent, _scheduler

    _agent = CollectorAgent()
    scheduler = await get_scheduler()

    # 이미 스케줄되어 있으면 스톱
    if scheduler.running:
        logger.info("CollectorAgent scheduler already running")
        return

    # 매일 08:30 KST에 실행
    scheduler.add_job(
        _run_collector,
        CronTrigger(hour=8, minute=30, day_of_week="0-4", timezone=str(KST)),
        id="collector_daily",
        name="CollectorAgent daily collection (08:30 KST)",
        misfire_grace_time=10,
    )

    scheduler.start()
    logger.info("✅ CollectorAgent scheduler started")


async def stop_collector_scheduler() -> None:
    """CollectorAgent 스케줄러를 정지합니다."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 CollectorAgent scheduler stopped")
