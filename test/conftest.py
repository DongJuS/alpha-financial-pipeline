"""
test/conftest.py — pytest 공용 픽스처 및 설정

이 파일은 test/ 하위의 모든 테스트에서 사용 가능한 pytest 픽스처를 정의합니다.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
import pytest
from dotenv import load_dotenv

# 프로젝트 루트 로드
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# 필수 환경변수 기본값 주입 (.env 없이도 테스트 가능)
_TEST_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql://alpha_user:alpha_pass@localhost:5432/alpha_db",
    "JWT_SECRET": "test-secret-for-pytest",
    "REDIS_URL": "redis://localhost:6379/0",
    "KIS_IS_PAPER_TRADING": "true",
}
for key, val in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(key, val)

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
    # 비동기 테스트 활성화
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
# 이벤트 루프 설정
# ────────────────────────────────────────────────────────────────────────────
# pytest-asyncio 0.23+ 에서는 event_loop fixture 직접 정의 대신
# pytest.ini의 asyncio_default_fixture_loop_scope = "session" 사용


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
def _clear_settings_cache():
    """테스트 간 Settings 캐시 오염을 방지합니다."""
    try:
        from src.utils.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass
    yield
    try:
        from src.utils.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clear_ticker_cache():
    """테스트 간 ticker 정규화 캐시 오염을 방지합니다."""
    try:
        from src.utils.ticker import clear_cache
        clear_cache()
    except Exception:
        pass
    yield
    try:
        from src.utils.ticker import clear_cache
        clear_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _mark_integration_tests(request):
    """
    DB나 Redis를 사용하는 테스트를 자동으로 'integration'으로 마킹합니다.
    """
    if "db_conn" in request.fixturenames or "redis_url" in request.fixturenames:
        request.node.add_marker(pytest.mark.integration)


# ────────────────────────────────────────────────────────────────────────────
# Mock DB 픽스처 (Agent 4 추가 — asyncpg mock)
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db_pool():
    """asyncpg pool mock — 실제 DB 없이 쿼리 함수 테스트에 사용.

    사용법:
        async def test_something(mock_db_pool):
            mock_db_pool.fetch_results = [{"id": 1, "name": "test"}]
            # ... 테스트 코드 ...
    """
    from unittest.mock import AsyncMock

    pool = AsyncMock()
    conn = AsyncMock()

    # 기본 반환값 설정
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.executemany = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)

    # context manager 패턴: async with pool.acquire() as conn
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    pool._mock_conn = conn
    return pool


@pytest.fixture
def mock_db_client(mock_db_pool, monkeypatch):
    """src.utils.db_client의 get_pool을 mock_db_pool로 대체.

    이 픽스처를 사용하면 queries.py 함수들이 실제 DB 대신
    mock_db_pool을 통해 실행됩니다.
    """

    async def _mock_get_pool():
        return mock_db_pool

    monkeypatch.setattr("src.utils.db_client.get_pool", _mock_get_pool)
    monkeypatch.setattr("src.utils.db_client._pool", mock_db_pool)
    return mock_db_pool


# ────────────────────────────────────────────────────────────────────────────
# Mock Redis 픽스처 (Agent 4 추가)
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """redis.asyncio.Redis mock — 실제 Redis 없이 테스트에 사용.

    사용법:
        async def test_something(mock_redis):
            mock_redis.get.return_value = "cached_value"
            # ... 테스트 코드 ...
    """
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=0)
    redis.expire = AsyncMock(return_value=True)
    redis.hset = AsyncMock(return_value=1)
    redis.hgetall = AsyncMock(return_value={})
    redis.publish = AsyncMock(return_value=1)
    redis.lpush = AsyncMock(return_value=1)
    redis.ltrim = AsyncMock(return_value=True)
    redis.pipeline.return_value = AsyncMock()
    redis.pipeline.return_value.lpush = AsyncMock()
    redis.pipeline.return_value.ltrim = AsyncMock()
    redis.pipeline.return_value.execute = AsyncMock(return_value=[1, True])
    redis.eval = AsyncMock(return_value=1)
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def mock_redis_client(mock_redis, monkeypatch):
    """src.utils.redis_client의 get_redis를 mock_redis로 대체.

    이 픽스처를 사용하면 redis_client 모듈의 함수들이
    실제 Redis 대신 mock을 사용합니다.
    """

    async def _mock_get_redis():
        return mock_redis

    monkeypatch.setattr("src.utils.redis_client.get_redis", _mock_get_redis)
    monkeypatch.setattr("src.utils.redis_client._redis_client", mock_redis)
    return mock_redis


# ────────────────────────────────────────────────────────────────────────────
# Mock S3 픽스처 (Agent 4 추가)
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_s3_client():
    """boto3 S3 client mock — 실제 S3/MinIO 없이 테스트에 사용.

    사용법:
        async def test_something(mock_s3_client):
            mock_s3_client.stored_objects["key"] = b"data"
            # ... 테스트 코드 ...
    """
    from unittest.mock import MagicMock

    client = MagicMock()
    client.stored_objects = {}  # key -> bytes 저장소

    def _upload_fileobj(fileobj, bucket, key, ExtraArgs=None):
        client.stored_objects[f"{bucket}/{key}"] = fileobj.read()

    def _download_fileobj(bucket, key, fileobj):
        full_key = f"{bucket}/{key}"
        if full_key in client.stored_objects:
            fileobj.write(client.stored_objects[full_key])
        else:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "GetObject",
            )

    def _head_bucket(Bucket):
        pass  # 버킷 존재 가정

    def _head_object(Bucket, Key):
        full_key = f"{Bucket}/{Key}"
        if full_key not in client.stored_objects:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )

    client.upload_fileobj = MagicMock(side_effect=_upload_fileobj)
    client.download_fileobj = MagicMock(side_effect=_download_fileobj)
    client.head_bucket = MagicMock(side_effect=_head_bucket)
    client.head_object = MagicMock(side_effect=_head_object)

    return client
