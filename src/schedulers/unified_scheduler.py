"""
src/schedulers/unified_scheduler.py — 통합 스케줄러

분산된 4개 AsyncIOScheduler를 단일 인스턴스로 통합합니다.
- job_wrapper.py: 재시도 + 실행 이력 기록
- distributed_lock.py: 중복 실행 방지 (Redis NX 락)

등록된 잡:
    stock_master_daily  08:10 KST  StockMasterCollector
    macro_daily         08:20 KST  MacroCollector
    collector_daily     08:30 KST  CollectorAgent
    index_warmup        08:55 KST  IndexCollector (워밍업)
    index_collection    30초 인터벌  IndexCollector (장중)
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.schedulers.distributed_lock import DistributedLock
from src.schedulers.job_wrapper import with_retry
from src.utils.logging import get_logger

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

_scheduler: AsyncIOScheduler | None = None

# 분산 락 TTL (초) — 잡 최대 실행 예상 시간보다 넉넉하게
_LOCK_TTL: dict[str, int] = {
    "stock_master_daily": 300,   # 5분
    "macro_daily": 300,          # 5분
    "collector_daily": 600,      # 10분
    "index_warmup": 60,          # 1분
    "index_collection": 25,      # 30초 인터벌보다 짧게
}


def _locked_job(job_id: str, coro_fn):  # type: ignore[no-untyped-def]
    """분산 락 + 재시도를 적용한 잡 래퍼를 반환합니다."""

    async def _inner() -> None:
        from src.utils.redis_client import get_redis

        redis = await get_redis()
        lock_key = f"scheduler:lock:{job_id}"
        async with DistributedLock(redis, lock_key, ttl=_LOCK_TTL.get(job_id, 120)):
            if not (await redis.get(lock_key) is not None
                    or True):  # acquired 여부는 context manager 내부에서 처리됨
                return
            await coro_fn()

    # _inner 자체도 lock을 거는 래퍼인데, DistributedLock.acquired를 바깥에서
    # 확인하기 위해 구조를 단순화합니다.
    async def _locked() -> None:
        from src.utils.redis_client import get_redis

        redis = await get_redis()
        lock_key = f"scheduler:lock:{job_id}"
        async with DistributedLock(redis, lock_key, ttl=_LOCK_TTL.get(job_id, 120)) as lock:
            if not lock.acquired:
                logger.debug("잡 스킵 (락 획득 실패): %s", job_id)
                return
            await coro_fn()

    return with_retry(_locked, job_id)


async def get_unified_scheduler() -> AsyncIOScheduler:
    """통합 스케줄러 싱글턴을 반환합니다."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=str(KST))
    return _scheduler


async def start_unified_scheduler() -> None:
    """통합 스케줄러를 시작하고 모든 잡을 등록합니다."""
    global _scheduler

    scheduler = await get_unified_scheduler()
    if scheduler.running:
        logger.info("Unified scheduler already running")
        return

    # ── 에이전트/콜렉터 지연 임포트 (순환 임포트 방지) ──────────────────────────
    from src.agents.collector import CollectorAgent
    from src.agents.index_collector import IndexCollector
    from src.agents.macro_collector import MacroCollector
    from src.agents.stock_master_collector import StockMasterCollector
    from src.utils.market_hours import is_market_open_now

    stock_master = StockMasterCollector()
    macro = MacroCollector()
    collector = CollectorAgent()
    index = IndexCollector()

    # ── 원본 잡 함수 정의 ────────────────────────────────────────────────────
    async def _run_stock_master() -> None:
        await stock_master.collect_stock_master(include_etf=True)

    async def _run_macro() -> None:
        await macro.collect_all()

    async def _run_collector() -> None:
        await collector.run()

    async def _run_index_warmup() -> None:
        await index.collect_once()

    async def _run_index_if_open() -> None:
        if await is_market_open_now():
            await index.collect_once()

    # ── 잡 등록 ──────────────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("stock_master_daily", _run_stock_master),
        CronTrigger(hour=8, minute=10, day_of_week="0-4", timezone=str(KST)),
        id="stock_master_daily",
        name="StockMasterCollector daily (08:10 KST)",
        misfire_grace_time=10,
        replace_existing=True,
    )

    scheduler.add_job(
        _locked_job("macro_daily", _run_macro),
        CronTrigger(hour=8, minute=20, day_of_week="0-4", timezone=str(KST)),
        id="macro_daily",
        name="MacroCollector daily (08:20 KST)",
        misfire_grace_time=10,
        replace_existing=True,
    )

    scheduler.add_job(
        _locked_job("collector_daily", _run_collector),
        CronTrigger(hour=8, minute=30, day_of_week="0-4", timezone=str(KST)),
        id="collector_daily",
        name="CollectorAgent daily (08:30 KST)",
        misfire_grace_time=10,
        replace_existing=True,
    )

    scheduler.add_job(
        _locked_job("index_warmup", _run_index_warmup),
        CronTrigger(hour=8, minute=55, day_of_week="0-4", timezone=str(KST)),
        id="index_warmup",
        name="Index collection warmup (08:55 KST)",
        misfire_grace_time=10,
        replace_existing=True,
    )

    scheduler.add_job(
        _locked_job("index_collection", _run_index_if_open),
        "interval",
        seconds=30,
        id="index_collection",
        name="Index collection every 30s",
        misfire_grace_time=5,
        replace_existing=True,
    )

    scheduler.start()
    logger.info("✅ Unified scheduler started (5 jobs registered)")

    # 서버 시작 직후 장중이면 즉시 1회 수집
    try:
        if await is_market_open_now():
            await index.collect_once()
    except Exception as exc:
        logger.warning("시작 직후 즉시 수집 실패 (비필수): %s", exc)


async def stop_unified_scheduler() -> None:
    """통합 스케줄러를 정지합니다."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        logger.info("🔴 Unified scheduler stopped")


def get_scheduler_status() -> dict:
    """
    현재 스케줄러 상태와 등록된 잡 정보를 반환합니다.
    (동기 함수 — FastAPI 라우터에서 직접 호출 가능)
    """
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
            }
        )

    return {
        "running": True,
        "job_count": len(jobs),
        "jobs": jobs,
    }
