"""
src/api/routers/audit.py — 통합 감사 추적 라우터
"""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.utils.db_client import fetch, fetchrow
from src.utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


class AuditTrailItem(BaseModel):
    event_type: str
    event_time: Optional[str] = None
    agent_id: Optional[str] = None
    description: Optional[str] = None
    result: Optional[str] = None


class AuditTrailResponse(BaseModel):
    data: list[AuditTrailItem]
    total: int
    page: int
    limit: int


class AuditSummary(BaseModel):
    total_events: int
    pass_rate: Optional[float] = None
    by_type: dict[str, int]


@router.get("/trail", response_model=AuditTrailResponse)
async def get_audit_trail(
    _: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    event_type: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="시작일 YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="종료일 YYYY-MM-DD"),
) -> AuditTrailResponse:
    """통합 감사 추적 로그를 반환합니다 (거래, 운영감사, 알림 이력 통합)."""
    offset = (page - 1) * limit

    # Build WHERE conditions dynamically
    conditions = []
    params: list[Any] = []
    param_idx = 1

    if event_type:
        conditions.append(f"event_type = ${param_idx}")
        params.append(event_type)
        param_idx += 1
    if date_from:
        conditions.append(f"event_time >= ${param_idx}::timestamp")
        params.append(date_from)
        param_idx += 1
    if date_to:
        conditions.append(f"event_time <= (${param_idx}::date + INTERVAL '1 day')")
        params.append(date_to)
        param_idx += 1

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Unified query combining multiple audit sources
    base_query = f"""
        WITH unified AS (
            SELECT
                'trade' AS event_type,
                to_char(executed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_time,
                signal_source AS agent_id,
                CONCAT(side, ' ', name, ' x', quantity, ' @ ', price) AS description,
                'executed' AS result
            FROM trade_history
            UNION ALL
            SELECT
                'operational_audit' AS event_type,
                to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_time,
                executed_by AS agent_id,
                audit_type AS description,
                CASE WHEN passed THEN 'pass' ELSE 'fail' END AS result
            FROM operational_audits
            UNION ALL
            SELECT
                'notification' AS event_type,
                to_char(sent_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_time,
                event_type AS agent_id,
                message AS description,
                CASE WHEN success THEN 'success' ELSE 'fail' END AS result
            FROM notification_history
        )
        SELECT * FROM unified{where_clause}
        ORDER BY event_time DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])

    rows = await fetch(base_query, *params)

    # Count total
    count_query = f"""
        WITH unified AS (
            SELECT 'trade' AS event_type,
                   to_char(executed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_time,
                   signal_source AS agent_id,
                   '' AS description, '' AS result
            FROM trade_history
            UNION ALL
            SELECT 'operational_audit' AS event_type,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_time,
                   executed_by AS agent_id, '' AS description, '' AS result
            FROM operational_audits
            UNION ALL
            SELECT 'notification' AS event_type,
                   to_char(sent_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS event_time,
                   event_type AS agent_id, '' AS description, '' AS result
            FROM notification_history
        )
        SELECT COUNT(*) AS cnt FROM unified{where_clause}
    """
    count_params = params[:-2]  # exclude limit/offset
    count_row = await fetchrow(count_query, *count_params)
    total = int(count_row["cnt"]) if count_row else 0

    return AuditTrailResponse(
        data=[AuditTrailItem(**dict(r)) for r in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/summary", response_model=AuditSummary)
async def get_audit_summary(
    _: Annotated[dict, Depends(get_current_user)],
) -> AuditSummary:
    """감사 이벤트 요약 (총 이벤트, 통과율, 유형별 분류)을 반환합니다."""
    summary_row = await fetchrow(
        """
        WITH unified AS (
            SELECT 'trade' AS event_type, TRUE AS passed FROM trade_history
            UNION ALL
            SELECT 'operational_audit', passed FROM operational_audits
            UNION ALL
            SELECT 'notification', success FROM notification_history
        )
        SELECT
            COUNT(*) AS total_events,
            ROUND(AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END), 4) AS pass_rate
        FROM unified
        """
    )

    type_rows = await fetch(
        """
        WITH unified AS (
            SELECT 'trade' AS event_type FROM trade_history
            UNION ALL
            SELECT 'operational_audit' FROM operational_audits
            UNION ALL
            SELECT 'notification' FROM notification_history
        )
        SELECT event_type, COUNT(*) AS cnt
        FROM unified
        GROUP BY event_type
        """
    )

    by_type = {r["event_type"]: int(r["cnt"]) for r in type_rows}

    return AuditSummary(
        total_events=int(summary_row["total_events"]) if summary_row else 0,
        pass_rate=float(summary_row["pass_rate"]) if summary_row and summary_row["pass_rate"] else None,
        by_type=by_type,
    )
