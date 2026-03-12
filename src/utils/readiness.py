"""
src/utils/readiness.py — 실거래 전환 준비 상태 점검
"""

from __future__ import annotations

from typing import Any

from src.utils.config import get_settings
from src.utils.db_client import fetchrow, fetchval
from src.utils.redis_client import get_redis


PLACEHOLDER_PATTERNS = [
    "...",
    "xxx",
    "xxxx",
    "xxxxx",
    "change-this",
    "example",
]


def _is_placeholder(value: str) -> bool:
    lower = value.strip().lower()
    if not lower:
        return True
    return any(p in lower for p in PLACEHOLDER_PATTERNS)


async def evaluate_real_trading_readiness() -> dict[str, Any]:
    """실거래 전환 전 필수 조건을 점검합니다."""
    settings = get_settings()
    checks: list[dict[str, Any]] = []

    # 1) 필수 자격증명
    cred_pairs = [
        ("KIS_APP_KEY", settings.kis_app_key),
        ("KIS_APP_SECRET", settings.kis_app_secret),
        ("KIS_ACCOUNT_NUMBER", settings.kis_account_number),
        ("JWT_SECRET", settings.jwt_secret),
        ("REAL_TRADING_CONFIRMATION_CODE", settings.real_trading_confirmation_code),
    ]
    for key, value in cred_pairs:
        ok = bool(value and not _is_placeholder(value))
        checks.append(
            {
                "key": f"cred:{key}",
                "ok": ok,
                "message": f"{key} 설정 {'정상' if ok else '누락/placeholder'}",
                "severity": "critical",
            }
        )

    # 2) 알림 채널
    telegram_ok = bool(
        settings.telegram_bot_token
        and settings.telegram_chat_id
        and not _is_placeholder(settings.telegram_bot_token)
        and not _is_placeholder(settings.telegram_chat_id)
    )
    checks.append(
        {
            "key": "notif:telegram",
            "ok": telegram_ok,
            "message": "Telegram 알림 채널 설정 " + ("정상" if telegram_ok else "누락/placeholder"),
            "severity": "high",
        }
    )

    # 3) DB 연결
    try:
        db_ok = (await fetchval("SELECT 1")) == 1
    except Exception as e:
        db_ok = False
        db_err = str(e)
    checks.append(
        {
            "key": "infra:db",
            "ok": db_ok,
            "message": "DB 연결 " + ("정상" if db_ok else f"실패 ({db_err})"),
            "severity": "critical",
        }
    )

    # 4) Redis 연결
    try:
        redis = await get_redis()
        redis_ok = bool(await redis.ping())
    except Exception as e:
        redis_ok = False
        redis_err = str(e)
    checks.append(
        {
            "key": "infra:redis",
            "ok": redis_ok,
            "message": "Redis 연결 " + ("정상" if redis_ok else f"실패 ({redis_err})"),
            "severity": "critical",
        }
    )

    # 5) 리스크 설정
    try:
        cfg = await fetchrow(
            """
            SELECT max_position_pct, daily_loss_limit_pct
            FROM portfolio_config
            LIMIT 1
            """
        )
        if cfg:
            max_position_pct = int(cfg["max_position_pct"])
            daily_loss_limit_pct = int(cfg["daily_loss_limit_pct"])
        else:
            max_position_pct = 1000
            daily_loss_limit_pct = 0
    except Exception:
        max_position_pct = 1000
        daily_loss_limit_pct = 0

    risk_ok = (1 <= max_position_pct <= 30) and (1 <= daily_loss_limit_pct <= 10)
    checks.append(
        {
            "key": "risk:limits",
            "ok": risk_ok,
            "message": (
                "리스크 한도 점검 "
                + (
                    f"정상(max_position_pct={max_position_pct}, daily_loss_limit_pct={daily_loss_limit_pct})"
                    if risk_ok
                    else (
                        f"비정상(max_position_pct={max_position_pct}, daily_loss_limit_pct={daily_loss_limit_pct})"
                    )
                )
            ),
            "severity": "critical",
        }
    )

    # 6) LLM 키 최소 1개
    llm_values = [settings.anthropic_api_key, settings.openai_api_key, settings.gemini_api_key]
    llm_ok = any(v and not _is_placeholder(v) for v in llm_values)
    checks.append(
        {
            "key": "llm:any",
            "ok": llm_ok,
            "message": "LLM 키 최소 1개 " + ("정상" if llm_ok else "누락/placeholder"),
            "severity": "high",
        }
    )

    critical_ok = all(c["ok"] for c in checks if c["severity"] == "critical")
    high_ok = all(c["ok"] for c in checks if c["severity"] in {"critical", "high"})
    return {
        "ready": critical_ok and high_ok,
        "critical_ok": critical_ok,
        "high_ok": high_ok,
        "checks": checks,
    }
