"""
src/api/routers/agents.py — 에이전트 상태 및 관리 라우터
"""

import json
from collections.abc import Mapping
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError

from src.agents import (
    FAST_FLOW_AGENT_ID,
    SLOW_METICULOUS_AGENT_ID,
    DualExecutionCoordinator,
    record_dual_execution_heartbeat,
)
from src.api.deps import get_admin_user, get_current_user
from src.utils.agent_activity import classify_agent_activity
from src.utils.db_client import fetch
from src.utils.redis_client import check_heartbeat

router = APIRouter()

AGENT_IDS = [
    "collector_agent",
    "predictor_1",
    "predictor_2",
    "predictor_3",
    "predictor_4",
    "predictor_5",
    "portfolio_manager_agent",
    "notifier_agent",
    "orchestrator_agent",
    FAST_FLOW_AGENT_ID,
    SLOW_METICULOUS_AGENT_ID,
]
ON_DEMAND_AGENT_IDS = {FAST_FLOW_AGENT_ID, SLOW_METICULOUS_AGENT_ID}


class AgentMetrics(BaseModel):
    api_latency_ms: Optional[int] = None
    error_count_last_hour: int = 0


class AgentStatusItem(BaseModel):
    agent_id: str
    status: str
    is_alive: bool
    activity_state: str
    activity_label: str
    last_action: Optional[str] = None
    metrics: Optional[AgentMetrics] = None
    updated_at: Optional[str] = None


class AgentsStatusResponse(BaseModel):
    agents: list[AgentStatusItem]


class DualExecutionRequest(BaseModel):
    task: str = Field(..., min_length=4, description="실행할 작업 지시")
    context: list[str] = Field(default_factory=list, description="보조 컨텍스트(선택)")


class DetailedStepItem(BaseModel):
    step: str
    why: str
    done_criteria: str


class FastFlowPlanItem(BaseModel):
    agent_id: str
    mode: str
    summary: str
    priorities: list[str]
    execution_tracks: list[str]
    quick_risks: list[str]


class SlowMeticulousPlanItem(BaseModel):
    agent_id: str
    mode: str
    assumptions: list[str]
    detailed_steps: list[DetailedStepItem]
    validation_checks: list[str]
    blockers_to_watch: list[str]


class CombinedExecutionPlanItem(BaseModel):
    execution_mode: str
    immediate_actions: list[str]
    verification_gate: list[str]
    completion_definition: list[str]


class DualExecutionResponse(BaseModel):
    task: str
    generated_at: str
    fast_flow: FastFlowPlanItem
    slow_meticulous: SlowMeticulousPlanItem
    combined: CombinedExecutionPlanItem


def _parse_agent_metrics(raw_metrics: Any) -> Optional[AgentMetrics]:
    if raw_metrics is None:
        return None

    parsed: dict[str, Any]
    if isinstance(raw_metrics, Mapping):
        parsed = dict(raw_metrics)
    elif isinstance(raw_metrics, str):
        try:
            decoded = json.loads(raw_metrics)
        except json.JSONDecodeError:
            return None
        if not isinstance(decoded, Mapping):
            return None
        parsed = dict(decoded)
    else:
        return None

    try:
        return AgentMetrics(**parsed)
    except (TypeError, ValidationError):
        return None


@router.get("/status", response_model=AgentsStatusResponse)
async def get_agents_status(
    _: Annotated[dict, Depends(get_current_user)],
) -> AgentsStatusResponse:
    """모든 에이전트의 최신 헬스 상태를 반환합니다."""
    # DB에서 각 에이전트의 최신 헬스비트 조회
    rows = await fetch(
        """
        SELECT DISTINCT ON (agent_id)
            agent_id, status, last_action, metrics,
            to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS updated_at
        FROM agent_heartbeats
        ORDER BY agent_id, recorded_at DESC
        """
    )

    db_status: dict[str, dict] = {r["agent_id"]: dict(r) for r in rows}

    items: list[AgentStatusItem] = []
    for agent_id in AGENT_IDS:
        is_alive = await check_heartbeat(agent_id)
        db_row = db_status.get(agent_id)
        if db_row is None and agent_id in ON_DEMAND_AGENT_IDS:
            items.append(
                AgentStatusItem(
                    agent_id=agent_id,
                    status="healthy",
                    is_alive=False,
                    activity_state="on_demand",
                    activity_label="요청 대기",
                    last_action="API 요청 시 실행",
                    metrics=None,
                    updated_at=None,
                )
            )
            continue
        status_value = db_row["status"] if db_row else ("healthy" if is_alive else "dead")
        updated_at = db_row["updated_at"] if db_row else None
        last_action = db_row["last_action"] if db_row else None
        activity_state, activity_label = classify_agent_activity(
            status=status_value,
            is_alive=is_alive,
            last_action=last_action,
            updated_at=updated_at,
        )

        items.append(
            AgentStatusItem(
                agent_id=agent_id,
                status=status_value,
                is_alive=is_alive,
                activity_state=activity_state,
                activity_label=activity_label,
                last_action=last_action,
                metrics=_parse_agent_metrics(db_row["metrics"]) if db_row else None,
                updated_at=updated_at,
            )
        )

    return AgentsStatusResponse(agents=items)


@router.post("/dual-execution/run", response_model=DualExecutionResponse)
async def run_dual_execution(
    body: DualExecutionRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> DualExecutionResponse:
    """
    2개 에이전트를 자동 순차 실행합니다.
    1) fast_flow_agent: 빠른 전체 흐름 설계
    2) slow_meticulous_agent: 꼼꼼한 상세 검증 계획 보강
    """
    coordinator = DualExecutionCoordinator()
    result = coordinator.run(task=body.task, context=body.context)

    # 실행 이력은 부가 기능이므로 실패해도 본 응답은 반환합니다.
    await record_dual_execution_heartbeat(result, source="api:/agents/dual-execution/run")

    return DualExecutionResponse(**result.to_dict())


@router.get("/{agent_id}/logs")
async def get_agent_logs(
    agent_id: str,
    _: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
    level: Optional[str] = Query(default=None, pattern="^(INFO|WARNING|ERROR)$"),
) -> dict:
    """특정 에이전트의 최근 헬스비트 로그를 반환합니다."""
    if agent_id not in AGENT_IDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{agent_id}'를 찾을 수 없습니다.",
        )

    query = """
        SELECT
            agent_id, status, last_action, metrics,
            to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS recorded_at
        FROM agent_heartbeats
        WHERE agent_id = $1
        ORDER BY recorded_at DESC
        LIMIT $2
    """
    rows = await fetch(query, agent_id, limit)
    return {"agent_id": agent_id, "logs": [dict(r) for r in rows]}


@router.post("/{agent_id}/restart")
async def restart_agent(
    agent_id: str,
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """에이전트 재시작 신호를 발행합니다 (관리자 전용)."""
    if agent_id not in AGENT_IDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{agent_id}'를 찾을 수 없습니다.",
        )

    import json
    from src.utils.redis_client import publish_message, TOPIC_ALERTS

    await publish_message(
        TOPIC_ALERTS,
        json.dumps(
            {
                "type": "restart_request",
                "agent_id": agent_id,
                "requested_by": "admin",
            }
        ),
    )

    return {"message": f"'{agent_id}' 재시작 신호가 발행되었습니다."}


@router.post("/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """에이전트 일시정지 신호를 발행합니다 (관리자 전용)."""
    if agent_id not in AGENT_IDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{agent_id}'를 찾을 수 없습니다.",
        )

    from src.utils.redis_client import publish_message, TOPIC_ALERTS

    await publish_message(
        TOPIC_ALERTS,
        json.dumps(
            {
                "type": "pause_request",
                "agent_id": agent_id,
                "requested_by": "admin",
            }
        ),
    )

    return {"message": f"'{agent_id}' 일시정지 신호가 발행되었습니다."}


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """에이전트 재개 신호를 발행합니다 (관리자 전용)."""
    if agent_id not in AGENT_IDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{agent_id}'를 찾을 수 없습니다.",
        )

    from src.utils.redis_client import publish_message, TOPIC_ALERTS

    await publish_message(
        TOPIC_ALERTS,
        json.dumps(
            {
                "type": "resume_request",
                "agent_id": agent_id,
                "requested_by": "admin",
            }
        ),
    )

    return {"message": f"'{agent_id}' 재개 신호가 발행되었습니다."}
