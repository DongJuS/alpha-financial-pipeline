"""
src/api/main.py — FastAPI 애플리케이션 진입점

실행 방법:
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from src.api.routers import (
    agents,
    audit,
    auth,
    datalake,
    feedback,
    market,
    marketplace,
    models,
    notifications,
    portfolio,
    rl,
    scheduler,
    strategy,
    system_health,
)
from src.schedulers.unified_scheduler import start_unified_scheduler, stop_unified_scheduler
from src.utils.config import get_settings
from src.utils.db_client import close_pool, get_pool
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import close_redis, get_redis

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "version": "0.1.0",
                "environment": "development",
                "paper_trading": True,
                "services": {
                    "database": "ok",
                    "redis": "ok",
                },
                "scheduler": {"running": True, "job_count": 5},
            }
        }
    )

    status: str
    version: str
    environment: str
    paper_trading: bool
    services: dict[str, str]
    scheduler: dict[str, object] | None = None


class RootResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Alpha Trading System API",
                "docs": "/docs",
            }
        }
    )

    message: str
    docs: str


OPENAPI_TAGS = [
    {"name": "auth", "description": "JWT 로그인 및 현재 사용자 조회"},
    {"name": "strategy", "description": "Strategy A/B 시그널, 토너먼트, 토론 transcript 조회"},
    {"name": "portfolio", "description": "계좌 현황, 포지션, 주문, 스냅샷, 설정 조회"},
    {"name": "agents", "description": "에이전트 상태 및 실행 관리"},
    {"name": "market", "description": "시장 데이터 및 지표 조회"},
    {"name": "models", "description": "Strategy A/B 모델 슬롯 구성 조회"},
    {"name": "notifications", "description": "알림 조회 및 운영 메시지"},
    {"name": "marketplace", "description": "종목 마스터, 관심종목, 랭킹 등 탐색 API"},
    {"name": "rl", "description": "강화학습 전략 및 정책 조회"},
    {"name": "system-health", "description": "서비스 상태와 운영 점검 API"},
    {"name": "datalake", "description": "Data Lake 저장물 및 메타데이터 조회"},
    {"name": "audit", "description": "실거래/운영 감사 이력"},
    {"name": "feedback", "description": "전략 피드백 수집 및 조회"},
    {"name": "scheduler", "description": "통합 스케줄러 상태 및 잡 실행 이력"},
    {"name": "system", "description": "루트 및 헬스체크"},
]


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
    # 티커 마스터 캐시 워밍업
    try:
        from src.utils.db_client import fetch
        from src.utils.ticker import build_cache
        rows = await fetch("SELECT raw_code, canonical FROM ticker_master WHERE is_active = TRUE")
        build_cache([(r["raw_code"], r["canonical"]) for r in rows])
        logger.info("✅ 티커 마스터 캐시 로드 완료 (%d건)", len(rows))
    except Exception as e:
        logger.warning("⚠️ 티커 마스터 캐시 로드 실패 (비필수): %s", e)

    # 통합 스케줄러 시작 (stock_master / macro / collector / index 포함)
    await start_unified_scheduler()

    yield

    # 통합 스케줄러 종료
    await stop_unified_scheduler()

    logger.info("🔴 Alpha Trading System 종료 중...")
    await close_pool()
    await close_redis()
    logger.info("연결 종료 완료")


app = FastAPI(
    title="Alpha Trading System API",
    description=(
        "KOSPI/KOSDAQ 멀티 에이전트 AI 트레이딩 시스템 API입니다.\n\n"
        "권장 사용 순서:\n"
        "1. `/api/v1/auth/login`으로 JWT 토큰 발급\n"
        "2. Swagger `Authorize` 버튼에 토큰 입력\n"
        "3. `strategy`, `portfolio`, `agents` 태그에서 현재 상태 확인"
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={
        "defaultModelsExpandDepth": 1,
        "displayRequestDuration": True,
        "persistAuthorization": True,
        "docExpansion": "list",
    },
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
app.include_router(system_health.router, prefix=f"{API_PREFIX}/system", tags=["system-health"])
app.include_router(datalake.router, prefix=f"{API_PREFIX}/datalake", tags=["datalake"])
app.include_router(audit.router, prefix=f"{API_PREFIX}/audit", tags=["audit"])
app.include_router(feedback.router, prefix=f"{API_PREFIX}/feedback", tags=["feedback"])
app.include_router(scheduler.router, prefix=f"{API_PREFIX}/scheduler", tags=["scheduler"])


# ─── 헬스 체크 ────────────────────────────────────────────────────────────────────────────────────────
@app.get(
    "/health",
    tags=["system"],
    response_model=HealthResponse,
    summary="서비스 헬스체크",
    description="API 서버와 DB/Redis 연결 상태를 한 번에 확인합니다.",
)
async def health_check() -> HealthResponse:
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

    from src.schedulers.unified_scheduler import get_scheduler_status

    sched_status = get_scheduler_status()
    status = "healthy" if (db_ok and redis_ok) else "degraded"

    return HealthResponse(
        status=status,
        version="0.1.0",
        environment=settings.app_env,
        paper_trading=settings.kis_is_paper_trading,
        services={
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
        scheduler={
            "running": sched_status["running"],
            "job_count": sched_status.get("job_count", 0),
        },
    )


@app.get(
    "/",
    tags=["system"],
    response_model=RootResponse,
    summary="API 루트",
    description="API 루트와 Swagger 문서 진입점을 반환합니다.",
)
async def root() -> RootResponse:
    return RootResponse(message="Alpha Trading System API", docs="/docs")
