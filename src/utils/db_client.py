"""
src/utils/db_client.py — asyncpg 연결 풀 관리

사용법:
    from src.utils.db_client import get_pool

    async def handler():
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM ohlcv_daily LIMIT 10")
"""

import asyncpg
from typing import Optional
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """asyncpg 연결 풀 싱글턴을 반환합니다."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=30,  # QA: 5 Predictor + Collector + Orchestrator + PM + API 동시 사용 대비
            command_timeout=30,
        )
        logger.info("PostgreSQL 연결 풀 생성 완료 (max_size=30)")
    return _pool


async def close_pool() -> None:
    """앱 종료 시 연결 풀을 닫습니다."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL 연결 풀 종료")


async def execute(query: str, *args: object) -> str:
    """단일 DML 쿼리를 실행합니다."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def executemany(query: str, args_list: list[tuple], *, chunk_size: int = 5000) -> None:
    """배치 DML 쿼리를 실행합니다.

    asyncpg의 executemany는 내부적으로 prepared statement + pipeline protocol을
    사용하여 네트워크 왕복을 최소화합니다.

    Args:
        query: 파라미터 플레이스홀더($1, $2, ...)가 포함된 SQL.
        args_list: 각 행에 대응하는 파라미터 튜플 리스트.
        chunk_size: 한 번에 전송할 최대 행 수 (기본 5,000건).
                    PostgreSQL 메모리 스파이크를 방지합니다.
    """
    if not args_list:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        for i in range(0, len(args_list), chunk_size):
            chunk = args_list[i : i + chunk_size]
            await conn.executemany(query, chunk)


async def fetch(query: str, *args: object) -> list[asyncpg.Record]:
    """SELECT 쿼리를 실행하고 결과 행 목록을 반환합니다."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: object) -> Optional[asyncpg.Record]:
    """SELECT 쿼리를 실행하고 첫 번째 행을 반환합니다."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args: object) -> object:
    """스칼라 값 하나를 반환합니다."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)
