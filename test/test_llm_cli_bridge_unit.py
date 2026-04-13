"""
test/test_llm_cli_bridge_unit.py -- src/llm/cli_bridge.py 단위 테스트 (보강)

기존 test_llm_cli_bridge.py에 더해 edge case를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]


# ── build_cli_command ───────────────────────────────────────────────────────


class TestBuildCliCommand:
    def test_empty_template(self):
        from src.llm.cli_bridge import build_cli_command

        assert build_cli_command("", model="claude") == []

    def test_whitespace_template(self):
        from src.llm.cli_bridge import build_cli_command

        assert build_cli_command("   ", model="claude") == []

    def test_model_replacement(self):
        from src.llm.cli_bridge import build_cli_command

        cmd = build_cli_command("echo {model}", model="claude-3-5-sonnet")
        assert "claude-3-5-sonnet" in cmd

    def test_no_model_placeholder(self):
        from src.llm.cli_bridge import build_cli_command

        cmd = build_cli_command("echo hello", model="claude")
        assert cmd[1] == "hello"

    def test_quoted_arguments(self):
        from src.llm.cli_bridge import build_cli_command

        cmd = build_cli_command('echo "hello world"', model="claude")
        assert "hello world" in cmd

    def test_resolves_cli_path(self):
        from src.llm.cli_bridge import build_cli_command

        with patch("src.llm.cli_bridge._resolve_cli_path", return_value="/usr/local/bin/echo"):
            cmd = build_cli_command("echo test", model="claude")
            assert cmd[0] == "/usr/local/bin/echo"


# ── is_cli_available ────────────────────────────────────────────────────────


class TestIsCliAvailable:
    def test_empty_command(self):
        from src.llm.cli_bridge import is_cli_available

        assert is_cli_available([]) is False

    def test_known_binary(self):
        from src.llm.cli_bridge import is_cli_available

        assert is_cli_available(["cat"]) is True

    def test_nonexistent_binary(self):
        from src.llm.cli_bridge import is_cli_available

        with patch("shutil.which", return_value=None):
            assert is_cli_available(["definitely_not_a_real_binary_xyz"]) is False


# ── run_cli_prompt ──────────────────────────────────────────────────────────


class TestRunCliPrompt:
    @pytest.mark.asyncio
    async def test_empty_command_raises(self):
        from src.llm.cli_bridge import run_cli_prompt

        with pytest.raises(RuntimeError, match="empty"):
            await run_cli_prompt([], "test")

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        from src.llm.cli_bridge import run_cli_prompt

        result = await run_cli_prompt(["cat"], "hello world")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self):
        """타임아웃 시 프로세스가 종료되고 RuntimeError 발생."""
        from src.llm.cli_bridge import run_cli_prompt

        # sleep은 stdin을 무시하므로 타임아웃 테스트에 적합
        # timeout을 아주 짧게 설정
        with pytest.raises(RuntimeError, match="timeout"):
            await run_cli_prompt(["sleep", "10"], "test", timeout_seconds=1)

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self):
        """비정상 종료 시 RuntimeError 발생."""
        from src.llm.cli_bridge import run_cli_prompt

        with pytest.raises(RuntimeError, match="failed"):
            await run_cli_prompt(["false"], "test")

    @pytest.mark.asyncio
    async def test_minimum_timeout(self):
        """timeout_seconds가 1 미만이어도 최소 1초가 적용되는지 확인."""
        from src.llm.cli_bridge import run_cli_prompt

        # cat은 빠르게 반환하므로 timeout_seconds=0도 동작
        result = await run_cli_prompt(["cat"], "quick", timeout_seconds=0)
        assert result == "quick"


# ── run_cli_prompt_with_output_file ─────────────────────────────────────────


class TestRunCliPromptWithOutputFile:
    @pytest.mark.asyncio
    async def test_empty_command_raises(self):
        from src.llm.cli_bridge import run_cli_prompt_with_output_file

        with pytest.raises(RuntimeError, match="empty"):
            await run_cli_prompt_with_output_file([], "test")


# ── _resolve_cli_path ───────────────────────────────────────────────────────


class TestResolveCliPath:
    def test_found_via_which(self):
        from src.llm.cli_bridge import _resolve_cli_path

        with patch("shutil.which", return_value="/usr/bin/cat"):
            assert _resolve_cli_path("cat") == "/usr/bin/cat"

    def test_fallback_to_original(self):
        from src.llm.cli_bridge import _resolve_cli_path

        with patch("shutil.which", return_value=None):
            # not "claude" so no known paths fallback
            result = _resolve_cli_path("unknown_cmd")
            assert result == "unknown_cmd"


# ── _claude_known_paths ─────────────────────────────────────────────────────


class TestClaudeKnownPaths:
    def test_returns_list(self):
        from src.llm.cli_bridge import _claude_known_paths

        paths = _claude_known_paths()
        assert isinstance(paths, list)
        assert len(paths) > 0
        assert all(isinstance(p, str) for p in paths)

    def test_includes_home_path(self):
        from src.llm.cli_bridge import _claude_known_paths

        paths = _claude_known_paths()
        assert any(".claude/bin/claude" in p for p in paths)


# ── CLI Bridge 에지케이스 (Agent 4 QA Round 2) ───────────────────────────────


class TestRunCliPromptEdgeCases:
    """run_cli_prompt: 타임아웃, 프로세스 종료 코드, 대용량 출력."""

    @pytest.mark.asyncio
    async def test_stderr_included_in_error(self):
        """비정상 종료 시 stderr가 에러 메시지에 포함."""
        from src.llm.cli_bridge import run_cli_prompt

        # bash -c로 stderr에 출력 후 exit 1
        with pytest.raises(RuntimeError) as exc_info:
            await run_cli_prompt(
                ["bash", "-c", "echo 'error detail' >&2; exit 1"],
                "test",
            )

        error_msg = str(exc_info.value)
        assert "error detail" in error_msg
        assert "exit=1" in error_msg

    @pytest.mark.asyncio
    async def test_large_output_handled(self):
        """대용량 stdout을 정상 처리."""
        from src.llm.cli_bridge import run_cli_prompt

        # 10KB 문자열 생성
        large_input = "x" * 10000
        result = await run_cli_prompt(["cat"], large_input)
        assert len(result) == 10000

    @pytest.mark.asyncio
    async def test_utf8_output(self):
        """UTF-8 문자열이 정상적으로 디코딩."""
        from src.llm.cli_bridge import run_cli_prompt

        result = await run_cli_prompt(["cat"], "한글 테스트 데이터")
        assert result == "한글 테스트 데이터"

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        """빈 입력이면 빈 문자열 반환."""
        from src.llm.cli_bridge import run_cli_prompt

        result = await run_cli_prompt(["cat"], "")
        assert result == ""


class TestResolveCliPathEdgeCases:
    """_resolve_cli_path: claude 바이너리 폴백 경로 탐색."""

    def test_claude_command_checks_known_paths(self):
        """'claude' 명령어일 때 알려진 ��로를 탐색."""
        from src.llm.cli_bridge import _resolve_cli_path

        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=False):
                result = _resolve_cli_path("claude")
                # 알려진 경로 모두 없으면 원본 반환
                assert result == "claude"

    def test_non_claude_command_no_fallback(self):
        """claude가 아닌 명령어는 알려진 경로 탐색 없이 원본 반환."""
        from src.llm.cli_bridge import _resolve_cli_path

        with patch("shutil.which", return_value=None):
            result = _resolve_cli_path("some_other_cmd")
            assert result == "some_other_cmd"


class TestBuildCliCommandEdgeCases:
    """build_cli_command: None 템플릿, 특수문자."""

    def test_none_template(self):
        """template이 None이면 빈 리스트."""
        from src.llm.cli_bridge import build_cli_command

        result = build_cli_command(None, model="claude")
        assert result == []

    def test_multiple_model_placeholders(self):
        """여러 {model} 플레이스홀더가 모두 치환."""
        from src.llm.cli_bridge import build_cli_command

        cmd = build_cli_command("echo {model} {model}", model="claude-3")
        assert cmd[1] == "claude-3"
        assert cmd[2] == "claude-3"
