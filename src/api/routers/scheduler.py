"""
src/api/routers/scheduler.py — 스케줄러 모니터링 API

GET /api/v1/scheduler/status  — 잡 목록, 다음 실행 시간, 실행 이력
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from src.schedulers.unified_scheduler import get_scheduler_status
from src.utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


class JobInfo(BaseModel):
    id: str
    name: str
    next_run: Optional[str] = None
    trigger: str
    recent_history: list[dict[str, Any]] = []


class SchedulerStatusResponse(BaseModel):
    running: bool
    job_count: int = 0
    jobs: list[JobInfo] = []


async def _get_job_history(job_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Redis에서 잡 실행 이력을 조회합니다."""
    try:
        from src.schedulers.job_wrapper import KEY_JOB_HISTORY
        from src.utils.redis_client import get_redis

        redis = await get_redis()
        key = KEY_JOB_HISTORY.format(job_id=job_id)
        raw = await redis.lrange(key, 0, limit - 1)
        return [json.loads(item) for item in raw]
    except Exception as exc:
        logger.debug("잡 이력 조회 실패 (비필수): %s", exc)
        return []


@router.get(
    "/status",
    response_model=SchedulerStatusResponse,
    summary="스케줄러 상태 조회",
    description="통합 스케줄러의 실행 상태, 등록된 잡 목록, 다음 실행 시간, 최근 실행 이력을 반환합니다.",
)
async def get_scheduler_status_endpoint() -> SchedulerStatusResponse:
    status = get_scheduler_status()

    if not status["running"]:
        return SchedulerStatusResponse(running=False)

    jobs: list[JobInfo] = []
    for job_data in status["jobs"]:
        history = await _get_job_history(job_data["id"])
        jobs.append(
            JobInfo(
                id=job_data["id"],
                name=job_data["name"],
                next_run=job_data["next_run"],
                trigger=job_data["trigger"],
                recent_history=history,
            )
        )

    return SchedulerStatusResponse(
        running=True,
        job_count=status["job_count"],
        jobs=jobs,
    )
