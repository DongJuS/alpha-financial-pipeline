"""
test/test_docker_compose_env.py — docker-compose.prod.yml 환경변수 검증 테스트

프로덕션 compose 파일의 KIS_IS_PAPER_TRADING 환경변수가 서비스별로
올바르게 설정되어 있는지 YAML 파싱으로 확인합니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

# ── docker-compose.prod.yml의 !override 태그 처리 ─────────────────────────
# Docker Compose v2.24.6+에서 사용하는 !override 태그는
# PyYAML의 SafeLoader가 인식하지 못하므로 커스텀 constructor를 등록합니다.


class _ComposeLoader(yaml.SafeLoader):
    """Docker Compose의 !override 태그를 처리하는 커스텀 YAML 로더."""


def _override_constructor(loader: yaml.Loader, node: yaml.Node):
    """!override 태그가 붙은 노드를 일반 mapping으로 파싱합니다."""
    return loader.construct_mapping(node, deep=True)


_ComposeLoader.add_constructor("!override", _override_constructor)


def _load_prod_compose() -> dict:
    """docker-compose.prod.yml을 파싱하여 dict로 반환합니다."""
    path = Path(__file__).resolve().parent.parent / "docker-compose.prod.yml"
    if not path.exists():
        pytest.skip(f"docker-compose.prod.yml을 찾을 수 없습니다: {path}")
    with open(path) as f:
        return yaml.load(f, Loader=_ComposeLoader)


class TestDockerComposeEnv:
    """docker-compose.prod.yml의 KIS_IS_PAPER_TRADING 환경변수 검증."""

    @pytest.fixture(scope="class")
    def compose_data(self) -> dict:
        return _load_prod_compose()

    def test_tick_collector_is_paper_trading_false(self, compose_data: dict):
        """tick-collector는 실시세 수집용이므로 KIS_IS_PAPER_TRADING=false."""
        env = compose_data["services"]["tick-collector"]["environment"]
        value = str(env["KIS_IS_PAPER_TRADING"]).lower()
        assert value == "false", (
            f"tick-collector의 KIS_IS_PAPER_TRADING이 '{value}'이지만 'false'여야 합니다"
        )

    def test_worker_is_paper_trading_true(self, compose_data: dict):
        """worker는 모의투자 모드이므로 KIS_IS_PAPER_TRADING=true."""
        env = compose_data["services"]["worker"]["environment"]
        value = str(env["KIS_IS_PAPER_TRADING"]).lower()
        assert value == "true", (
            f"worker의 KIS_IS_PAPER_TRADING이 '{value}'이지만 'true'여야 합니다"
        )

    def test_api_is_paper_trading_true(self, compose_data: dict):
        """api는 모의투자 모드이므로 KIS_IS_PAPER_TRADING=true."""
        env = compose_data["services"]["api"]["environment"]
        value = str(env["KIS_IS_PAPER_TRADING"]).lower()
        assert value == "true", (
            f"api의 KIS_IS_PAPER_TRADING이 '{value}'이지만 'true'여야 합니다"
        )
