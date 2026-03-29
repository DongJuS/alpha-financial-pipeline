"""
src/schedulers/index_scheduler.py — KOSPI/KOSDAQ 지수 수집 스케줄러

APScheduler를 사용하여 시장 시간 중(09:00~15:30 KST, 월~금) 30초마다
지수를 수집하고, 사전 워밍업을 위해 08:55에 한 번 실행합니다.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.index_collector import IndexCollector
from src.utils.logging import get_logger
from src.utils.market_hours import is_market_open_now

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None
_collector: IndexCollector | None = None


async def _collect_if_market_open() -> None:
    """시장이 열려 있으면 지수를 수집합니다."""
    if _collector is None:
        return
    try:
        if await is_market_open_now():
            await _collector.collect_once()
    except Exception as exc:
        logger.warning("지수 수집 스케줄 실행 중 에러: %s", exc)


async def get_scheduler() -> AsyncIOScheduler:
    """스케줄러 싱글톤을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_index_scheduler() -> None:
    """지수 수집 스케줄러를 시작합니다."""
    global _collector, _scheduler

    _collector = IndexCollector()
    scheduler = await get_scheduler()

    # 이미 스케줄되어 있으면 스톱
    if scheduler.running:
        logger.info("Index scheduler already running")
        return

    # 사전 워밍업: 매일 08:55 KST에 한 번 수집
    scheduler.add_job(
        _collector.collect_once,
        CronTrigger(hour=8, minute=55, day_of_week="0-4", timezone=str(KST)),
        id="index_warmup",
        name="Index collection warmup (08:55 KST)",
        misfire_grace_time=10,
    )

    # 정규 수집: 매 30초마다 시장 시간 중에만 실행
    scheduler.add_job(
        _collect_if_market_open,
        "interval",
        seconds=30,
        id="index_collection",
        name="Index collection every 30s",
        misfire_grace_time=5,
    )

    scheduler.start()
    logger.info("✅ Index scheduler started")

    # 서버 시작 직후 즉시 1회 수집 (장중이면 캐시 즉시 채움)
    await _collect_if_market_open()


async def stop_index_scheduler() -> None:
    """지수 수집 스케줄러를 정지합니다."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 Index scheduler stopped")
