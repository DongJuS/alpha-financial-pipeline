"""
scripts/kis_auth.py — KIS Developers OAuth2 토큰 발급·갱신·저장

사용법:
    python scripts/kis_auth.py             # 토큰 발급 및 Redis 저장
    python scripts/kis_auth.py --check     # Redis에 저장된 토큰 상태 확인
    python scripts/kis_auth.py --revoke    # 토큰 폐기

KIS 토큰 특성:
    - 만료 시간: 발급 후 86400초 (24시간)
    - Redis TTL: 23시간 (만료 1시간 전 갱신 여유분)
    - 실거래/페이퍼 엔드포인트가 다름 — Settings.kis_base_url 자동 분기
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.services.kis_session import issue_kis_token, revoke_kis_token
from src.utils.config import get_settings, kis_app_key_for_scope, kis_app_secret_for_scope
from src.utils.logging import setup_logging
from src.utils.redis_client import (
    TTL_KIS_TOKEN,
    close_redis,
    get_redis,
    kis_oauth_token_key,
)

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


async def issue_token(scope: str) -> dict:
    """KIS Developers OAuth2 토큰을 발급하고 Redis에 저장합니다."""
    app_key = kis_app_key_for_scope(settings, scope)
    app_secret = kis_app_secret_for_scope(settings, scope)
    if not app_key or not app_secret:
        logger.error("KIS_APP_KEY, KIS_APP_SECRET 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    mode = "페이퍼" if scope == "paper" else "실거래"
    logger.info("KIS 토큰 발급 요청 [%s 모드]: %s", mode, f"{settings.kis_base_url_for_scope(scope)}/oauth2/tokenP")
    token_info = await issue_kis_token(settings, account_scope=scope)
    logger.info(
        "✅ KIS 토큰 발급 완료 — Redis TTL: %d시간, 만료: %d초 후",
        TTL_KIS_TOKEN // 3600,
        token_info["expires_in"],
    )

    return token_info


async def check_token(scope: str) -> None:
    """Redis에 저장된 KIS 토큰 상태를 출력합니다."""
    import json

    redis = await get_redis()
    token_key = kis_oauth_token_key(scope)
    raw = await redis.get(token_key)

    if not raw:
        logger.warning("Redis에 KIS %s 토큰이 없습니다. 토큰을 발급하세요.", scope)
        return

    token_info = json.loads(raw)
    ttl = await redis.ttl(token_key)
    access_token_preview = token_info["access_token"][:20] + "..."

    logger.info("─── KIS 토큰 상태 ──────────────────")
    logger.info("  모드    : %s", "페이퍼" if token_info.get("is_paper") else "실거래")
    logger.info("  토큰 앞부분: %s", access_token_preview)
    logger.info("  남은 TTL: %d분 (%d초)", ttl // 60, ttl)
    if ttl < 3600:
        logger.warning("  ⚠️  토큰이 1시간 내에 만료됩니다. 갱신을 권장합니다.")


async def revoke_token(scope: str) -> None:
    """발급된 KIS 토큰을 폐기하고 Redis에서 삭제합니다."""
    redis = await get_redis()
    token_key = kis_oauth_token_key(scope)
    raw = await redis.get(token_key)
    if not raw:
        logger.info("Redis에 저장된 %s 토큰이 없습니다.", scope)
        return
    await revoke_kis_token(settings, account_scope=scope)
    logger.info("✅ KIS %s 토큰이 폐기되었습니다.", scope)


async def main_async(args: argparse.Namespace) -> None:
    try:
        scopes = ["paper", "real"] if args.scope == "all" else [args.scope]
        if args.check:
            for scope in scopes:
                await check_token(scope)
        elif args.revoke:
            for scope in scopes:
                await revoke_token(scope)
        else:
            for scope in scopes:
                await issue_token(scope)
    finally:
        await close_redis()


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS Developers OAuth2 토큰 관리")
    parser.add_argument(
        "--scope",
        choices=["paper", "real", "all"],
        default="paper" if settings.kis_is_paper_trading else "real",
        help="토큰을 발급/확인/폐기할 계좌 scope",
    )
    parser.add_argument("--check", action="store_true", help="저장된 토큰 상태 확인")
    parser.add_argument("--revoke", action="store_true", help="토큰 폐기")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
