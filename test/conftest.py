"""
test/conftest.py — pytest 공용 픽스처 및 설정

이 파일은 test/ 하위의 모든 테스트에서 사용 가능한 pytest 픽스처를 정의합니다.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator, Generator

import asyncpg
import pytest
from dotenv import load_dotenv

# 프로젝트 루트 로드
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# .env 파일이 없는 환경(worktree, CI)에서도 Settings 로드가 실패하지 않도록
# 필수 환경변수가 미설정이면 더미값을 주입
_REQUIRED_DEFAULTS = {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test_db",
    "JWT_SECRET": "test-secret-for-pytest",
}
for _key, _default in _REQUIRED_DEFAULTS.items():
    if not os.environ.get(_key):
        os.environ[_key] = _default

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Pytest 설정
# ────────────────────────────────────────────────────────────────────────────

def pytest_configure(config):
    """Pytest 초기화 훅"""
    # Python 3.9에서 DeprecationWarning 방지
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


# ────────────────────────────────────────────────────────────────────────────
# 데이터베이스 픽스처
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def database_url() -> str:
    """테스트 데이터베이스 URL을 반환합니다."""
    # Docker 환경에서는 docker-compose.test.yml의 DATABASE_URL 사용
    # 로컬 개발 환경에서는 .env에서 로드 (test 접미사)
    url = os.getenv("DATABASE_URL", "")

    if not url:
        pytest.skip("DATABASE_URL 환경변수가 설정되지 않았습니다.")

    logger.info(f"테스트 DB 연결: {url.split('@')[-1] if '@' in url else url}")
    return url


@pytest.fixture(scope="session")
async def db_pool(database_url: str) -> AsyncGenerator[asyncpg.pool.Pool, None]:
    """
    세션 스코프 데이터베이스 연결 풀.

    모든 테스트에서 공유되며, 세션 종료 시 정리됩니다.
    """
    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
        command_timeout=10,
    )
    logger.info("DB 연결 풀 생성됨")

    try:
        yield pool
    finally:
        await pool.close()
        logger.info("DB 연결 풀 종료됨")


@pytest.fixture
async def db_conn(db_pool: asyncpg.pool.Pool) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    각 테스트마다 새로운 DB 연결을 제공합니다.

    자동으로 로울백되므로 다른 테스트에 영향을 주지 않습니다.
    """
    async with db_pool.acquire() as conn:
        # 트랜잭션 시작 (테스트 후 자동 롤백)
        tx = conn.transaction()
        await tx.start()

        try:
            yield conn
        finally:
            # 트랜잭션 롤백으로 데이터 정리
            await tx.rollback()


# ────────────────────────────────────────────────────────────────────────────
# Redis 픽스처
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def redis_url() -> str:
    """테스트 Redis URL을 반환합니다."""
    url = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    logger.info(f"테스트 Redis 연결: {url}")
    return url


# ────────────────────────────────────────────────────────────────────────────
# 이벤트 루프 픽스처
# ────────────────────────────────────────────────────────────────────────────

# event_loop fixture 제거됨 (pytest-asyncio 0.26에서 deprecated).
# pytest-asyncio의 auto 모드 + IsolatedAsyncioTestCase가 각자 loop를 관리.


# ────────────────────────────────────────────────────────────────────────────
# 환경변수 픽스처
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def test_env() -> dict[str, str]:
    """테스트 환경변수를 반환합니다."""
    return {
        "KIS_IS_PAPER_TRADING": "true",
        "NODE_ENV": "test",
        "ORCH_RUN_ONCE": "true",
        "ORCH_INTERVAL_SECONDS": "1",
        "ORCH_ENABLE_DAILY_REPORT": "false",
    }


# ────────────────────────────────────────────────────────────────────────────
# 마커 자동 설정
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mark_integration_tests(request):
    """
    DB나 Redis를 사용하는 테스트를 자동으로 'integration'으로 마킹합니다.
    """
    if "db_conn" in request.fixturenames or "redis_url" in request.fixturenames:
        request.node.add_marker(pytest.mark.integration)
