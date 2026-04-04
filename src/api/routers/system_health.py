"""
src/api/routers/system_health.py — 시스템 헬스 모니터링 라우터
"""

import time
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.utils.db_client import fetch, fetchrow, fetchval
from src.utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


class ServiceStatus(BaseModel):
    name: str
    status: str  # "ok" | "error" | "degraded"
    latency_ms: Optional[float] = None
    details: Optional[dict[str, Any]] = None


class AgentSummary(BaseModel):
    total: int
    alive: int
    dead: int
    degraded: int


class SystemHealthOverview(BaseModel):
    overall_status: str
    services: list[ServiceStatus]
    agent_summary: AgentSummary
    last_orchestrator_cycle: Optional[str] = None
    uptime_seconds: Optional[int] = None


class SystemMetricsResponse(BaseModel):
    error_count_24h: int
    total_heartbeats_24h: int
    active_agents: int
    db_table_count: int
    recent_errors: list[dict[str, Any]]


@router.get("/overview", response_model=SystemHealthOverview)
async def get_health_overview(
    _: Annotated[dict, Depends(get_current_user)],
) -> SystemHealthOverview:
    """종합 시스템 헬스 상태를 반환합니다."""
    import asyncio

    services: list[ServiceStatus] = []

    # DB check
    db_status = "ok"
    db_latency = None
    try:
        t0 = time.monotonic()
        await fetchval("SELECT 1")
        db_latency = round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        db_status = "error"
        logger.warning("DB 헬스체크 실패: %s", e)
    services.append(ServiceStatus(name="PostgreSQL", status=db_status, latency_ms=db_latency))

    # Redis check
    redis_status = "ok"
    redis_latency = None
    try:
        from src.utils.redis_client import get_redis

        t0 = time.monotonic()
        redis = await get_redis()
        await redis.ping()
        redis_latency = round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        redis_status = "error"
        logger.warning("Redis 헬스체크 실패: %s", e)
    services.append(ServiceStatus(name="Redis", status=redis_status, latency_ms=redis_latency))

    # S3 check
    s3_status = "ok"
    s3_latency = None
    try:
        from src.utils.config import get_settings
        from src.utils.s3_client import _get_s3_client

        settings = get_settings()
        client = _get_s3_client()
        t0 = time.monotonic()
        await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket_name)
        s3_latency = round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        s3_status = "error"
        logger.warning("S3 헬스체크 실패: %s", e)
    services.append(ServiceStatus(name="S3/MinIO", status=s3_status, latency_ms=s3_latency))

    # KIS API check
    kis_status = "ok"
    try:
        from src.utils.config import get_settings as _get_settings
        from src.services.kis_session import has_kis_credentials

        _settings = _get_settings()
        if not has_kis_credentials(_settings, "paper"):
            kis_status = "error"
    except Exception:
        kis_status = "error"
    services.append(ServiceStatus(
        name="KIS API",
        status=kis_status,
        latency_ms=None,
        details={"message": "KIS_PAPER_APP_KEY 미설정" if kis_status == "error" else "정상"},
    ))

    # Agent summary
    from src.utils.redis_client import check_heartbeat

    agent_ids = [
        "collector_agent",
        "predictor_1",
        "predictor_2",
        "predictor_3",
        "predictor_4",
        "predictor_5",
        "portfolio_manager_agent",
        "notifier_agent",
        "orchestrator_agent",
    ]
    alive_count = 0
    for aid in agent_ids:
        is_alive = await check_heartbeat(aid)
        if is_alive:
            alive_count += 1
    dead_count = len(agent_ids) - alive_count

    # Last orchestrator cycle
    last_cycle_row = await fetchrow(
        """
        SELECT to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS recorded_at
        FROM agent_heartbeats
        WHERE agent_id = 'orchestrator_agent'
        ORDER BY recorded_at DESC
        LIMIT 1
        """
    )
    last_cycle = last_cycle_row["recorded_at"] if last_cycle_row else None

    overall = "healthy"
    if any(s.status == "error" for s in services):
        overall = "degraded"
    if all(s.status == "error" for s in services):
        overall = "critical"

    return SystemHealthOverview(
        overall_status=overall,
        services=services,
        agent_summary=AgentSummary(
            total=len(agent_ids),
            alive=alive_count,
            dead=dead_count,
            degraded=0,
        ),
        last_orchestrator_cycle=last_cycle,
    )


@router.get("/metrics", response_model=SystemMetricsResponse)
async def get_system_metrics(
    _: Annotated[dict, Depends(get_current_user)],
) -> SystemMetricsResponse:
    """최근 24시간 시스템 메트릭을 반환합니다."""
    error_row = await fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status IN ('error', 'dead')) AS error_count,
            COUNT(*) AS total_count
        FROM agent_heartbeats
        WHERE recorded_at >= NOW() - INTERVAL '24 hours'
        """
    )
    error_count = int(error_row["error_count"] or 0) if error_row else 0
    total_hb = int(error_row["total_count"] or 0) if error_row else 0

    active_row = await fetchrow(
        """
        SELECT COUNT(DISTINCT agent_id) AS cnt
        FROM agent_heartbeats
        WHERE recorded_at >= NOW() - INTERVAL '5 minutes'
        """
    )
    active_agents = int(active_row["cnt"] or 0) if active_row else 0

    table_count_row = await fetchrow(
        "SELECT COUNT(*) AS cnt FROM information_schema.tables WHERE table_schema = 'public'"
    )
    db_table_count = int(table_count_row["cnt"] or 0) if table_count_row else 0

    recent_errors = await fetch(
        """
        SELECT agent_id, status, last_action,
               to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS recorded_at
        FROM agent_heartbeats
        WHERE status IN ('error', 'dead')
          AND recorded_at >= NOW() - INTERVAL '24 hours'
        ORDER BY recorded_at DESC
        LIMIT 20
        """
    )

    return SystemMetricsResponse(
        error_count_24h=error_count,
        total_heartbeats_24h=total_hb,
        active_agents=active_agents,
        db_table_count=db_table_count,
        recent_errors=[dict(r) for r in recent_errors],
    )
