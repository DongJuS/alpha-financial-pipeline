"""
src/utils/db_client.py — asyncpg 연결 풀 관리

사용법:
    from src.utils.db_client import get_pool

    async def handler():
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM market_data LIMIT 10")
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
            max_size=20,
            command_timeout=30,
        )
        logger.info("PostgreSQL 연결 풀 생성 완료")
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
