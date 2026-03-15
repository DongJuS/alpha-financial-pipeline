"""
src/api/routers/notifications.py — 알림 이력 및 설정 라우터
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.api.deps import get_admin_user, get_current_user
from src.utils.config import get_settings
from src.utils.db_client import execute, fetch

router = APIRouter()


class NotificationTestRequest(BaseModel):
    message: str


class NotificationPreferencesRequest(BaseModel):
    morning_brief: bool = True
    trade_alerts: bool = True
    circuit_breaker: bool = True
    daily_report: bool = True
    weekly_summary: bool = True


DEFAULT_NOTIFICATION_PREFERENCES = {
    "morning_brief": True,
    "trade_alerts": True,
    "circuit_breaker": True,
    "daily_report": True,
    "weekly_summary": True,
}


@router.get("/history")
async def get_notification_history(
    _: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """최근 Telegram 알림 발송 이력을 반환합니다."""
    rows = await fetch(
        """
        SELECT event_type, message, success, error_msg,
               to_char(sent_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS+09:00') AS sent_at
        FROM notification_history
        ORDER BY sent_at DESC
        LIMIT $1
        """,
        limit,
    )
    return {"notifications": [dict(r) for r in rows]}


@router.get("/preferences")
async def get_preferences(
    _: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """현재 알림 설정을 조회합니다."""
    import json
    from src.utils.redis_client import get_redis

    redis = await get_redis()
    raw = await redis.get("system:notification_preferences")
    if not raw:
        return {"preferences": DEFAULT_NOTIFICATION_PREFERENCES}

    try:
        loaded = json.loads(raw)
    except Exception:
        loaded = {}

    merged = {**DEFAULT_NOTIFICATION_PREFERENCES, **loaded}
    return {"preferences": merged}


@router.post("/test")
async def send_test_notification(
    body: NotificationTestRequest,
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """테스트 Telegram 알림을 발송합니다."""
    settings = get_settings()

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram 설정이 완료되지 않았습니다. TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 환경변수를 확인하세요.",
        )

    import httpx

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    success = False
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": f"[Alpha 테스트] {body.message}",
                    "parse_mode": "HTML",
                },
            )
            resp.raise_for_status()
            success = True
    except Exception as e:
        error_msg = str(e)

    # 발송 이력 저장
    await execute(
        "INSERT INTO notification_history (event_type, message, success, error_msg) VALUES ($1, $2, $3, $4)",
        "test",
        body.message,
        success,
        error_msg,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram 발송 실패: {error_msg}",
        )

    return {"message": "테스트 알림이 발송되었습니다."}


@router.put("/preferences")
async def update_preferences(
    body: NotificationPreferencesRequest,
    _: Annotated[dict, Depends(get_admin_user)],
) -> dict:
    """알림 설정을 업데이트합니다."""
    # 현재는 Redis에 설정 저장 (Phase 5에서 DB 테이블로 이전 예정)
    import json
    from src.utils.redis_client import get_redis

    redis = await get_redis()
    merged = {**DEFAULT_NOTIFICATION_PREFERENCES, **body.model_dump()}
    await redis.set(
        "system:notification_preferences",
        json.dumps(merged),
    )
    return {"message": "알림 설정이 업데이트되었습니다.", "preferences": merged}
