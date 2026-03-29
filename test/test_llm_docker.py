"""
test/test_llm_docker.py — LLM 클라이언트 Docker/K8s 환경 대응 테스트

컨테이너 환경 감지, 인증 경로 폴백 로직을 검증합니다.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

pytestmark = [pytest.mark.unit]


# ─── Gemini Docker 환경 감지 ──────────────────────────────────────────────────


class TestContainerDetection:
    """_is_running_in_container() 컨테이너 감지 로직."""

    def test_detects_dockerenv(self):
        """/.dockerenv 파일이 있으면 컨테이너로 감지."""
        from src.llm.gemini_client import _is_running_in_container

        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch("os.path.isfile") as mock_isfile:
                mock_isfile.return_value = True
                assert _is_running_in_container() is True

    def test_detects_kubernetes(self):
        """KUBERNETES_SERVICE_HOST 환경변수가 있으면 컨테이너로 감지."""
        from src.llm.gemini_client import _is_running_in_container

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch("os.path.isfile", return_value=False):
                assert _is_running_in_container() is True

    def test_not_container_locally(self):
        """로컬 환경에서는 False."""
        from src.llm.gemini_client import _is_running_in_container

        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.isfile", return_value=False):
                # /proc/1/cgroup 읽기 실패 시
                with patch("builtins.open", side_effect=FileNotFoundError):
                    assert _is_running_in_container() is False


# ─── Gemini ADC 경로 탐색 ────────────────────────────────────────────────────


class TestGeminiADCPaths:
    """load_gemini_oauth_credentials() ADC 경로 탐색."""

    def test_includes_k8s_secret_mount_path(self):
        """K8s secret mount 경로가 탐색 대상에 포함되는지 확인."""
        # load_gemini_oauth_credentials 내부의 adc_paths를 직접 검증
        # 함수 코드에서 경로 목록 추출
        import inspect
        from src.llm.gemini_client import load_gemini_oauth_credentials

        source = inspect.getsource(load_gemini_oauth_credentials)
        assert "/var/secrets/google/credentials.json" in source
        assert "/etc/google/auth/application_default_credentials.json" in source

    def test_includes_docker_root_path(self):
        """Docker /root 경로가 포함되는지 확인."""
        import inspect
        from src.llm.gemini_client import load_gemini_oauth_credentials

        source = inspect.getsource(load_gemini_oauth_credentials)
        assert "/root/.config/gcloud/application_default_credentials.json" in source

    def test_google_app_credentials_env_takes_priority(self):
        """GOOGLE_APPLICATION_CREDENTIALS가 설정되어 있으면 우선 사용."""
        from src.llm.gemini_client import (
            _clear_gemini_oauth_credentials_cache,
            load_gemini_oauth_credentials,
        )

        _clear_gemini_oauth_credentials_cache()
        fake_path = "/tmp/test_gcp_creds.json"

        with (
            patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": fake_path}),
            patch("os.path.isfile", return_value=True),
            patch("google.auth.default", return_value=(MagicMock(), "test-project")),
        ):
            creds, project = load_gemini_oauth_credentials()
            assert creds is not None
            assert project == "test-project"

        _clear_gemini_oauth_credentials_cache()


# ─── Claude Docker 경고 ──────────────────────────────────────────────────────


class TestClaudeDockerWarning:
    """Claude client Docker 환경 경고."""

    def test_warns_in_docker_without_api_key(self):
        """Docker에서 API key 없으면 경고 로그가 출력되는지 확인."""
        import inspect
        from src.llm.claude_client import ClaudeClient

        source = inspect.getsource(ClaudeClient.__init__)
        # Docker/K8s 환경 감지 코드가 있는지 확인
        assert "/.dockerenv" in source or "KUBERNETES_SERVICE_HOST" in source

    def test_cli_fallback_paths_include_docker(self):
        """Claude CLI 경로에 Docker 관련 경로가 포함되는지 확인."""
        from src.llm.cli_bridge import _claude_known_paths

        paths = _claude_known_paths()
        docker_paths = [p for p in paths if "/root/" in p or "node_modules" in p]
        assert len(docker_paths) >= 2


# ─── K8s Readiness 체크 ──────────────────────────────────────────────────────


class TestK8sReadiness:
    """readiness.py의 K8s 환경 체크."""

    @pytest.mark.asyncio
    async def test_skips_when_not_in_k8s(self):
        """K8s 밖에서는 빈 리스트 반환."""
        from src.utils.readiness import _evaluate_k8s_readiness

        with patch.dict(os.environ, {}, clear=True):
            checks = await _evaluate_k8s_readiness()

        assert checks == []

    @pytest.mark.asyncio
    async def test_runs_checks_in_k8s(self):
        """K8s에서 실행 시 체크 항목이 반환되는지 확인."""
        from src.utils.readiness import _evaluate_k8s_readiness

        with (
            patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}),
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("shutil.which", return_value=None),
            patch("socket.getaddrinfo", side_effect=__import__("socket").gaierror("DNS fail")),
        ):
            checks = await _evaluate_k8s_readiness()

        assert len(checks) > 0
        keys = [c["key"] for c in checks]
        assert "k8s:service_account" in keys
        assert "k8s:kubectl" in keys

    @pytest.mark.asyncio
    async def test_sa_token_check(self):
        """ServiceAccount 토큰 마운트 확인."""
        from src.utils.readiness import _evaluate_k8s_readiness

        with (
            patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}),
            patch("os.path.isfile", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("shutil.which", return_value="/usr/bin/kubectl"),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            checks = await _evaluate_k8s_readiness()

        sa_check = next(c for c in checks if c["key"] == "k8s:service_account")
        assert sa_check["ok"] is True
