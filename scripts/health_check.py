"""
scripts/health_check.py — 전체 시스템 상태 점검 스크립트

사용법:
    python scripts/health_check.py

에이전트, DB, Redis, KIS 토큰, 환경변수 등을 점검하고 결과를 출력합니다.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.config import get_settings
from src.utils.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

CHECK_MARK = "✅"
WARN_MARK = "⚠️ "
FAIL_MARK = "❌"


async def check_db() -> tuple[bool, str]:
    """PostgreSQL 연결 및 테이블 존재 여부를 확인합니다."""
    from src.utils.db_client import close_pool, fetch

    try:
        rows = await fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        table_names = [r["tablename"] for r in rows]
        expected = {
            "users", "market_data", "predictions", "predictor_tournament_scores",
            "debate_transcripts", "portfolio_config", "portfolio_positions",
            "trade_history", "agent_heartbeats", "collector_errors", "notification_history",
            "real_trading_audit", "operational_audits",
        }
        missing = expected - set(table_names)
        await close_pool()

        if missing:
            return False, f"누락된 테이블: {', '.join(sorted(missing))}"
        return True, f"정상 ({len(table_names)}개 테이블)"
    except Exception as e:
        return False, f"연결 실패: {e}"


async def check_redis() -> tuple[bool, str]:
    """Redis 연결 및 PING 응답을 확인합니다."""
    from src.utils.redis_client import close_redis, get_redis

    try:
        redis = await get_redis()
        pong = await redis.ping()
        await close_redis()
        return pong, "PONG 응답 정상" if pong else "PONG 응답 없음"
    except Exception as e:
        return False, f"연결 실패: {e}"


async def check_kis_token() -> tuple[bool, str]:
    """Redis에 저장된 KIS 토큰 상태를 확인합니다."""
    from src.utils.redis_client import KEY_KIS_OAUTH_TOKEN, close_redis, get_redis
    import json

    try:
        redis = await get_redis()
        raw = await redis.get(KEY_KIS_OAUTH_TOKEN)
        ttl = await redis.ttl(KEY_KIS_OAUTH_TOKEN)
        await close_redis()

        if not raw:
            return False, "토큰 없음 — `python scripts/kis_auth.py` 실행 필요"

        token_info = json.loads(raw)
        mode = "페이퍼" if token_info.get("is_paper") else "실거래"
        if ttl < 3600:
            return True, f"{WARN_MARK} 토큰 {ttl // 60}분 후 만료 [{mode} 모드] — 갱신 권장"
        return True, f"유효 (남은 TTL: {ttl // 60}분) [{mode} 모드]"
    except Exception as e:
        return False, f"확인 실패: {e}"


def check_env_vars() -> tuple[bool, str]:
    """필수 환경변수 설정 여부를 확인합니다."""
    required = {
        "DATABASE_URL": settings.database_url,
        "JWT_SECRET": settings.jwt_secret,
        "REDIS_URL": settings.redis_url,
    }
    optional = {
        "KIS_APP_KEY": settings.kis_app_key,
        "KIS_APP_SECRET": settings.kis_app_secret,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
        "GEMINI_API_KEY": settings.gemini_api_key,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
    }

    missing_required = [k for k, v in required.items() if not v]
    missing_optional = [k for k, v in optional.items() if not v]

    if missing_required:
        return False, f"필수 환경변수 누락: {', '.join(missing_required)}"

    msg = "필수 환경변수 모두 설정됨"
    if missing_optional:
        msg += f"\n     {WARN_MARK} 선택 환경변수 미설정: {', '.join(missing_optional)}"

    return True, msg


async def run_health_check() -> int:
    """전체 헬스체크를 실행하고 종료 코드를 반환합니다."""
    print("\n" + "=" * 55)
    print("  Alpha Trading System — 상태 점검")
    print(f"  환경: {settings.app_env} | 페이퍼: {settings.kis_is_paper_trading}")
    print("=" * 55)

    checks = [
        ("환경변수", check_env_vars()),
        ("PostgreSQL", await check_db()),
        ("Redis", await check_redis()),
        ("KIS 토큰", await check_kis_token()),
    ]

    all_ok = True
    for name, (ok, msg) in checks:
        icon = CHECK_MARK if ok else FAIL_MARK
        print(f"  {icon}  {name:<15} {msg}")
        if not ok:
            all_ok = False

    print("=" * 55)
    if all_ok:
        print("  🎉  모든 점검 통과!")
    else:
        print("  💥  일부 점검 실패 — 위 항목을 확인하세요.")
    print()

    return 0 if all_ok else 1


def main() -> None:
    exit_code = asyncio.run(run_health_check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
