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
