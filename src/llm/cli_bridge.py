"""
src/llm/cli_bridge.py — LLM CLI 실행 브릿지
"""

from __future__ import annotations

import asyncio
import shlex
import shutil


def _claude_known_paths() -> list[str]:
    """claude CLI가 설치될 수 있는 알려진 경로 목록을 반환합니다."""
    import os

    return [
        os.path.expanduser("~/.claude/bin/claude"),
        "/root/.claude/bin/claude",
        "/usr/local/bin/claude",
        "/usr/lib/node_modules/.bin/claude",       # npm global (Docker)
        "/usr/local/lib/node_modules/.bin/claude",  # npm global (alt)
    ]


def _resolve_cli_path(cmd: str) -> str:
    """shutil.which 로 못 찾으면 알려진 경로를 직접 탐색합니다."""
    import os

    resolved = shutil.which(cmd)
    if resolved:
        return resolved

    if cmd == "claude":
        for p in _claude_known_paths():
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return cmd  # 원본 반환 (실행 시 에러로 잡힘)


def build_cli_command(template: str, model: str) -> list[str]:
    """
    CLI 커맨드 템플릿을 토큰화합니다.
    - {model} 플레이스홀더를 현재 모델명으로 치환합니다.
    """
    rendered = (template or "").strip().replace("{model}", model)
    if not rendered:
        return []
    tokens = shlex.split(rendered)
    if tokens:
        tokens[0] = _resolve_cli_path(tokens[0])
    return tokens


def is_cli_available(command: list[str]) -> bool:
    if not command:
        return False
    # shutil.which 우선, 없으면 알려진 설치 경로 직접 확인
    if shutil.which(command[0]) is not None:
        return True

    import os

    cmd_name = command[0]
    if cmd_name == "claude":
        return any(os.path.isfile(p) and os.access(p, os.X_OK) for p in _claude_known_paths())
    return False


async def run_cli_prompt(command: list[str], prompt: str, timeout_seconds: int = 90) -> str:
    """
    CLI 명령을 실행하고 stdin으로 prompt를 전달한 뒤 stdout 텍스트를 반환합니다.
    """
    if not command:
        raise RuntimeError("CLI command is empty.")

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=prompt.encode("utf-8")),
            timeout=max(1, int(timeout_seconds)),
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError(f"CLI timeout after {timeout_seconds}s: {' '.join(command)}") from exc

    if process.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"CLI command failed (exit={process.returncode}): {' '.join(command)}; stderr={err}"
        )

    return stdout.decode("utf-8", errors="replace").strip()
