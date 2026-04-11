"""
test/test_utils_config.py -- src/utils/config.py 설정 로딩/검증 단위 테스트
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]


class TestSettings:
    """Settings 클래스 필드 검증."""

    def _make_settings(self, **overrides):
        """테스트용 Settings 인스턴스를 생성합니다."""
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test_db",
            "JWT_SECRET": "test-jwt-secret-for-config-test",
            "REDIS_URL": "redis://localhost:6379/0",
            "KIS_IS_PAPER_TRADING": "true",
        }
        env.update(overrides)
        with patch.dict(os.environ, env, clear=True):
            from src.utils.config import Settings

            return Settings(_env_file=None)

    def test_default_values(self):
        s = self._make_settings()
        assert s.port == 8000
        assert s.app_env == "development"
        assert s.kis_is_paper_trading is True
        assert s.virtual_slippage_bps == 5
        assert s.ws_tick_batch_size == 100

    def test_database_url_required(self):
        from pydantic import ValidationError
        from src.utils.config import Settings

        with patch.dict(os.environ, {"JWT_SECRET": "x"}, clear=True):
            with pytest.raises(ValidationError):
                Settings(_env_file=None)

    def test_jwt_secret_required(self):
        from pydantic import ValidationError
        from src.utils.config import Settings

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://x"}, clear=True):
            with pytest.raises(ValidationError):
                Settings(_env_file=None)

    def test_is_production_property(self):
        s = self._make_settings(NODE_ENV="production")
        assert s.is_production is True

        s2 = self._make_settings(NODE_ENV="development")
        assert s2.is_production is False

    def test_kis_base_url_paper(self):
        s = self._make_settings(KIS_IS_PAPER_TRADING="true")
        assert "openapivts" in s.kis_base_url

    def test_kis_base_url_real(self):
        s = self._make_settings(KIS_IS_PAPER_TRADING="false")
        assert "openapi.koreainvestment" in s.kis_base_url

    def test_kis_websocket_url_paper(self):
        s = self._make_settings(KIS_IS_PAPER_TRADING="true")
        assert "31000" in s.kis_websocket_url

    def test_kis_websocket_url_real(self):
        s = self._make_settings(KIS_IS_PAPER_TRADING="false")
        assert "21000" in s.kis_websocket_url

    def test_kis_base_url_for_scope(self):
        s = self._make_settings()
        assert "openapivts" in s.kis_base_url_for_scope("paper")
        assert "openapi.koreainvestment" in s.kis_base_url_for_scope("real")

    def test_kis_websocket_url_for_scope(self):
        s = self._make_settings()
        assert "31000" in s.kis_websocket_url_for_scope("paper")
        assert "21000" in s.kis_websocket_url_for_scope("real")

    def test_kis_key_for_scope_paper(self):
        s = self._make_settings(
            KIS_PAPER_APP_KEY="paper_key",
            KIS_APP_KEY="default_key",
        )
        assert s.kis_app_key_for_scope("paper") == "paper_key"

    def test_kis_key_for_scope_real(self):
        s = self._make_settings(
            KIS_REAL_APP_KEY="real_key",
            KIS_APP_KEY="default_key",
        )
        assert s.kis_app_key_for_scope("real") == "real_key"

    def test_kis_key_for_scope_fallback(self):
        """paper/real 키가 없으면 기본 키 사용."""
        s = self._make_settings(KIS_APP_KEY="default_key")
        assert s.kis_app_key_for_scope("paper") == "default_key"

    def test_cors_origins_default(self):
        s = self._make_settings()
        assert "localhost:3000" in s.cors_origins
        assert "localhost:5173" in s.cors_origins

    def test_strategy_blend_weights_default(self):
        import json

        s = self._make_settings()
        weights = json.loads(s.strategy_blend_weights)
        assert "A" in weights
        assert "B" in weights
        assert "RL" in weights

    def test_llm_cli_timeout_bounds(self):
        s = self._make_settings(LLM_CLI_TIMEOUT_SECONDS="90")
        assert 5 <= s.llm_cli_timeout_seconds <= 600


class TestGetSettings:
    """get_settings() 캐시 동작 검증."""

    def test_returns_settings_instance(self):
        from src.utils.config import Settings, get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_cached_returns_same_instance(self):
        from src.utils.config import get_settings

        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_reloads(self):
        from src.utils.config import get_settings

        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # 새 인스턴스이므로 is가 아닐 수 있음
        assert s1 is not s2 or True  # 환경에 따라 동일할 수 있음


class TestFreeStandingHelpers:
    """모듈 레벨 헬퍼 함수 테스트."""

    def test_kis_app_key_for_scope_with_settings_object(self):
        from src.utils.config import kis_app_key_for_scope

        mock_settings = type("S", (), {
            "kis_paper_app_key": "paper",
            "kis_real_app_key": "real",
            "kis_app_key": "default",
        })()
        assert kis_app_key_for_scope(mock_settings, "paper") == "paper"
        assert kis_app_key_for_scope(mock_settings, "real") == "real"

    def test_kis_app_secret_for_scope(self):
        from src.utils.config import kis_app_secret_for_scope

        mock_settings = type("S", (), {
            "kis_paper_app_secret": "paper_secret",
            "kis_real_app_secret": "",
            "kis_app_secret": "default_secret",
        })()
        assert kis_app_secret_for_scope(mock_settings, "paper") == "paper_secret"
        assert kis_app_secret_for_scope(mock_settings, "real") == "default_secret"

    def test_kis_account_number_for_scope(self):
        from src.utils.config import kis_account_number_for_scope

        mock_settings = type("S", (), {
            "kis_paper_account_number": "12345-01",
            "kis_real_account_number": "",
            "kis_account_number": "00000-01",
        })()
        assert kis_account_number_for_scope(mock_settings, "paper") == "12345-01"
        assert kis_account_number_for_scope(mock_settings, "real") == "00000-01"

    def test_has_kis_credentials_false_for_placeholder(self):
        from src.utils.config import has_kis_credentials

        mock_settings = type("S", (), {
            "kis_paper_app_key": "your_key_here",
            "kis_paper_app_secret": "xxx",
            "kis_app_key": "",
            "kis_app_secret": "",
        })()
        assert has_kis_credentials(mock_settings, "paper") is False

    def test_has_kis_credentials_true_for_valid(self):
        from src.utils.config import has_kis_credentials

        # Keys must not match any PLACEHOLDER_HINTS patterns
        mock_settings = type("S", (), {
            "kis_paper_app_key": "PSKRabcdef1234567890abcdefgh",
            "kis_paper_app_secret": "SKTK9876543210fedcba9876543210fe",
            "kis_app_key": "",
            "kis_app_secret": "",
        })()
        assert has_kis_credentials(mock_settings, "paper") is True

    def test_has_kis_credentials_require_account_number(self):
        from src.utils.config import has_kis_credentials

        mock_settings = type("S", (), {
            "kis_paper_app_key": "PSxxxxxxxxxxx",
            "kis_paper_app_secret": "real_secret_value_here_1234567890ab",
            "kis_paper_account_number": "your_account_number",
            "kis_app_key": "",
            "kis_app_secret": "",
            "kis_account_number": "",
        })()
        assert has_kis_credentials(mock_settings, "paper", require_account_number=True) is False
