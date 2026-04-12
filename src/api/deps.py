"""
src/api/deps.py — FastAPI 의존성 주입 모음

각 라우터에서 `Depends()`로 사용합니다.
"""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.utils.config import get_settings, Settings
from src.utils.db_client import fetchrow
from src.utils.logging import get_logger

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="JWT access token을 입력하세요. `Bearer` 접두사는 자동으로 붙지 않으니 토큰 문자열만 입력하면 됩니다.",
)


def get_current_settings() -> Settings:
    return get_settings()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_current_settings)],
) -> dict:
    """Bearer 토큰을 검증하고 현재 사용자 정보를 반환합니다."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning("auth 401: 토큰 만료 — token prefix: %s…", token[:8] if len(token) > 8 else "short")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning("auth 401: 유효하지 않은 토큰 — %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await fetchrow(
        "SELECT id, email, name, is_admin FROM users WHERE id = $1::uuid",
        user_id,
    )
    if not user:
        logger.warning("auth 401: user_id=%s — users 테이블에 존재하지 않음 (삭제된 사용자?)", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="존재하지 않는 사용자입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "sub": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "is_admin": user["is_admin"],
        "exp": payload.get("exp"),
    }


async def get_admin_user(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """관리자 권한 확인."""
    if not current_user.get("is_admin"):
        logger.warning("auth 403: email=%s — 관리자 권한 없음", current_user.get("email"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )
    return current_user
