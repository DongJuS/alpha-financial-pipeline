"""
src/api/routers/audit.py — 감사 추적(Audit Trail) 라우터
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
    id: int
    audit_type: str
    event_source: str
    summary: str
    details: Optional[dict[str, Any]] = None
    success: Optional[bool] = None
    actor: Optional[str] = None
    created_at: str


class AuditTrailResponse(BaseModel):
    items: list[AuditTrailItem]
    total: int
    page: int
    per_page: int


class AuditSummaryResponse(BaseModel):
    total_events: int
    events_24h: int
    events_7d: int
    by_type: dict[str, int]
    pass_rate: Optional[float] = None


@router.get("/trail", response_model=AuditTrailResponse)
async def get_audit_trail(
    _: Annotated[dict, Depends(get_current_user)],
    audit_type: Optional[str] = Query(default=None, description="감사 유형 필터"),
    from_date: Optional[str] = Query(
        default=None, alias="from", description="시작일 (YYYY-MM-DD)"
    ),
    to_date: Optional[str] = Query(
        default=None, alias="to", description="종료일 (YYYY-MM-DD)"
    ),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> AuditTrailResponse:
    """통합 감사 추적 이력을 반환합니다."""
    params: list[Any] = []
    where_parts: list[str] = []

    if audit_type:
        params.append(audit_type)
        where_parts.append(f"audit_type = ${len(params)}")
    if from_date:
        params.append(from_date)
        where_parts.append(f"created_at >= ${len(params)}::date")
    if to_date:
        params.append(to_date)
        where_parts.append(f"created_at < (${len(params)}::date + interval '1 day')")

    where_clause = ""
    if where_parts:
        where_clause = "WHERE " + " AND ".join(where_parts)

    offset = (page - 1) * per_page
    params += [per_page, offset]

    query = f"""
    WITH unified_audit AS (
        SELECT
            id, audit_type, 'operational' AS event_source,
            summary,
            details::text::jsonb AS details,
            passed AS success,
            executed_by AS actor,
            created_at
        FROM operational_audits

        UNION ALL

        SELECT
            id, 'mode_switch' AS audit_type, 'trading_mode' AS event_source,
            COALESCE(message, '모드 전환 요청') AS summary,
            jsonb_build_object(
                'paper_enabled', requested_paper_enabled,
                'real_enabled', requested_real_enabled,
                'primary_scope', requested_primary_account_scope,
                'applied', applied
            ) AS details,
            applied AS success,
            COALESCE(requested_by_email, requested_by_user_id) AS actor,
            requested_at AS created_at
        FROM real_trading_audit

        UNION ALL

        SELECT
            id, 'notification' AS audit_type, 'notifier' AS event_source,
            CONCAT(event_type, ': ', LEFT(message, 80)) AS summary,
            jsonb_build_object('event_type', event_type, 'error_msg', error_msg) AS details,
            success,
            NULL AS actor,
            sent_at AS created_at
        FROM notification_history
    )
    SELECT
        id, audit_type, event_source, summary, details, success, actor,
        to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
    FROM unified_audit
    {where_clause}
    ORDER BY created_at DESC
    LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """

    rows = await fetch(query, *params)
    items = [AuditTrailItem(**dict(r)) for r in rows]

    # total count
    count_params = params[:-2]
    count_query = f"""
    WITH unified_audit AS (
        SELECT id, audit_type, created_at FROM operational_audits
        UNION ALL
        SELECT id, 'mode_switch' AS audit_type, requested_at AS created_at FROM real_trading_audit
        UNION ALL
        SELECT id, 'notification' AS audit_type, sent_at AS created_at FROM notification_history
    )
    SELECT COUNT(*) AS cnt FROM unified_audit {where_clause}
    """
    count_row = await fetchrow(count_query, *count_params)
    total = int(count_row["cnt"] or 0) if count_row else 0

    return AuditTrailResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/summary", response_model=AuditSummaryResponse)
async def get_audit_summary(
    _: Annotated[dict, Depends(get_current_user)],
) -> AuditSummaryResponse:
    """감사 이벤트 요약 통계를 반환합니다."""
    row = await fetchrow(
        """
        WITH unified AS (
            SELECT audit_type, passed AS success, created_at FROM operational_audits
            UNION ALL
            SELECT 'mode_switch', applied, requested_at FROM real_trading_audit
            UNION ALL
            SELECT 'notification', success, sent_at FROM notification_history
        )
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS cnt_24h,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS cnt_7d,
            COUNT(*) FILTER (WHERE success = TRUE) AS pass_count
        FROM unified
        """
    )

    total = int(row["total"] or 0) if row else 0
    cnt_24h = int(row["cnt_24h"] or 0) if row else 0
    cnt_7d = int(row["cnt_7d"] or 0) if row else 0
    pass_count = int(row["pass_count"] or 0) if row else 0
    pass_rate = round(pass_count / total * 100, 1) if total > 0 else None

    type_rows = await fetch(
        """
        WITH unified AS (
            SELECT audit_type FROM operational_audits
            UNION ALL
            SELECT 'mode_switch' FROM real_trading_audit
            UNION ALL
            SELECT 'notification' FROM notification_history
        )
        SELECT audit_type, COUNT(*) AS cnt FROM unified GROUP BY audit_type
        """
    )
    by_type = {r["audit_type"]: int(r["cnt"]) for r in type_rows}

    return AuditSummaryResponse(
        total_events=total,
        events_24h=cnt_24h,
        events_7d=cnt_7d,
        by_type=by_type,
        pass_rate=pass_rate,
    )
