"""
src/api/routers/auth.py — 인증 라우터 (JWT 발급)
"""

import hashlib
import time
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from src.api.deps import get_current_settings, get_current_user
from src.utils.config import Settings
from src.utils.db_client import fetchrow

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int = 86400


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    is_admin: bool


def _hash_password(password: str) -> str:
    """SHA-256 해시 (실제 운영에서는 bcrypt 사용 권장)."""
    return hashlib.sha256(password.encode()).hexdigest()


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    settings: Annotated[Settings, Depends(get_current_settings)],
) -> LoginResponse:
    """이메일/비밀번호로 로그인하여 JWT 토큰을 발급합니다."""
    user = await fetchrow(
        "SELECT id, email, name, password_hash, is_admin FROM users WHERE email = $1",
        body.email,
    )
    if not user or user["password_hash"] != _hash_password(body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    expires_in = 86400  # 24시간
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "is_admin": user["is_admin"],
        "exp": int(time.time()) + expires_in,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return LoginResponse(token=token, expires_in=expires_in)


@router.get("/users/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> UserResponse:
    """현재 로그인한 사용자 정보를 반환합니다."""
    return UserResponse(
        id=current_user["sub"],
        email=current_user["email"],
        name=current_user["name"],
        is_admin=current_user.get("is_admin", False),
    )
