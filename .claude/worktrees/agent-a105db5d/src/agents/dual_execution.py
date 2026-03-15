"""
src/agents/dual_execution.py — 빠른/꼼꼼 2-에이전트 실행 코디네이터

목표:
1) fast_flow_agent가 전체 흐름을 빠르게 설계
2) slow_meticulous_agent가 검증 중심의 상세 실행안으로 보완
3) 두 결과를 합쳐 자동 실행 가능한 작업 지시로 반환
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Iterable

from src.utils.logging import get_logger

logger = get_logger(__name__)

FAST_FLOW_AGENT_ID = "fast_flow_agent"
SLOW_METICULOUS_AGENT_ID = "slow_meticulous_agent"

_FOCUS_RULES: list[tuple[str, str]] = [
    ("docker", "컨테이너/배포"),
    ("compose", "서비스 오케스트레이션"),
    ("api", "백엔드 API 경로"),
    ("router", "라우터/엔드포인트"),
    ("frontend", "프론트 연동"),
    ("ui", "프론트 연동"),
    ("db", "데이터 스키마/호환성"),
    ("database", "데이터 스키마/호환성"),
    ("redis", "캐시/메시징"),
    ("test", "검증/회귀 방지"),
    ("문서", "문서/운영 가이드"),
    ("docs", "문서/운영 가이드"),
    ("commit", "릴리스/커밋 품질"),
]


@dataclass
class DetailedStep:
    step: str
    why: str
    done_criteria: str


@dataclass
class FastFlowPlan:
    agent_id: str
    mode: str
    summary: str
    priorities: list[str]
    execution_tracks: list[str]
    quick_risks: list[str]


@dataclass
class SlowMeticulousPlan:
    agent_id: str
    mode: str
    assumptions: list[str]
    detailed_steps: list[DetailedStep]
    validation_checks: list[str]
    blockers_to_watch: list[str]


@dataclass
class CombinedExecutionPlan:
    execution_mode: str
    immediate_actions: list[str]
    verification_gate: list[str]
    completion_definition: list[str]


@dataclass
class DualExecutionResult:
    task: str
    generated_at: str
    fast_flow: FastFlowPlan
    slow_meticulous: SlowMeticulousPlan
    combined: CombinedExecutionPlan

    def to_dict(self) -> dict:
        return asdict(self)


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _detect_focus(task: str, context: list[str]) -> list[str]:
    corpus = f"{task}\n" + "\n".join(context)
    lowered = corpus.lower()

    detected = [focus for key, focus in _FOCUS_RULES if key in lowered]
    if not detected:
        detected = ["핵심 기능", "검증/회귀 방지", "문서/운영 가이드"]
    return _unique(detected)[:5]


def _risk_from_focus(focus: str) -> str:
    mapping = {
        "컨테이너/배포": "환경별 포트/네트워크 차이로 연결 실패 가능성",
        "서비스 오케스트레이션": "서비스 시작 순서 불일치로 초기화 실패 가능성",
        "백엔드 API 경로": "기존 클라이언트와 경로/스키마 불일치 가능성",
        "라우터/엔드포인트": "권한/검증 누락으로 보안 리스크 발생 가능성",
        "프론트 연동": "프록시/베이스 URL 불일치로 API 호출 실패 가능성",
        "데이터 스키마/호환성": "스키마 변경 시 마이그레이션 누락 가능성",
        "캐시/메시징": "TTL/채널 규칙 불일치로 상태 오탐 가능성",
        "검증/회귀 방지": "핵심 경로 테스트 누락으로 회귀 발생 가능성",
        "문서/운영 가이드": "실행 절차 문서 미반영으로 운영 혼선 가능성",
        "릴리스/커밋 품질": "변경 의도 누락으로 히스토리 추적 난이도 증가",
        "핵심 기능": "핵심 흐름 누락으로 사용자 요구 미충족 가능성",
    }
    return mapping.get(focus, "의존성/환경 차이로 예기치 않은 동작 가능성")


class FastFlowAgent:
    """빠른 방향성 수립 담당 에이전트."""

    agent_id = FAST_FLOW_AGENT_ID

    def run(self, task: str, context: list[str]) -> FastFlowPlan:
        focus = _detect_focus(task, context)
        priorities = [f"{idx + 1}. {topic} 먼저 고정" for idx, topic in enumerate(focus)]

        execution_tracks = [
            "현재 상태를 5분 내 스캔해 변경 지점을 확정",
            "영향도가 큰 파일부터 순차 반영",
            "동작 검증(명령/컴파일/헬스체크)으로 실패 지점 조기 확인",
            "문서와 실행 절차를 마지막에 동기화",
        ]

        quick_risks = [_risk_from_focus(topic) for topic in focus[:3]]

        return FastFlowPlan(
            agent_id=self.agent_id,
            mode="fast-overview",
            summary=f"요청 작업을 큰 흐름 기준으로 분해해 빠르게 완료 경로를 제시합니다: {task}",
            priorities=priorities,
            execution_tracks=execution_tracks,
            quick_risks=quick_risks,
        )


class SlowMeticulousAgent:
    """느리지만 누락을 줄이는 검증 중심 에이전트."""

    agent_id = SLOW_METICULOUS_AGENT_ID

    def run(self, task: str, context: list[str], fast_plan: FastFlowPlan) -> SlowMeticulousPlan:
        assumptions = _unique(
            [
                "기존 API 계약과 DB 스키마 호환성을 유지해야 함",
                "변경 후 실행/검증 커맨드가 재현 가능해야 함",
                "운영 문서(README/BOOTSTRAP/API 스펙)가 코드와 일치해야 함",
            ]
            + [f"추가 컨텍스트: {line}" for line in context[:2]]
        )

        detailed_steps: list[DetailedStep] = []
        for idx, priority in enumerate(fast_plan.priorities, start=1):
            topic = priority.split(". ", 1)[1] if ". " in priority else priority
            topic = topic.replace(" 먼저 고정", "")
            detailed_steps.append(
                DetailedStep(
                    step=f"[{idx}] {topic} 변경 구현",
                    why=f"{topic} 영역이 전체 작업 성공률에 직접 영향",
                    done_criteria=f"{topic} 관련 코드/설정/문서가 서로 모순 없이 반영됨",
                )
            )

        # 기본 검증 체크는 항상 포함
        validation_checks = _unique(
            [
                "정적 점검 또는 컴파일 단계에서 문법 오류가 없어야 함",
                "핵심 API 경로 또는 스크립트 실행 결과가 성공이어야 함",
                "신규/변경 설정 파일이 실제 실행 명령과 일치해야 함",
                "커밋 메시지 본문에 변경 의도·영향·검증 내역이 포함되어야 함",
            ]
        )

        blockers_to_watch = [
            "외부 의존 서비스 미기동(DB/Redis/Docker daemon) 시 검증 결과가 왜곡될 수 있음",
            "환경변수 누락 시 런타임 실패 가능성이 높음",
            "권한 제한으로 git 작업이 중단될 수 있음",
        ]

        return SlowMeticulousPlan(
            agent_id=self.agent_id,
            mode="slow-meticulous",
            assumptions=assumptions,
            detailed_steps=detailed_steps,
            validation_checks=validation_checks,
            blockers_to_watch=blockers_to_watch,
        )


class DualExecutionCoordinator:
    """빠른 흐름 + 꼼꼼 검증을 순차 결합하는 실행 코디네이터."""

    def __init__(self) -> None:
        self.fast_agent = FastFlowAgent()
        self.slow_agent = SlowMeticulousAgent()

    def run(self, task: str, context: list[str] | None = None) -> DualExecutionResult:
        ctx = context or []
        fast = self.fast_agent.run(task=task, context=ctx)
        slow = self.slow_agent.run(task=task, context=ctx, fast_plan=fast)

        combined = CombinedExecutionPlan(
            execution_mode="fast-first-then-meticulous",
            immediate_actions=[
                "fast_flow_agent 계획으로 우선순위 고정",
                "slow_meticulous_agent 체크리스트로 누락 검증",
                "검증 통과 후 상세 커밋 메시지로 결과 고정",
            ],
            verification_gate=slow.validation_checks,
            completion_definition=[
                "핵심 변경이 실행 가능한 상태로 반영됨",
                "검증 명령 결과가 실패 없이 확인됨",
                "문서/코드/실행 절차가 동기화됨",
            ],
        )

        return DualExecutionResult(
            task=task,
            generated_at=datetime.now(timezone.utc).isoformat(),
            fast_flow=fast,
            slow_meticulous=slow,
            combined=combined,
        )


async def record_dual_execution_heartbeat(result: DualExecutionResult, source: str) -> None:
    """
    2개 에이전트 실행 결과를 Redis heartbeat + DB 로그로 기록합니다.
    외부 의존성 장애가 있더라도 핵심 결과 반환을 막지 않도록 예외는 내부 처리합니다.
    """
    from src.utils.db_client import execute
    from src.utils.redis_client import set_heartbeat

    payload = {
        "source": source,
        "generated_at": result.generated_at,
        "task": result.task,
    }
    actions = {
        FAST_FLOW_AGENT_ID: "전체 흐름 우선순위 계획 생성",
        SLOW_METICULOUS_AGENT_ID: "상세 체크리스트 및 검증 게이트 작성",
    }

    for agent_id, action in actions.items():
        try:
            await set_heartbeat(agent_id)
        except Exception as e:
            logger.warning("heartbeat 기록 실패 (%s): %s", agent_id, e)

        try:
            await execute(
                """
                INSERT INTO agent_heartbeats (agent_id, status, last_action, metrics)
                VALUES ($1, 'healthy', $2, $3::jsonb)
                """,
                agent_id,
                action,
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("DB heartbeat 로그 실패 (%s): %s", agent_id, e)
