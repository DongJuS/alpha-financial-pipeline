"""
src/utils/agent_activity.py — 에이전트 활동 상태 분류 유틸
"""

from __future__ import annotations

from datetime import datetime, timezone

ACTIVE_WINDOW_SECONDS = 180
SCHEDULED_WAIT_WINDOW_SECONDS = 900

INVESTING_KEYWORDS = ("주문", "투자", "매수", "매도", "청산", "포지션")
COLLECTING_KEYWORDS = ("수집", "collector")
ANALYZING_KEYWORDS = ("예측", "토론", "합의", "tournament", "score")
NOTIFYING_KEYWORDS = ("알림", "리포트", "telegram")
ORCHESTRATING_KEYWORDS = ("사이클", "orchestrator", "execution", "plan")


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_agent_activity(
    *,
    status: str,
    is_alive: bool,
    last_action: str | None,
    updated_at: str | None,
    now_utc: datetime | None = None,
) -> tuple[str, str]:
    """
    에이전트 활동 상태(activity_state)와 표시 라벨(activity_label)을 반환합니다.
    """
    if status == "dead":
        return "offline", "중지"
    if status == "error":
        return "error", "오류"
    if not is_alive and not updated_at:
        return "offline", "중지"

    now = now_utc or datetime.now(timezone.utc)
    updated = _parse_utc_timestamp(updated_at)
    is_recent = False
    elapsed_seconds: int | None = None
    if updated:
        elapsed_seconds = max(0, int((now - updated).total_seconds()))
        is_recent = elapsed_seconds <= ACTIVE_WINDOW_SECONDS

    action_text = (last_action or "").lower()

    if is_recent:
        if _contains_any(action_text, INVESTING_KEYWORDS):
            return "investing", "투자 실행 중"
        if _contains_any(action_text, COLLECTING_KEYWORDS):
            return "collecting", "데이터 수집 중"
        if _contains_any(action_text, ANALYZING_KEYWORDS):
            return "analyzing", "신호 분석 중"
        if _contains_any(action_text, NOTIFYING_KEYWORDS):
            return "notifying", "알림 처리 중"
        if _contains_any(action_text, ORCHESTRATING_KEYWORDS):
            return "orchestrating", "흐름 조율 중"
        return "active", "활동 중"

    if status == "degraded":
        return "degraded", "점검 필요"

    if is_alive and not updated:
        return "active", "활동 중"
    if elapsed_seconds is not None and elapsed_seconds <= SCHEDULED_WAIT_WINDOW_SECONDS:
        return "scheduled_wait", "주기 대기 중"
    return "idle", "대기 중"
