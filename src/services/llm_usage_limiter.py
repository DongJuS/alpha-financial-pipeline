"""
src/services/llm_usage_limiter.py — provider별 일일 LLM 사용량 제한
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.redis_client import KEY_LLM_PROVIDER_DAILY_USAGE, get_redis

logger = get_logger(__name__)

_PROVIDER_LABELS = {
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
}

_RESERVE_USAGE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', key) or '0')
if current >= limit then
  return {0, current}
end
current = redis.call('INCR', key)
if current == 1 then
  redis.call('EXPIRE', key, ttl)
end
return {1, current}
"""


def usage_window(*, timezone_name: str, now: datetime | None = None) -> tuple[str, int]:
    tz = ZoneInfo(timezone_name)
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    next_midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ttl_seconds = max(1, int((next_midnight - current).total_seconds()))
    return current.date().isoformat(), ttl_seconds


async def reserve_provider_call(provider: str, *, limit: int | None = None) -> tuple[int, int]:
    settings = get_settings()
    provider_key = provider.strip().lower()
    resolved_limit = limit if limit is not None else settings.llm_daily_provider_limit
    date_key, ttl_seconds = usage_window(timezone_name=settings.llm_usage_timezone)
    redis = await get_redis()
    usage_key = KEY_LLM_PROVIDER_DAILY_USAGE.format(provider=provider_key, date=date_key)

    allowed, count = await redis.eval(
        _RESERVE_USAGE_SCRIPT,
        1,
        usage_key,
        resolved_limit,
        ttl_seconds,
    )
    count = int(count)

    if int(allowed) != 1:
        label = _PROVIDER_LABELS.get(provider_key, provider_key.upper())
        raise RuntimeError(
            f"{label} 일일 사용 한도({resolved_limit}회)에 도달했습니다. "
            f"오늘({date_key})은 더 이상 호출하지 않습니다."
        )

    remaining = resolved_limit - count
    if remaining in {5, 1, 0}:
        label = _PROVIDER_LABELS.get(provider_key, provider_key.upper())
        logger.warning("%s 일일 사용량 %d/%d", label, count, resolved_limit)

    return count, resolved_limit
