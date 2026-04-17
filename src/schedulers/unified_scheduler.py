"""
src/schedulers/unified_scheduler.py — 통합 스케줄러

분산된 4개 AsyncIOScheduler를 단일 인스턴스로 통합합니다.
- job_wrapper.py: 재시도 + 실행 이력 기록
- distributed_lock.py: 중복 실행 방지 (Redis NX 락)

등록된 잡:
    [장 전]
    rl_bootstrap        08:00 KST  RL 부트스트랩 (활성 정책 없으면 학습, 있으면 워밍업)
    predictor_warmup    08:05 KST  A/B Predictor LLM 클라이언트 워밍업
    krx_stock_master_daily  08:10 KST  KrxStockMasterCollector
    macro_daily         08:20 KST  MacroCollector
    collector_daily     08:30 KST  CollectorAgent
    index_warmup        08:55 KST  IndexCollector (워밍업)

    [장 중]
    index_collection      30초 인터벌  IndexCollector (장중)
    kis_token_health    매시 정각 (09~15시, 평일)  KIS OAuth 토큰 유효성 검증

    [상시]
    llm_auth_health       1분 인터벌  LLM provider 인증 상태 점검

    [장 후]
    s3_tick_flush       15:40 KST  DB→S3 틱 데이터 일괄 flush (hour 파티셔닝)
    minute_aggregation  15:50 KST  tick_data→ohlcv_minute 1분봉 배치 집계
    rl_retrain          16:00 KST  RL 전략 재학습
    blend_weight_adjust 16:30 KST  블렌딩 가중치 동적 조정

    [월간]
    minute_partition_mgmt  매월 1일 00:05 KST  파티션 관리 + S3 아카이브
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
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
    "rl_bootstrap": 3600,         # 60분 (멀티 티커 학습 포함 가능)
    "predictor_warmup": 60,      # 1분 (모듈 캐싱 + 가용성 확인)
    "krx_stock_master_daily": 300,   # 5분
    "macro_daily": 300,          # 5분
    "collector_daily": 600,      # 10분
    "index_warmup": 60,          # 1분
    "index_collection": 25,      # 30초 인터벌보다 짧게
    "kis_token_health": 30,      # 30초 (토큰 검증 API 호출)
    # 장 후
    "s3_tick_flush": 600,        # 10분 (DB→S3 일괄 flush)
    "minute_aggregation": 300,   # 5분 (tick→ohlcv_minute 집계)
    "rl_retrain": 3600,          # 60분 (멀티 티커 학습)
    "blend_weight_adjust": 120,  # 2분
    # 월간
    "minute_partition_mgmt": 600,  # 10분 (S3 아카이브 포함)
    # 상시
    "llm_auth_health": 30,  # 30초
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


async def check_llm_auth_health() -> dict[str, str]:
    """LLM provider 인증 상태를 점검하고 상태 변경 시 알림을 보낸다.

    체크 대상:
    1. Claude CLI: cli_bridge.is_cli_available() + 환경변수/API key
    2. Codex CLI: ~/.codex/auth.json 존재 + access_token 유효
    3. Gemini ADC: gemini_oauth_available() 성공 여부

    Returns:
        현재 provider별 인증 상태 dict (예: {"claude": "cli_ok", ...})
    """
    import json as _json
    import os

    from src.utils.redis_client import get_redis as _get_redis
    from src.utils.secret_validation import is_placeholder_secret

    redis = await _get_redis()
    health_key = "llm:auth:health"
    prev_raw = await redis.get(health_key)
    prev_status: dict[str, str] = {}
    if prev_raw:
        try:
            prev_status = _json.loads(prev_raw)
        except Exception:
            pass

    current_status: dict[str, str] = {}

    # 1. Claude CLI 체크
    try:
        from src.llm.cli_bridge import build_cli_command, is_cli_available
        from src.utils.config import get_settings as _get_settings

        _s = _get_settings()
        cli_cmd = build_cli_command(_s.anthropic_cli_command, model="claude-3-5-sonnet-latest")
        has_cli = bool(cli_cmd) and is_cli_available(cli_cmd)
        has_oauth = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
        has_api_key = bool(_s.anthropic_api_key) and not is_placeholder_secret(
            _s.anthropic_api_key
        )

        if has_cli:
            current_status["claude"] = "cli_ok"
        elif has_oauth:
            current_status["claude"] = "oauth_token_ok"
        elif has_api_key:
            current_status["claude"] = "api_key_only"
        else:
            current_status["claude"] = "unavailable"
    except Exception as exc:
        current_status["claude"] = f"error:{exc}"

    # 2. Codex CLI 체크
    try:
        from src.llm.gpt_client import load_codex_auth_status
        from src.utils.config import get_settings as _get_settings

        _s = _get_settings()
        auth = load_codex_auth_status()
        has_codex = bool(auth["has_access_token"] and auth["has_refresh_token"])
        has_api_key = bool(_s.openai_api_key) and not is_placeholder_secret(
            _s.openai_api_key
        )

        if has_codex:
            current_status["codex"] = "cli_ok"
        elif has_api_key:
            current_status["codex"] = "api_key_only"
        else:
            current_status["codex"] = "unavailable"
    except Exception as exc:
        current_status["codex"] = f"error:{exc}"

    # 3. Gemini ADC 체크
    try:
        from src.llm.gemini_client import gemini_oauth_available

        if gemini_oauth_available():
            current_status["gemini"] = "oauth_ok"
        else:
            current_status["gemini"] = "unavailable"
    except Exception as exc:
        current_status["gemini"] = f"error:{exc}"

    # Redis에 현재 상태 저장 (TTL 5분 — 2번 연속 실패하면 자동 만료)
    await redis.set(health_key, _json.dumps(current_status), ex=300)

    # 상태 변경 감지 → 알림
    changed_providers: list[str] = []
    for provider in ("claude", "codex", "gemini"):
        prev = prev_status.get(provider, "unknown")
        curr = current_status.get(provider, "unknown")
        if prev != curr:
            changed_providers.append(provider)
            logger.warning(
                "LLM auth 상태 변경: %s %s → %s",
                provider,
                prev,
                curr,
            )

    if changed_providers:
        try:
            from src.agents.notifier import NotifierAgent

            notifier = NotifierAgent()
            lines = ["LLM 인증 상태 변경"]
            for p in changed_providers:
                prev = prev_status.get(p, "unknown")
                curr = current_status.get(p, "unknown")
                lines.append(f"- {p}: {prev} -> {curr}")
            await notifier.send("llm_auth_health", "\n".join(lines))
        except Exception as exc:
            logger.warning("LLM auth health 알림 전송 실패: %s", exc)
    else:
        logger.debug("LLM auth health: 변경 없음 %s", current_status)

    return current_status


def _extract_job_error_payload(
    event: JobExecutionEvent,
    scheduler: AsyncIOScheduler,
) -> dict[str, str]:
    """JobExecutionEvent에서 알림에 필요한 필드를 추출한다. (테스트 가능하도록 분리)"""
    job_id = event.job_id or "unknown"
    job = scheduler.get_job(job_id) if event.job_id else None
    job_name = job.name if job else job_id
    exc = event.exception
    exc_msg = f"{type(exc).__name__}: {exc}" if exc else "unknown error"

    tb_excerpt = ""
    if event.traceback:
        tb_lines = str(event.traceback).strip().split("\n")[-10:]
        tb_excerpt = "\n".join(tb_lines)

    return {
        "job_id": job_id,
        "job_name": job_name,
        "exception": exc_msg,
        "traceback_excerpt": tb_excerpt,
    }


def _make_job_error_listener(scheduler: AsyncIOScheduler):
    """EVENT_JOB_ERROR 콜백을 생성한다. (module-level: 테스트 가능)"""
    import asyncio

    def _on_job_error(event: JobExecutionEvent) -> None:
        payload = _extract_job_error_payload(event, scheduler)
        logger.error(
            "스케줄러 잡 실패: job_id=%s name=%s exc=%s",
            payload["job_id"], payload["job_name"], payload["exception"],
        )
        try:
            from src.agents.notifier import NotifierAgent

            async def _notify() -> None:
                try:
                    await NotifierAgent().send_scheduler_error_alert(**payload)
                except Exception as notify_exc:
                    logger.warning("스케줄러 에러 알림 발송 실패: %s", notify_exc)

            try:
                asyncio.get_running_loop().create_task(_notify())
            except RuntimeError:
                logger.debug("이벤트 루프 없음 — 스케줄러 에러 알림 스킵")
        except Exception as exc:
            logger.warning("스케줄러 에러 알림 구성 실패: %s", exc)

    return _on_job_error


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
    from src.agents.krx_stock_master_collector import KrxStockMasterCollector
    from src.utils.market_hours import is_market_open_now

    krx_stock_master = KrxStockMasterCollector()
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

        # ── DB 에서 활성 정책 + RL 학습 대상 종목 조회 ──
        try:
            active_map = await store.list_active_policies()
        except Exception as exc:
            logger.warning("RL bootstrap: DB 조회 실패 — %s", exc)
            return

        try:
            from src.db.queries import list_rl_target_tickers
            all_tickers = await list_rl_target_tickers()
        except Exception as exc:
            logger.warning("RL bootstrap: rl_targets 조회 실패 — %s", exc)
            return

        if not all_tickers:
            logger.info("RL 부트스트랩: rl_targets에 등록된 종목 없음 — 스킵")
            return

        logger.info(
            "RL bootstrap: %d target tickers from rl_targets, %d with active policies",
            len(all_tickers),
            len(active_map),
        )

        # 활성 정책 있는 티커 → 워밍업 (로드·검증)
        warmed = 0
        for ticker, policy_id in active_map.items():
            try:
                await store.load_policy(policy_id, ticker)
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
        """A/B 전략 LLM 클라이언트를 사전 초기화한다.

        목적:
        - Gemini OAuth 자격증명 캐싱 (모듈 레벨, 이후 재사용)
        - Claude SDK/CLI 가용성 확인
        - 무거운 import 선행 로드 (google.generativeai 등)
        인스턴스 자체는 버려지지만, 위 모듈 레벨 상태가 캐싱됨.
        """
        providers_ok: dict[str, bool] = {}

        # Gemini OAuth 캐싱
        try:
            from src.llm.gemini_client import load_gemini_oauth_credentials

            creds, _ = load_gemini_oauth_credentials()
            providers_ok["gemini"] = creds is not None
        except Exception as exc:
            providers_ok["gemini"] = False
            logger.warning("Predictor 워밍업: Gemini OAuth 실패 — %s", exc)

        # Claude SDK 가용성
        try:
            from src.llm.claude_client import ClaudeClient

            client = ClaudeClient()
            providers_ok["claude"] = client.is_configured
        except Exception as exc:
            providers_ok["claude"] = False
            logger.warning("Predictor 워밍업: Claude 초기화 실패 — %s", exc)

        # GPT 가용성
        try:
            from src.llm.gpt_client import GPTClient

            gpt = GPTClient()
            providers_ok["gpt"] = gpt.is_configured
        except Exception:
            providers_ok["gpt"] = False

        available = [k for k, v in providers_ok.items() if v]
        logger.info("Predictor 워밍업 완료: %s 사용 가능", available or "없음")

    # -- 기존 데이터 수집 잡 --
    async def _run_krx_stock_master() -> None:
        await krx_stock_master.collect_krx_stock_master(include_etf=True)

    async def _run_macro() -> None:
        await macro.collect_all()

    async def _run_collector() -> None:
        import os

        from src.constants import DEFAULT_COLLECTOR_DAILY_LIMIT

        limit = int(os.getenv("COLLECTOR_DAILY_LIMIT", str(DEFAULT_COLLECTOR_DAILY_LIMIT)))
        await collector.collect_daily_bars(tickers=None, lookback_days=120, limit=limit)

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
        logger.info("RL retrain: %d target tickers", len(outcomes))
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
        _locked_job("krx_stock_master_daily", _run_krx_stock_master),
        CronTrigger(hour=8, minute=10, day_of_week="0-4", timezone=str(KST)),
        id="krx_stock_master_daily",
        name="KrxStockMasterCollector daily (08:10 KST)",
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

    # -- 장 중: KIS 토큰 health 체크 (매시 정각, 09~15시) --
    async def _run_kis_token_health() -> None:
        """KIS OAuth 토큰 유효성을 검증하고, 만료/실패 시 재발급 + 알림."""
        from src.services.kis_session import get_stored_kis_token, issue_kis_token
        from src.utils.config import get_settings as _get_settings, has_kis_credentials
        from src.utils.redis_client import get_redis as _get_redis

        _settings = _get_settings()
        scope = "paper" if _settings.kis_is_paper_trading else "real"

        if not has_kis_credentials(_settings, scope):
            logger.warning("KIS health: %s 인증 정보 미설정 — 스킵", scope)
            return

        redis = await _get_redis()
        token_key = f"kis:oauth_token:{scope}"
        ttl = await redis.ttl(token_key)
        token = await get_stored_kis_token(scope)

        status = "ok"
        detail = ""

        if not token:
            try:
                await issue_kis_token(settings=_settings, account_scope=scope)
                status = "recovered"
                detail = "토큰 없음 → 재발급 성공"
            except Exception as exc:
                status = "error"
                detail = f"토큰 재발급 실패: {exc}"
        elif ttl < 3600:
            try:
                await issue_kis_token(settings=_settings, account_scope=scope)
                status = "renewed"
                detail = f"TTL {ttl}초 → 갱신 완료"
            except Exception as exc:
                status = "warning"
                detail = f"TTL {ttl}초, 갱신 실패: {exc}"
        else:
            detail = f"TTL {ttl // 3600}h {(ttl % 3600) // 60}m"

        logger.info("KIS health [%s]: %s — %s", scope, status, detail)

        if status in ("error", "warning"):
            try:
                from src.agents.notifier import NotifierAgent

                notifier = NotifierAgent()
                await notifier.send(
                    "kis_health",
                    f"⚠️ KIS 토큰 이상\n상태: {status}\n스코프: {scope}\n{detail}",
                )
            except Exception as exc:
                logger.warning("KIS health 알림 전송 실패: %s", exc)

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

    scheduler.add_job(
        _locked_job("kis_token_health", _run_kis_token_health),
        CronTrigger(hour="9-15", minute=0, day_of_week="0-4", timezone=str(KST)),
        id="kis_token_health",
        name="KIS token health check (hourly 09-15 KST)",
        misfire_grace_time=60,
        replace_existing=True,
    )

    # ── 잡 등록: 상시 ─────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("llm_auth_health", check_llm_auth_health),
        "interval",
        minutes=1,
        id="llm_auth_health",
        name="LLM auth health check (every 1m)",
        misfire_grace_time=30,
        replace_existing=True,
    )

    # -- 장 후: DB→S3 틱 일괄 flush (15:40 KST) --
    async def _run_s3_tick_flush() -> None:
        """장 종료 후 당일 틱 데이터를 DB에서 읽어 시간대별 S3 파일로 저장한다."""
        from src.services.datalake import flush_ticks_to_s3

        uris = await flush_ticks_to_s3()
        logger.info("S3 틱 flush 크론 완료: %d파일", len(uris))

    # ── 잡 등록: 장 후 ─────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("s3_tick_flush", _run_s3_tick_flush),
        CronTrigger(hour=15, minute=40, day_of_week="0-4", timezone=str(KST)),
        id="s3_tick_flush",
        name="S3 tick flush (15:40 KST)",
        misfire_grace_time=60,
        replace_existing=True,
    )

    # -- 장 후: tick_data → ohlcv_minute 1분봉 배치 집계 (15:50 KST) --
    async def _run_minute_aggregation() -> None:
        """장 종료 후 당일 00:00~익일 00:00 틱 데이터를 1분봉으로 UPSERT한다 (멱등성)."""
        from datetime import datetime as _dt, timedelta

        from src.db.queries import aggregate_ticks_to_minutes

        today = _dt.now(tz=KST).date()
        start = _dt(today.year, today.month, today.day, 0, 0, 0, tzinfo=KST)
        end = start + timedelta(days=1)
        count = await aggregate_ticks_to_minutes(start, end)
        logger.info("분봉 집계 완료: %s, %d건", today.isoformat(), count)

    scheduler.add_job(
        _locked_job("minute_aggregation", _run_minute_aggregation),
        CronTrigger(hour=15, minute=50, day_of_week="0-4", timezone=str(KST)),
        id="minute_aggregation",
        name="Minute aggregation (15:50 KST)",
        misfire_grace_time=60,
        replace_existing=True,
    )

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

    # -- 월간: 분봉 파티션 관리 (매월 1일 00:05 KST) --
    async def _run_minute_partition_mgmt() -> None:
        """매월 1일: 다음 달 파티션 생성 + 3개월 전 아카이브→DROP."""
        from datetime import datetime as _dt

        from src.utils.db_client import execute

        now = _dt.now(tz=KST)

        # 1) 다음 달 파티션 CREATE IF NOT EXISTS
        if now.month == 12:
            next_year, next_month = now.year + 1, 1
        else:
            next_year, next_month = now.year, now.month + 1

        if next_month == 12:
            after_year, after_month = next_year + 1, 1
        else:
            after_year, after_month = next_year, next_month + 1

        partition_name = f"ohlcv_minute_{next_year}_{next_month:02d}"
        start_val = f"{next_year}-{next_month:02d}-01"
        end_val = f"{after_year}-{after_month:02d}-01"

        await execute(
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF ohlcv_minute "
            f"FOR VALUES FROM ('{start_val}') TO ('{end_val}')"
        )
        logger.info(
            "파티션 생성: %s (%s ~ %s)", partition_name, start_val, end_val
        )

        # 2) 3개월 전 데이터 아카이브
        archive_month = now.month - 3
        archive_year = now.year
        if archive_month <= 0:
            archive_month += 12
            archive_year -= 1

        from src.services.datalake import archive_minute_bars, check_archive_marker

        uris = await archive_minute_bars(archive_year, archive_month)

        if not uris:
            logger.info(
                "파티션 관리: %04d-%02d 아카이브할 데이터 없음",
                archive_year,
                archive_month,
            )
            return

        # 3) 마커 확인 후 파티션 DROP
        if await check_archive_marker(archive_year, archive_month):
            old_partition = f"ohlcv_minute_{archive_year}_{archive_month:02d}"
            await execute(f"DROP TABLE IF EXISTS {old_partition}")
            logger.info(
                "파티션 DROP: %s (S3 아카이브 확인 완료)", old_partition
            )
        else:
            logger.warning(
                "파티션 DROP 스킵: %04d-%02d — S3 마커 미확인. 수동 확인 필요",
                archive_year,
                archive_month,
            )
            # Telegram 알림
            try:
                from src.agents.notifier import NotifierAgent

                notifier = NotifierAgent()
                await notifier.send(
                    "partition_mgmt",
                    "분봉 파티션 DROP 스킵\n"
                    f"{archive_year}-{archive_month:02d} S3 마커 미확인",
                )
            except Exception as exc:
                logger.warning("파티션 관리 알림 실패: %s", exc)

    # ── 잡 등록: 월간 ─────────────────────────────────────────────────────
    scheduler.add_job(
        _locked_job("minute_partition_mgmt", _run_minute_partition_mgmt),
        CronTrigger(day=1, hour=0, minute=5, timezone=str(KST)),
        id="minute_partition_mgmt",
        name="Minute partition management (1st 00:05 KST)",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # 잡 실패 이벤트 → Telegram 알림 훅
    scheduler.add_listener(_make_job_error_listener(scheduler), EVENT_JOB_ERROR)

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
