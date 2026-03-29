"""
src/schedulers/job_wrapper.py — 잡 실행 래퍼 (재시도 + 이력 기록)

- 최대 3회 재시도, exponential backoff
- 각 실행 결과를 Redis 리스트에 기록 (잡별 최근 50건)
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Redis 키 패턴: 잡 실행 이력
KEY_JOB_HISTORY = "scheduler:history:{job_id}"
MAX_HISTORY = 50  # 잡별 최대 이력 보관 수


async def _record_history(
    job_id: str,
    status: str,
    duration_ms: float,
    error: str | None = None,
) -> None:
    """잡 실행 결과를 Redis에 기록합니다."""
    try:
        from src.utils.redis_client import get_redis

        redis = await get_redis()
        entry = {
            "job_id": job_id,
            "status": status,
            "duration_ms": round(duration_ms, 1),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            entry["error"] = error

        key = KEY_JOB_HISTORY.format(job_id=job_id)
        pipe = redis.pipeline()
        pipe.lpush(key, json.dumps(entry))
        pipe.ltrim(key, 0, MAX_HISTORY - 1)
        await pipe.execute()
    except Exception as exc:
        logger.debug("잡 이력 기록 실패 (비필수): %s", exc)


def with_retry(
    fn: Callable[[], Awaitable[Any]],
    job_id: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Callable[[], Awaitable[None]]:
    """
    재시도 + 이력 기록을 적용한 잡 래퍼를 반환합니다.

    Args:
        fn: 실행할 비동기 함수 (인자 없음)
        job_id: 잡 식별자 (이력 키, 락 키에 사용)
        max_retries: 최대 재시도 횟수 (초기 실행 포함 총 시도 횟수)
        base_delay: 첫 재시도 대기 시간(초). 이후 2배씩 증가.
    """

    async def _wrapped() -> None:
        attempt = 0
        last_exc: BaseException | None = None
        t_start = time.monotonic()

        while attempt < max_retries:
            attempt += 1
            try:
                await fn()
                duration_ms = (time.monotonic() - t_start) * 1000
                await _record_history(job_id, "success", duration_ms)
                return
            except Exception as exc:
                last_exc = exc
                remaining = max_retries - attempt
                if remaining > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "잡 실패 [%s] (시도 %d/%d) — %s. %.1fs 후 재시도",
                        job_id,
                        attempt,
                        max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "잡 최종 실패 [%s] (%d회 시도) — %s",
                        job_id,
                        max_retries,
                        exc,
                    )

        duration_ms = (time.monotonic() - t_start) * 1000
        await _record_history(
            job_id,
            "failed",
            duration_ms,
            error=str(last_exc) if last_exc else "unknown",
        )

    return _wrapped
