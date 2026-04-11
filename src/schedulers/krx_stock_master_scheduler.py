"""
src/schedulers/krx_stock_master_scheduler.py — KrxStockMasterCollector 스케줄러

APScheduler를 사용하여 매일 08:10 KST에 KrxStockMasterCollector를 실행합니다.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.krx_stock_master_collector import KrxStockMasterCollector
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None
_collector: KrxStockMasterCollector | None = None


async def _run_krx_stock_master_collector() -> None:
    """KrxStockMasterCollector를 실행합니다."""
    if _collector is None:
        return
    try:
        await _collector.collect_krx_stock_master(include_etf=True)
    except Exception as exc:
        logger.warning("KrxStockMasterCollector 스케줄 실행 중 에러: %s", exc)


async def get_scheduler() -> AsyncIOScheduler:
    """스케줄러 싱글턴을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_krx_stock_master_scheduler() -> None:
    """KrxStockMasterCollector 스케줄러를 시작합니다."""
    global _collector, _scheduler

    _collector = KrxStockMasterCollector()
    scheduler = await get_scheduler()

    # 이미 스케줄되어 있으면 스톱
    if scheduler.running:
        logger.info("KrxStockMasterCollector scheduler already running")
        return

    # 매일 08:10 KST에 실행
    scheduler.add_job(
        _run_krx_stock_master_collector,
        CronTrigger(hour=8, minute=10, day_of_week="0-4", timezone=str(KST)),
        id="krx_stock_master_daily",
        name="KrxStockMasterCollector daily collection (08:10 KST)",
        misfire_grace_time=10,
    )

    scheduler.start()
    logger.info("✅ KrxStockMasterCollector scheduler started")


async def stop_krx_stock_master_scheduler() -> None:
    """KrxStockMasterCollector 스케줄러를 정지합니다."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 KrxStockMasterCollector scheduler stopped")
