"""
src/utils/security_audit.py — 저장소 보안 감사 유틸
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

PLACEHOLDER_HINTS = [
    "...",
    "xxx",
    "xxxx",
    "xxxxx",
    "change-this",
    "example",
    "your_",
    "<",
    ">",
]

SENSITIVE_ENV_KEYS = {
    "JWT_SECRET",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
}

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("gemini", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
]

IGNORED_PATH_PARTS = {
    ".git",
    "node_modules",
    "dist",
    "__pycache__",
    ".venv",
    "venv",
}


def _has_git(root: Path) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(root), "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    if not normalized:
        return True
    return any(hint in normalized for hint in PLACEHOLDER_HINTS)


def _is_text_file(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:1024]
    except OSError:
        return False
    return b"\x00" not in chunk


def _list_tracked_files(root: Path) -> list[Path]:
    if _has_git(root):
        cmd = ["git", "-C", str(root), "ls-files"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return [root / rel for rel in files]

    # git 미설치 환경(예: 경량 Docker)에서는 워크스페이스 파일을 재귀 스캔합니다.
    return [p for p in root.rglob("*") if p.is_file()]


def _line_has_safe_context(line: str) -> bool:
    lower = line.lower()
    return any(token in lower for token in ["example", "sample", "dummy", "placeholder", "your_"])


def check_env_git_safety(root: Path) -> dict[str, Any]:
    gitignore_path = root / ".gitignore"
    has_env_rule = False
    if gitignore_path.exists():
        for line in gitignore_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped in {".env", "*.env"} or stripped.endswith("/.env"):
                has_env_rule = True
                break

    tracked_env = False
    git_available = _has_git(root)
    if git_available:
        tracked_cmd = ["git", "-C", str(root), "ls-files", "--error-unmatch", ".env"]
        tracked_run = subprocess.run(tracked_cmd, capture_output=True, text=True)
        tracked_env = tracked_run.returncode == 0

    ok = has_env_rule and (not tracked_env)
    if ok:
        if git_available:
            message = ".env git 추적 방지 설정 정상"
        else:
            message = ".env 제외 규칙 확인됨 (git 미설치로 추적 여부 확인 생략)"
    elif tracked_env:
        message = ".env 파일이 git에 추적되고 있습니다"
    else:
        message = ".gitignore에 .env 제외 규칙이 없습니다"

    return {
        "ok": ok,
        "git_available": git_available,
        "has_env_ignore_rule": has_env_rule,
        "tracked_env": tracked_env,
        "message": message,
    }


def scan_repository_for_secrets(root: Path, tracked_files: list[Path] | None = None) -> dict[str, Any]:
    files = tracked_files or _list_tracked_files(root)
    findings: list[dict[str, Any]] = []
    scanned_files = 0

    for path in files:
        rel = path.relative_to(root).as_posix()
        if any(part in IGNORED_PATH_PARTS for part in path.parts):
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if not path.is_file() or not _is_text_file(path):
            continue

        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue

        scanned_files += 1
        for lineno, line in enumerate(lines, start=1):
            if _line_has_safe_context(line):
                continue

            for pattern_name, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue

                candidate = match.group(0)
                if _looks_like_placeholder(candidate):
                    continue

                findings.append(
                    {
                        "type": pattern_name,
                        "path": rel,
                        "line": lineno,
                        "snippet": line.strip()[:180],
                    }
                )

    return {
        "ok": len(findings) == 0,
        "scanned_files": scanned_files,
        "findings": findings,
    }


def check_env_example_safety(root: Path) -> dict[str, Any]:
    path = root / ".env.example"
    issues: list[str] = []
    if not path.exists():
        return {"ok": False, "issues": [".env.example 파일이 없습니다."]}

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key not in SENSITIVE_ENV_KEYS:
            continue
        if value and not _looks_like_placeholder(value):
            issues.append(f"{key}가 placeholder가 아닌 값으로 보입니다")

    return {"ok": len(issues) == 0, "issues": issues}


def run_repository_security_audit(root: Path | None = None) -> dict[str, Any]:
    base = root or Path(__file__).resolve().parents[2]

    env_safety = check_env_git_safety(base)
    secret_scan = scan_repository_for_secrets(base)
    env_example = check_env_example_safety(base)

    failures: list[str] = []
    warnings: list[str] = []

    if not env_safety["ok"]:
        failures.append(env_safety["message"])

    if not secret_scan["ok"]:
        failures.append(f"시크릿 패턴 탐지 {len(secret_scan['findings'])}건")

    if not env_example["ok"]:
        warnings.extend(env_example["issues"])
    if not env_safety.get("git_available", True):
        warnings.append("git 미설치 환경에서 실행되어 파일 추적 기반 검사가 일부 축소되었습니다")

    passed = len(failures) == 0
    summary = "보안 감사 통과" if passed else f"보안 감사 실패 ({len(failures)}건)"

    return {
        "passed": passed,
        "summary": summary,
        "failures": failures,
        "warnings": warnings,
        "env_safety": env_safety,
        "secret_scan": secret_scan,
        "env_example": env_example,
    }
