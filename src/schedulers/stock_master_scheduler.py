"""
src/schedulers/stock_master_scheduler.py — StockMasterCollector 스케줄러

APScheduler를 사용하여 매일 08:10 KST에 StockMasterCollector를 실행합니다.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.stock_master_collector import StockMasterCollector
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None
_collector: StockMasterCollector | None = None


async def _run_stock_master_collector() -> None:
    """StockMasterCollector를 실행합니다."""
    if _collector is None:
        return
    try:
        await _collector.collect_stock_master(include_etf=True)
    except Exception as exc:
        logger.warning("StockMasterCollector 스케줄 실행 중 에러: %s", exc)


async def get_scheduler() -> AsyncIOScheduler:
    """스케줄러 싱글턴을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_stock_master_scheduler() -> None:
    """StockMasterCollector 스케줄러를 시작합니다."""
    global _collector, _scheduler

    _collector = StockMasterCollector()
    scheduler = await get_scheduler()

    # 이미 스케줄되어 있으면 스톱
    if scheduler.running:
        logger.info("StockMasterCollector scheduler already running")
        return

    # 매일 08:10 KST에 실행
    scheduler.add_job(
        _run_stock_master_collector,
        CronTrigger(hour=8, minute=10, day_of_week="0-4", timezone=str(KST)),
        id="stock_master_daily",
        name="StockMasterCollector daily collection (08:10 KST)",
        misfire_grace_time=10,
    )

    scheduler.start()
    logger.info("✅ StockMasterCollector scheduler started")


async def stop_stock_master_scheduler() -> None:
    """StockMasterCollector 스케줄러를 정지합니다."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 StockMasterCollector scheduler stopped")
