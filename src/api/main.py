"""
src/api/main.py — FastAPI 애플리케이션 진입점

실행 방법:
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import agents, audit, auth, datalake, feedback, market, marketplace, models, notifications, portfolio, rl, strategy, system_health
from src.schedulers.index_scheduler import start_index_scheduler, stop_index_scheduler
from src.utils.config import get_settings
from src.utils.db_client import close_pool, get_pool
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import close_redis, get_redis

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """앱 시작/종료 시 DB·Redis 연결 끝을 초기화/해제합니다."""
    logger.info("🚀 Alpha Trading System 시작 중...")
    await get_pool()
    await get_redis()
    logger.info("✅ DB·Redis 연결 완료")

    # S3/MinIO 버킷 자동 확인
    try:
        from src.utils.s3_client import ensure_bucket
        await ensure_bucket()
        logger.info("✅ S3 Data Lake 버킷 준비 완료")
    except Exception as e:
        logger.warning("⚠️ S3 버킷 초기화 실패 (비필수): %s", e)

    # Index scheduler 시작
    await start_index_scheduler()

    yield

    # Index scheduler 종료
    await stop_index_scheduler()

    logger.info("🔴 Alpha Trading System 종료 중...")
    await close_pool()
    await close_redis()
    logger.info("연결 종료 완료")


app = FastAPI(
    title="Alpha Trading System API",
    description="KOSPI/KOSDAQ 멀티 에이전트 AI 트레이딩 시스템",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ────────────────────────────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 라우터 등록 ────────────────────────────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX, tags=["auth"])
app.include_router(market.router, prefix=f"{API_PREFIX}/market", tags=["market"])
app.include_router(agents.router, prefix=f"{API_PREFIX}/agents", tags=["agents"])
app.include_router(strategy.router, prefix=f"{API_PREFIX}/strategy", tags=["strategy"])
app.include_router(portfolio.router, prefix=f"{API_PREFIX}/portfolio", tags=["portfolio"])
app.include_router(notifications.router, prefix=f"{API_PREFIX}/notifications", tags=["notifications"])
app.include_router(models.router, prefix=f"{API_PREFIX}/models", tags=["models"])
app.include_router(marketplace.router, prefix=f"{API_PREFIX}/marketplace", tags=["marketplace"])
app.include_router(rl.router, prefix=f"{API_PREFIX}/rl", tags=["rl"])
app.include_router(feedback.router, prefix=f"{API_PREFIX}/feedback", tags=["feedback"])
app.include_router(system_health.router, prefix=f"{API_PREFIX}/system", tags=["system"])
app.include_router(datalake.router, prefix=f"{API_PREFIX}/datalake", tags=["datalake"])
app.include_router(audit.router, prefix=f"{API_PREFIX}/audit", tags=["audit"])


# ─── 헬스 체크 ────────────────────────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """서버 및 DB·Redis 연결 상태를 반환합니다."""
    from src.utils.db_client import fetchval
    from src.utils.redis_client import get_redis as _get_redis

    db_ok = False
    redis_ok = False

    try:
        result = await fetchval("SELECT 1")
        db_ok = result == 1
    except Exception as e:
        logger.warning("DB 헬스체크 실패: %s", e)

    try:
        redis = await _get_redis()
        pong = await redis.ping()
        redis_ok = pong is True
    except Exception as e:
        logger.warning("Redis 헬스체크 실패: %s", e)

    status = "healthy" if (db_ok and redis_ok) else "degraded"

    return {
        "status": status,
        "version": "0.1.0",
        "environment": settings.app_env,
        "paper_trading": settings.kis_is_paper_trading,
        "services": {
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    }


@app.get("/", tags=["system"])
async def root() -> dict:
    return {"message": "Alpha Trading System API", "docs": "/docs"}
