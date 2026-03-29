"""
src/utils/auth.py — 인증 공용 유틸
"""

import hashlib


def hash_password(password: str) -> str:
    """로그인/시드에서 공통으로 사용하는 SHA-256 비밀번호 해시."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()
