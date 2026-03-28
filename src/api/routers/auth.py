"""
src/api/routers/auth.py — 인증 라우터 (JWT 발급)
"""

import time
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.api.deps import get_current_settings, get_current_user
from src.utils.config import Settings
from src.utils.db_client import fetchrow
from src.utils.auth import hash_password

router = APIRouter()


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "admin@example.com",
                "password": "admin1234",
            }
        }
    )

    email: EmailStr = Field(description="로그인에 사용할 이메일 주소")
    password: str = Field(description="평문 비밀번호", min_length=1)


class LoginResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sample",
                "expires_in": 86400,
            }
        }
    )

    token: str = Field(description="Swagger Authorize 또는 프론트 localStorage에 넣을 JWT access token")
    expires_in: int = Field(default=86400, description="토큰 만료 시간(초)")


class UserResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "00000000-0000-0000-0000-000000000001",
                "email": "admin@example.com",
                "name": "Admin",
                "is_admin": True,
            }
        }
    )

    id: str
    email: str
    name: str
    is_admin: bool


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="JWT 로그인",
    description="이메일/비밀번호를 검증한 뒤 JWT access token을 발급합니다. 발급된 토큰은 Swagger의 `Authorize` 버튼이나 프론트엔드의 `alpha_token` 저장소에 사용할 수 있습니다.",
    responses={
        401: {
            "description": "이메일 또는 비밀번호가 올바르지 않을 때 반환됩니다.",
            "content": {"application/json": {"example": {"detail": "이메일 또는 비밀번호가 올바르지 않습니다."}}},
        }
    },
)
async def login(
    body: LoginRequest,
    settings: Annotated[Settings, Depends(get_current_settings)],
) -> LoginResponse:
    """이메일/비밀번호로 로그인하여 JWT 토큰을 발급합니다."""
    user = await fetchrow(
        "SELECT id, email, name, password_hash, is_admin FROM users WHERE email = $1",
        body.email,
    )
    if not user or user["password_hash"] != hash_password(body.password):
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


@router.get(
    "/users/me",
    response_model=UserResponse,
    summary="현재 사용자 조회",
    description="Bearer 토큰을 재검증해 현재 로그인한 사용자 정보를 반환합니다.",
    responses={
        401: {
            "description": "토큰이 만료되었거나 유효하지 않거나, 사용자가 삭제된 경우 반환됩니다.",
            "content": {"application/json": {"example": {"detail": "유효하지 않은 토큰입니다."}}},
        }
    },
)
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
