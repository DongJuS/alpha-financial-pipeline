"""
src/utils/secret_validation.py — 시크릿/토큰 값 유효성(placeholder 여부) 판별
"""

from __future__ import annotations

PLACEHOLDER_HINTS = (
    "...",
    "xxx",
    "xxxx",
    "xxxxx",
    "change-this",
    "example",
    "your_",
    "placeholder",
    "<",
    ">",
)


def is_placeholder_secret(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip().strip("'\"").lower()
    if not normalized:
        return True
    if normalized in {"none", "null", "nil", "n/a", "na"}:
        return True
    return any(hint in normalized for hint in PLACEHOLDER_HINTS)
