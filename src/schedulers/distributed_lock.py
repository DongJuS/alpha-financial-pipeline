"""
src/schedulers/distributed_lock.py — Redis 기반 분산 락

중복 실행 방지를 위해 Redis SET NX EX 패턴으로 분산 락을 구현합니다.

사용법:
    async with DistributedLock(redis, "job:index_collection", ttl=60):
        await do_work()
"""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis

from src.utils.logging import get_logger

logger = get_logger(__name__)


class LockAcquisitionError(Exception):
    """락 획득 실패 시 발생합니다."""


class DistributedLock:
    """Redis SET NX EX 기반 분산 락."""

    def __init__(
        self,
        redis: aioredis.Redis,
        key: str,
        ttl: int = 60,
        *,
        raise_on_fail: bool = False,
    ) -> None:
        """
        Args:
            redis: aioredis 클라이언트
            key: 락 키 (예: "scheduler:lock:job_id")
            ttl: 락 만료 시간(초). 잡 최대 실행 시간보다 넉넉하게 설정.
            raise_on_fail: True면 획득 실패 시 LockAcquisitionError 발생,
                           False면 조용히 스킵 (context manager 반환값으로 확인).
        """
        self._redis = redis
        self._key = key
        self._ttl = ttl
        self._raise_on_fail = raise_on_fail
        self._token: str | None = None
        self.acquired: bool = False

    async def __aenter__(self) -> "DistributedLock":
        self._token = str(uuid.uuid4())
        result = await self._redis.set(
            self._key, self._token, nx=True, ex=self._ttl
        )
        self.acquired = result is True
        if not self.acquired:
            if self._raise_on_fail:
                raise LockAcquisitionError(
                    f"락 획득 실패 (다른 인스턴스가 실행 중): {self._key}"
                )
            logger.debug("분산 락 스킵 (이미 실행 중): %s", self._key)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[override]
        if self.acquired and self._token is not None:
            # 내가 설정한 락만 해제 (Lua 스크립트로 원자적 처리)
            script = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""
            await self._redis.eval(script, 1, self._key, self._token)  # type: ignore[call-arg]
            self.acquired = False
