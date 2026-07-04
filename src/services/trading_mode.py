"""
src/services/trading_mode.py — 런타임 trading mode (paper/real) 저장 + 조회.

Redis key `system:trading_mode` 를 single source. env `KIS_IS_PAPER_TRADING`
은 초기 부트스트랩용 fallback — Redis 값이 있으면 그게 우선.

이 helper 를 KIS credential 결정 지점에서 사용하면 UI 의 토글이 즉시 반영됨.
"""

from __future__ import annotations

from typing import Literal

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_REDIS_KEY = "system:trading_mode"
Mode = Literal["paper", "real"]


async def get_current_trading_mode() -> Mode:
    """현재 활성 mode 반환. Redis 값 > env fallback."""
    try:
        redis = await get_redis()
        val = await redis.get(_REDIS_KEY)
        if val:
            v = val.decode() if isinstance(val, bytes) else str(val)
            if v in ("paper", "real"):
                return v  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("trading_mode Redis 조회 실패, env fallback: %s", exc)

    settings = get_settings()
    return "paper" if settings.kis_is_paper_trading else "real"


async def set_trading_mode(mode: Mode) -> None:
    """Redis 에 저장. 즉시 모든 pod 에서 조회 반영."""
    if mode not in ("paper", "real"):
        raise ValueError(f"invalid mode: {mode!r} — 'paper' 또는 'real'")

    redis = await get_redis()
    await redis.set(_REDIS_KEY, mode)
    logger.info("trading_mode 변경: %s", mode)


async def is_paper_trading() -> bool:
    """`settings.kis_is_paper_trading` 을 대체하는 runtime helper."""
    return (await get_current_trading_mode()) == "paper"


# ── Hard stop dry-run flag ──────────────────────────────────────
#
# Sell Strategy Phase A (docs/plans/SELL_STRATEGY_PHASES.md §3-4).
# Hard stop 트리거 조건 도달 시 실 broker.execute_order 발주를 스킵할지 결정.
# Default true — mandate 자본 보존 상 안전 default (실 매매하려면 명시적으로
# 꺼야 함). Redis 값 > env fallback 순위.

_HARD_STOP_DRY_RUN_REDIS_KEY = "system:hard_stop_dry_run"
_HARD_STOP_DRY_RUN_ENV = "HARD_STOP_LOSS_DRY_RUN"


async def is_hard_stop_dry_run() -> bool:
    """Hard stop 이 dry-run 모드인지 반환.

    Redis key `system:hard_stop_dry_run` 우선 (즉시 반영, 재기동 불필요).
    Env `HARD_STOP_LOSS_DRY_RUN` fallback. 둘 다 없으면 True (안전 default).

    True 인 값 표기: '1' | 'true' | 'yes' | 'on' (대소문자 무시).
    """
    import os

    try:
        redis = await get_redis()
        val = await redis.get(_HARD_STOP_DRY_RUN_REDIS_KEY)
        if val is not None:
            v = val.decode() if isinstance(val, bytes) else str(val)
            return v.strip().lower() in ("1", "true", "yes", "on")
    except Exception as exc:
        logger.warning("hard_stop_dry_run Redis 조회 실패, env fallback: %s", exc)

    env_val = os.environ.get(_HARD_STOP_DRY_RUN_ENV)
    if env_val is None:
        return True  # 안전 default: 미설정 = dry-run on
    return env_val.strip().lower() in ("1", "true", "yes", "on")


async def set_hard_stop_dry_run(enabled: bool) -> None:
    """Redis 에 저장. 즉시 모든 pod 에서 조회 반영."""
    redis = await get_redis()
    await redis.set(_HARD_STOP_DRY_RUN_REDIS_KEY, "true" if enabled else "false")
    logger.info("hard_stop_dry_run 변경: %s", enabled)


# ── Hard stop persistent lockout (Layer 3 다음 거래일까지) ─────────
#
# docs/plans/SELL_STRATEGY_PHASES.md §3-1 Layer 3 스펙:
#   "그날 모든 신규 주문 취소 + 다음 거래일까지 매매 lockout"
# _is_daily_loss_blocked 는 매 사이클 당일 pnl 만 체크 → 자정 지나면 자동 해제.
# 이를 보완: -3% 도달 시 Redis flag 세팅, 다음 거래일 09:00 까지 TTL.
# Flag 활성 시 hard_stop_scan 및 process_predictions 매매 skip.

_LOCKOUT_KEY_PREFIX = "hard_stop:lockout:"


async def is_hard_stop_lockout_active(account_scope: str) -> bool:
    """다음 거래일 lockout Redis flag 가 활성인지 조회.

    (docs/plans/SELL_STRATEGY_PHASES.md §3-1 · §8-8)
    True 면 매매 skip. Redis 실패 시 False (안전 기본값 아님 — Redis 장애 시
    lockout 자동 해제되지만 daily pnl 체크는 여전히 동작해서 당일 재판정 됨).
    """
    try:
        redis = await get_redis()
        val = await redis.get(f"{_LOCKOUT_KEY_PREFIX}{account_scope}")
        return val is not None
    except Exception as exc:
        logger.warning("hard_stop lockout Redis 조회 실패: %s", exc)
        return False


async def set_hard_stop_lockout(account_scope: str, until):  # type: ignore[no-untyped-def]
    """Redis 에 lockout flag 세팅. TTL 은 until (datetime, KST) 까지.

    until 이 현재보다 과거면 최소 60초 TTL 로 clamp.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    now = datetime.now(kst)
    if until.tzinfo is None:
        until = until.replace(tzinfo=kst)
    ttl_seconds = max(int((until - now).total_seconds()), 60)

    redis = await get_redis()
    await redis.set(
        f"{_LOCKOUT_KEY_PREFIX}{account_scope}",
        "true",
        ex=ttl_seconds,
    )
    logger.info(
        "hard_stop lockout 세팅: scope=%s, until=%s (ttl=%ds)",
        account_scope,
        until.isoformat(),
        ttl_seconds,
    )


async def clear_hard_stop_lockout(account_scope: str) -> None:
    """Lockout flag 즉시 해제 (긴급 오버라이드 · 테스트용)."""
    redis = await get_redis()
    await redis.delete(f"{_LOCKOUT_KEY_PREFIX}{account_scope}")
    logger.info("hard_stop lockout 해제: scope=%s", account_scope)
