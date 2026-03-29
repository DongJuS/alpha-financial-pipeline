"""
src/schedulers/unified_scheduler.py — 통합 스케줄러

분산된 4개 AsyncIOScheduler를 단일 인스턴스로 통합합니다.
- job_wrapper.py: 재시도 + 실행 이력 기록
- distributed_lock.py: 중복 실행 방지 (Redis NX 락)

등록된 잡:
    [장 전]
    rl_bootstrap        08:00 KST  RL 부트스트랩 (활성 정책 없으면 학습, 있으면 워밍업)
    predictor_warmup    08:05 KST  A/B Predictor LLM 클라이언트 워밍업
    stock_master_daily  08:10 KST  StockMasterCollector
    macro_daily         08:20 KST  MacroCollector
    collector_daily     08:30 KST  CollectorAgent
    index_warmup        08:55 KST  IndexCollector (워밍업)

    [장 중]
    index_collection    30초 인터벌  IndexCollector (장중)

    [장 후]
    rl_retrain          16:00 KST  RL 전략 재학습
    blend_weight_adjust 16:30 KST  블렌딩 가중치 동적 조정
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
    # 장 전
    "rl_bootstrap": 1800,         # 30분 (시딩+학습 포함 가능)
    "predictor_warmup": 180,     # 3분 (LLM API 호출 포함)
    "stock_master_daily": 300,   # 5분
    "macro_daily": 300,          # 5분
    "collector_daily": 600,      # 10분
    "index_warmup": 60,          # 1분
    "index_collection": 25,      # 30초 인터벌보다 짧게
    # 장 후
    "rl_retrain": 3600,          # 60분 (멀티 티커 학습)
    "blend_weight_adjust": 120,  # 2분
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

    # -- 장 전: RL 부트스트랩 (08:00 KST) --
    async def _run_rl_bootstrap() -> None:
        """활성 정책이 없는 티커에 대해 RL 부트스트랩을 실행한다.

        이미 활성 정책이 있으면 정책 로드·검증만 수행(워밍업).
        활성 정책이 없으면 RLContinuousImprover.retrain_ticker()로
        FDR 데이터 기반 학습→활성화 파이프라인을 실행한다.
        """
        from src.agents.rl_continuous_improver import RLContinuousImprover
        from src.agents.rl_policy_store_v2 import RLPolicyStoreV2

        store = RLPolicyStoreV2()
        registry = store.load_registry()
        active_map = registry.list_active_policies()
        all_tickers = registry.list_all_tickers()

        # 활성 정책 있는 티커 → 워밍업 (로드·검증)
        warmed = 0
        for ticker, policy_id in active_map.items():
            try:
                store.load_policy(policy_id, ticker)
                warmed += 1
            except Exception as exc:
                logger.warning("RL 워밍업: %s/%s 로드 실패 — %s", ticker, policy_id, exc)
        if warmed:
            logger.info("RL 워밍업: %d/%d 정책 로드 완료", warmed, len(active_map))

        # 활성 정책 없는 티커 → 부트스트랩 (학습→검증→활성화)
        missing = [t for t in all_tickers if t not in active_map]
        if not missing:
            logger.info("RL 부트스트랩: 모든 티커에 활성 정책 있음 — 스킵")
            return

        logger.info("RL 부트스트랩: %d 티커에 활성 정책 없음 → 학습 시작: %s", len(missing), missing)
        improver = RLContinuousImprover(policy_store=store)
        bootstrapped = 0
        for ticker in missing:
            try:
                outcome = await improver.retrain_ticker(ticker, dataset_days=720)
                if outcome.success:
                    bootstrapped += 1
                    logger.info(
                        "RL 부트스트랩: %s → %s (정책: %s)",
                        ticker,
                        "활성화 완료" if outcome.deployed else "승격 게이트 미통과",
                        outcome.new_policy_id or "N/A",
                    )
                else:
                    logger.warning("RL 부트스트랩: %s 학습 실패 — %s", ticker, outcome.error)
            except Exception as exc:
                logger.warning("RL 부트스트랩: %s 실패 — %s", ticker, exc)
        logger.info("RL 부트스트랩 완료: %d/%d 티커 처리", bootstrapped, len(missing))

    # -- 장 전: A/B Predictor 워밍업 (08:05 KST) --
    async def _run_predictor_warmup() -> None:
        """A/B 전략 Predictor의 LLM 클라이언트를 사전 초기화한다."""
        from src.agents.predictor import PredictorAgent
        from src.agents.strategy_a_tournament import PROFILES

        warmup_count = 0
        for profile in PROFILES:
            try:
                agent = PredictorAgent(
                    agent_id=profile.agent_id,
                    strategy="A",
                    llm_model=profile.model,
                    persona=profile.persona,
                )
                # LLM 클라이언트 초기화는 __init__에서 완료됨.
                # 실제 API 연결 검증을 위해 가볍게 인스턴스 생성만 수행.
                warmup_count += 1
            except Exception as exc:
                logger.warning("Predictor 워밍업 실패 [%s]: %s", profile.agent_id, exc)
        logger.info("Predictor 워밍업 완료: %d/%d 에이전트", warmup_count, len(PROFILES))

    # -- 기존 데이터 수집 잡 --
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

    # -- 장 후: RL 재학습 (16:00 KST) --
    async def _run_rl_retrain() -> None:
        """장 마감 후 모든 RL 정책을 재학습한다."""
        from src.agents.rl_continuous_improver import RLContinuousImprover

        improver = RLContinuousImprover()
        outcomes = await improver.retrain_all()
        success = sum(1 for o in outcomes if o.success)
        logger.info(
            "RL 재학습 완료: %d/%d 성공",
            success,
            len(outcomes),
        )

    # -- 장 후: 블렌딩 가중치 동적 조정 (16:30 KST) --
    async def _run_blend_weight_adjust() -> None:
        """성과 기반으로 A/B/RL 블렌딩 가중치를 재계산·기록한다."""
        from src.utils.blend_weight_optimizer import (
            BlendWeightOptimizer,
            fetch_strategy_performance,
        )
        from src.utils.config import get_settings

        settings = get_settings()
        if not settings.dynamic_blend_weights_enabled:
            logger.info("블렌딩 가중치 조정: DYNAMIC_BLEND_WEIGHTS_ENABLED=false — 스킵")
            return

        import json as _json

        base_weights: dict[str, float] = _json.loads(settings.strategy_blend_weights)
        optimizer = BlendWeightOptimizer(
            base_weights=base_weights,
            lookback_days=settings.dynamic_blend_lookback_days,
            min_weight=settings.dynamic_blend_min_weight,
        )
        new_weights = await optimizer.optimize()

        # Redis에 최신 가중치 캐싱 (오케스트레이터가 다음 사이클에서 참조)
        try:
            from src.utils.redis_client import get_redis

            redis = await get_redis()
            await redis.set(
                "scheduler:blend_weights:latest",
                _json.dumps(new_weights),
                ex=86400,  # 24시간 TTL
            )
        except Exception as exc:
            logger.warning("블렌딩 가중치 Redis 캐싱 실패 (비필수): %s", exc)

        logger.info("블렌딩 가중치 동적 조정 완료: %s", new_weights)

    # ── 잡 등록: 장 전 ─────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("rl_bootstrap", _run_rl_bootstrap),
        CronTrigger(hour=8, minute=0, day_of_week="0-4", timezone=str(KST)),
        id="rl_bootstrap",
        name="RL bootstrap/warmup (08:00 KST)",
        misfire_grace_time=60,
        replace_existing=True,
    )

    scheduler.add_job(
        _locked_job("predictor_warmup", _run_predictor_warmup),
        CronTrigger(hour=8, minute=5, day_of_week="0-4", timezone=str(KST)),
        id="predictor_warmup",
        name="A/B Predictor warmup (08:05 KST)",
        misfire_grace_time=10,
        replace_existing=True,
    )

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

    # ── 잡 등록: 장 중 ─────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("index_collection", _run_index_if_open),
        "interval",
        seconds=30,
        id="index_collection",
        name="Index collection every 30s",
        misfire_grace_time=5,
        replace_existing=True,
    )

    # ── 잡 등록: 장 후 ─────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("rl_retrain", _run_rl_retrain),
        CronTrigger(hour=16, minute=0, day_of_week="0-4", timezone=str(KST)),
        id="rl_retrain",
        name="RL retrain all (16:00 KST)",
        misfire_grace_time=60,
        replace_existing=True,
    )

    scheduler.add_job(
        _locked_job("blend_weight_adjust", _run_blend_weight_adjust),
        CronTrigger(hour=16, minute=30, day_of_week="0-4", timezone=str(KST)),
        id="blend_weight_adjust",
        name="Blend weight dynamic adjust (16:30 KST)",
        misfire_grace_time=30,
        replace_existing=True,
    )

    scheduler.start()
    job_count = len(scheduler.get_jobs())
    logger.info("✅ Unified scheduler started (%d jobs registered)", job_count)

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
