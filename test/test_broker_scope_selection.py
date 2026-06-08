"""
test/test_broker_scope_selection.py — build_broker_for_scope() 브로커 선택 테스트

account_scope 값에 따라 올바른 브로커 팩토리가 호출되는지 검증합니다.
무거운 의존성(KIS API, Redis 등)은 sys.modules stub으로 우회합니다.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── 헬퍼: 무거운 의존성을 stub 모듈로 대체 ──────────────────────────────────

_STUB_MODULES = [
    "src.brokers.kis",
    "src.services.kis_session",
    "src.utils.redis_client",
]


@pytest.fixture(autouse=True)
def _broker_module_stubs():
    """KIS/Redis 등 무거운 의존성 모듈을 stub으로 대체합니다."""
    originals: dict[str, ModuleType | None] = {}

    for name in _STUB_MODULES:
        originals[name] = sys.modules.get(name)
        stub = ModuleType(name)
        sys.modules[name] = stub

    # KIS stub 속성
    kis_mod = sys.modules["src.brokers.kis"]
    for attr in [
        "KISPaperApiClient",
        "KISPaperBroker",
        "KISRealApiClient",
        "KISRealBroker",
    ]:
        setattr(kis_mod, attr, MagicMock())

    # redis_client stub 속성
    redis_mod = sys.modules["src.utils.redis_client"]
    for attr in ["TTL_KIS_TOKEN", "get_redis", "kis_oauth_token_key"]:
        setattr(redis_mod, attr, MagicMock())

    # kis_session stub 속성
    kis_session_mod = sys.modules["src.services.kis_session"]
    setattr(kis_session_mod, "ensure_kis_token", MagicMock())

    # src.brokers 모듈을 fresh로 로드
    sys.modules.pop("src.brokers", None)

    yield

    # 정리: src.brokers 캐시 제거 후 원래 모듈 복원
    sys.modules.pop("src.brokers", None)
    for name, orig in originals.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig


class TestBuildBrokerForScope:
    """build_broker_for_scope()가 scope에 따라 올바른 팩토리를 호출하는지 검증."""

    def test_paper_scope_calls_build_paper_broker(self):
        """scope='paper' → build_paper_broker가 호출된다."""
        import src.brokers as brokers_mod

        sentinel = object()
        with patch.object(brokers_mod, "build_paper_broker", return_value=sentinel) as mock_fn:
            result = brokers_mod.build_broker_for_scope("paper")

        assert result is sentinel
        mock_fn.assert_called_once()

    def test_virtual_scope_calls_build_virtual_broker(self):
        """scope='virtual' → build_virtual_broker가 호출된다."""
        import src.brokers as brokers_mod

        sentinel = object()
        with patch.object(
            brokers_mod, "build_virtual_broker", return_value=sentinel
        ) as mock_fn:
            result = brokers_mod.build_broker_for_scope("virtual")

        assert result is sentinel
        mock_fn.assert_called_once()

    def test_real_scope_calls_build_real_broker(self):
        """scope='real' → build_real_broker가 호출된다."""
        import src.brokers as brokers_mod

        sentinel = object()
        with patch.object(brokers_mod, "build_real_broker", return_value=sentinel) as mock_fn:
            result = brokers_mod.build_broker_for_scope("real")

        assert result is sentinel
        mock_fn.assert_called_once()

    def test_unknown_scope_defaults_to_paper(self):
        """알 수 없는 scope → normalize_account_scope에 의해 paper로 폴백."""
        import src.brokers as brokers_mod

        sentinel = object()
        with patch.object(brokers_mod, "build_paper_broker", return_value=sentinel) as mock_fn:
            result = brokers_mod.build_broker_for_scope("unknown")

        assert result is sentinel
        mock_fn.assert_called_once()

    def test_virtual_scope_passes_strategy_id(self):
        """scope='virtual'일 때 strategy_id 인자가 build_virtual_broker에 전달된다."""
        import src.brokers as brokers_mod

        sentinel = object()
        with patch.object(
            brokers_mod, "build_virtual_broker", return_value=sentinel
        ) as mock_fn:
            result = brokers_mod.build_broker_for_scope(
                "virtual", strategy_id="RL"
            )

        assert result is sentinel
        mock_fn.assert_called_once_with(strategy_id="RL")
