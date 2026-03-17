"""
src/schedulers/macro_collector_scheduler.py — MacroCollector 스케줄러

APScheduler를 사용하여 매일 08:20 KST에 MacroCollector를 실행합니다.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.macro_collector import MacroCollector
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None
_collector: MacroCollector | None = None


async def _run_macro_collector() -> None:
    """MacroCollector를 실행합니다."""
    if _collector is None:
        return
    try:
        await _collector.collect_all()
    except Exception as exc:
        logger.warning("MacroCollector 스케줄 실행 중 에러: %s", exc)


async def get_scheduler() -> AsyncIOScheduler:
    """스케줄러 싱글턴을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_macro_scheduler() -> None:
    """MacroCollector 스케줄러를 시작합니다."""
    global _collector, _scheduler

    _collector = MacroCollector()
    scheduler = await get_scheduler()

    # 이미 스케줄되어 있으면 스톱
    if scheduler.running:
        logger.info("MacroCollector scheduler already running")
        return

    # 매일 08:20 KST에 실행
    scheduler.add_job(
        _run_macro_collector,
        CronTrigger(hour=8, minute=20, day_of_week="0-4", timezone=str(KST)),
        id="macro_daily",
        name="MacroCollector daily collection (08:20 KST)",
        misfire_grace_time=10,
    )

    scheduler.start()
    logger.info("✅ MacroCollector scheduler started")


async def stop_macro_scheduler() -> None:
    """MacroCollector 스케줄러를 정지합니다."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 MacroCollector scheduler stopped")
