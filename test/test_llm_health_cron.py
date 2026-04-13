"""
test/test_llm_health_cron.py — LLM auth health check 크론 + usage mode 추적 테스트
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ────────────────────────────────────────────────────────────────────────────
# reserve_provider_call mode 추적 테스트
# ────────────────────────────────────────────────────────────────────────────


class TestReserveProviderCallMode:
    """reserve_provider_call에 mode 파라미터가 올바르게 동작하는지 검증."""

    async def test_mode_cli_records_separate_redis_key(
        self, mock_redis: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mode='cli' 전달 시 별도 Redis 키에 카운트가 기록된다."""
        # Lua eval → (allowed=1, count=1)
        mock_redis.eval = AsyncMock(return_value=[1, 1])
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        monkeypatch.setattr(
            "src.services.llm_usage_limiter.get_redis",
            AsyncMock(return_value=mock_redis),
        )

        # Settings mock
        settings = MagicMock()
        settings.llm_daily_provider_limit = 100
        settings.llm_usage_timezone = "Asia/Seoul"
        monkeypatch.setattr(
            "src.services.llm_usage_limiter.get_settings",
            lambda: settings,
        )

        from src.services.llm_usage_limiter import reserve_provider_call

        count, limit = await reserve_provider_call("claude", mode="cli")

        assert count == 1
        assert limit == 100

        # mode별 키에 incr이 호출되었는지 확인
        incr_calls = mock_redis.incr.call_args_list
        assert len(incr_calls) == 1
        mode_key = incr_calls[0][0][0]
        assert "llm:mode:claude:cli:daily:" in mode_key

        # expire도 호출되었는지 확인
        expire_calls = mock_redis.expire.call_args_list
        assert len(expire_calls) == 1
        assert expire_calls[0][0][0] == mode_key

    async def test_mode_defaults_to_unknown(
        self, mock_redis: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mode 미지정 시 'unknown'으로 기록된다."""
        mock_redis.eval = AsyncMock(return_value=[1, 1])
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        monkeypatch.setattr(
            "src.services.llm_usage_limiter.get_redis",
            AsyncMock(return_value=mock_redis),
        )

        settings = MagicMock()
        settings.llm_daily_provider_limit = 100
        settings.llm_usage_timezone = "Asia/Seoul"
        monkeypatch.setattr(
            "src.services.llm_usage_limiter.get_settings",
            lambda: settings,
        )

        from src.services.llm_usage_limiter import reserve_provider_call

        await reserve_provider_call("gemini")

        incr_calls = mock_redis.incr.call_args_list
        assert len(incr_calls) == 1
        mode_key = incr_calls[0][0][0]
        assert "llm:mode:gemini:unknown:daily:" in mode_key


# ────────────────────────────────────────────────────────────────────────────
# check_llm_auth_health 테스트
# ────────────────────────────────────────────────────────────────────────────


class TestCheckLlmAuthHealth:
    """check_llm_auth_health 함수의 상태 수집·저장·알림 로직 검증."""

    @pytest.fixture
    def mock_redis_for_health(self) -> AsyncMock:
        """health check용 Redis mock."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)
        return redis

    async def test_collects_provider_status_and_stores_in_redis(
        self,
        mock_redis_for_health: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """각 provider 상태를 수집하고 Redis에 JSON으로 저장한다."""
        monkeypatch.setattr(
            "src.utils.redis_client.get_redis",
            AsyncMock(return_value=mock_redis_for_health),
        )

        # Claude: cli 사용 가능
        monkeypatch.setattr(
            "src.llm.cli_bridge.build_cli_command",
            lambda template, model: ["claude", "--model", model],
        )
        monkeypatch.setattr(
            "src.llm.cli_bridge.is_cli_available",
            lambda cmd: True,
        )
        settings = MagicMock()
        settings.anthropic_cli_command = "claude"
        settings.anthropic_api_key = ""
        settings.openai_api_key = ""
        monkeypatch.setattr(
            "src.utils.config.get_settings",
            lambda: settings,
        )

        # Codex: API key만 있음
        monkeypatch.setattr(
            "src.llm.gpt_client.load_codex_auth_status",
            lambda: {
                "exists": False,
                "has_access_token": False,
                "has_refresh_token": False,
                "has_api_key": False,
            },
        )
        settings.openai_api_key = "sk-real-key-12345678"
        monkeypatch.setattr(
            "src.utils.secret_validation.is_placeholder_secret",
            lambda v: False,
        )

        # Gemini: oauth 사용 가능
        monkeypatch.setattr(
            "src.llm.gemini_client.gemini_oauth_available",
            lambda: True,
        )

        # Notifier mock (상태 변경 시 호출되므로)
        mock_notifier = MagicMock()
        mock_notifier.send = AsyncMock()
        monkeypatch.setattr(
            "src.agents.notifier.NotifierAgent",
            lambda: mock_notifier,
        )

        from src.schedulers.unified_scheduler import check_llm_auth_health

        result = await check_llm_auth_health()

        assert result["claude"] == "cli_ok"
        assert result["codex"] == "api_key_only"
        assert result["gemini"] == "oauth_ok"

        # Redis에 저장 확인
        set_calls = mock_redis_for_health.set.call_args_list
        assert len(set_calls) == 1
        stored_key = set_calls[0][0][0]
        stored_value = json.loads(set_calls[0][0][1])
        assert stored_key == "llm:auth:health"
        assert stored_value["claude"] == "cli_ok"
        assert stored_value["gemini"] == "oauth_ok"
        # TTL 5분
        assert set_calls[0][1]["ex"] == 300

    async def test_detects_status_change_and_sends_notification(
        self,
        mock_redis_for_health: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """이전 상태와 현재 상태가 다르면 NotifierAgent.send()를 호출한다."""
        # 이전 상태: claude=cli_ok, codex=cli_ok, gemini=oauth_ok
        prev_status = json.dumps({
            "claude": "cli_ok",
            "codex": "cli_ok",
            "gemini": "oauth_ok",
        })
        mock_redis_for_health.get = AsyncMock(return_value=prev_status)

        monkeypatch.setattr(
            "src.utils.redis_client.get_redis",
            AsyncMock(return_value=mock_redis_for_health),
        )

        # 현재 상태: claude=unavailable (변경!), codex=cli_ok (동일), gemini=unavailable (변경!)
        settings = MagicMock()
        settings.anthropic_cli_command = ""
        settings.anthropic_api_key = ""
        settings.openai_api_key = ""
        monkeypatch.setattr(
            "src.utils.config.get_settings",
            lambda: settings,
        )
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "")

        monkeypatch.setattr(
            "src.llm.cli_bridge.build_cli_command",
            lambda template, model: [],
        )
        monkeypatch.setattr(
            "src.llm.cli_bridge.is_cli_available",
            lambda cmd: False,
        )
        monkeypatch.setattr(
            "src.utils.secret_validation.is_placeholder_secret",
            lambda v: True,
        )

        # Codex: cli_ok
        monkeypatch.setattr(
            "src.llm.gpt_client.load_codex_auth_status",
            lambda: {
                "exists": True,
                "has_access_token": True,
                "has_refresh_token": True,
                "has_api_key": False,
            },
        )

        # Gemini: unavailable
        monkeypatch.setattr(
            "src.llm.gemini_client.gemini_oauth_available",
            lambda: False,
        )

        mock_notifier = MagicMock()
        mock_notifier.send = AsyncMock()
        monkeypatch.setattr(
            "src.agents.notifier.NotifierAgent",
            lambda: mock_notifier,
        )

        from src.schedulers.unified_scheduler import check_llm_auth_health

        result = await check_llm_auth_health()

        assert result["claude"] == "unavailable"
        assert result["codex"] == "cli_ok"
        assert result["gemini"] == "unavailable"

        # 알림 전송 확인 (claude, gemini 변경됨)
        mock_notifier.send.assert_awaited_once()
        call_args = mock_notifier.send.call_args
        assert call_args[0][0] == "llm_auth_health"
        msg = call_args[0][1]
        assert "claude" in msg
        assert "gemini" in msg
        # codex는 변경 없으므로 알림에 포함되지 않아야 함
        assert "codex" not in msg

    async def test_no_notification_when_status_unchanged(
        self,
        mock_redis_for_health: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """상태 변경이 없으면 알림을 보내지 않는다."""
        # 이전 상태 = 현재 상태와 동일하게 설정
        prev_status = json.dumps({
            "claude": "unavailable",
            "codex": "unavailable",
            "gemini": "unavailable",
        })
        mock_redis_for_health.get = AsyncMock(return_value=prev_status)

        monkeypatch.setattr(
            "src.utils.redis_client.get_redis",
            AsyncMock(return_value=mock_redis_for_health),
        )

        settings = MagicMock()
        settings.anthropic_cli_command = ""
        settings.anthropic_api_key = ""
        settings.openai_api_key = ""
        monkeypatch.setattr(
            "src.utils.config.get_settings",
            lambda: settings,
        )
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "")

        monkeypatch.setattr(
            "src.llm.cli_bridge.build_cli_command",
            lambda template, model: [],
        )
        monkeypatch.setattr(
            "src.llm.cli_bridge.is_cli_available",
            lambda cmd: False,
        )
        monkeypatch.setattr(
            "src.utils.secret_validation.is_placeholder_secret",
            lambda v: True,
        )
        monkeypatch.setattr(
            "src.llm.gpt_client.load_codex_auth_status",
            lambda: {
                "exists": False,
                "has_access_token": False,
                "has_refresh_token": False,
                "has_api_key": False,
            },
        )
        monkeypatch.setattr(
            "src.llm.gemini_client.gemini_oauth_available",
            lambda: False,
        )

        mock_notifier = MagicMock()
        mock_notifier.send = AsyncMock()
        monkeypatch.setattr(
            "src.agents.notifier.NotifierAgent",
            lambda: mock_notifier,
        )

        from src.schedulers.unified_scheduler import check_llm_auth_health

        result = await check_llm_auth_health()

        assert result["claude"] == "unavailable"
        assert result["codex"] == "unavailable"
        assert result["gemini"] == "unavailable"

        # 알림 미전송 확인
        mock_notifier.send.assert_not_awaited()

    async def test_handles_provider_check_exception_gracefully(
        self,
        mock_redis_for_health: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """provider 체크 중 예외 발생 시 error 상태를 기록하고 계속 진행한다."""
        monkeypatch.setattr(
            "src.utils.redis_client.get_redis",
            AsyncMock(return_value=mock_redis_for_health),
        )

        # Claude: 예외 발생
        def _raise_import_error(template, model):
            raise ImportError("cli_bridge not found")

        monkeypatch.setattr(
            "src.llm.cli_bridge.build_cli_command",
            _raise_import_error,
        )

        settings = MagicMock()
        settings.anthropic_cli_command = "claude"
        settings.anthropic_api_key = ""
        settings.openai_api_key = ""
        monkeypatch.setattr(
            "src.utils.config.get_settings",
            lambda: settings,
        )

        # Codex: 정상
        monkeypatch.setattr(
            "src.llm.gpt_client.load_codex_auth_status",
            lambda: {
                "exists": False,
                "has_access_token": False,
                "has_refresh_token": False,
                "has_api_key": False,
            },
        )
        monkeypatch.setattr(
            "src.utils.secret_validation.is_placeholder_secret",
            lambda v: True,
        )

        # Gemini: 정상
        monkeypatch.setattr(
            "src.llm.gemini_client.gemini_oauth_available",
            lambda: False,
        )

        mock_notifier = MagicMock()
        mock_notifier.send = AsyncMock()
        monkeypatch.setattr(
            "src.agents.notifier.NotifierAgent",
            lambda: mock_notifier,
        )

        from src.schedulers.unified_scheduler import check_llm_auth_health

        result = await check_llm_auth_health()

        # Claude는 error 상태
        assert result["claude"].startswith("error:")
        assert "cli_bridge not found" in result["claude"]
        # 나머지는 정상 처리
        assert result["codex"] == "unavailable"
        assert result["gemini"] == "unavailable"
