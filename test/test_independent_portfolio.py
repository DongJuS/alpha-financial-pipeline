"""
test/test_independent_portfolio.py — Phase 2: Independent Portfolio per Strategy 통합 테스트

테스트 대상:
- AccountScope 'virtual' 확장
- VirtualBroker 구조
- PortfolioManagerAgent strategy_id 기반 격리
- OrchestratorAgent --independent-portfolio 모드
- PaperOrderRequest strategy_id 필드
- build_broker_for_scope virtual 분기
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ────────────────────────── AccountScope Tests ──────────────────────────


class TestAccountScopeVirtual:
    """AccountScope에 'virtual' 값이 올바르게 추가되었는지 검증."""

    def test_normalize_virtual(self):
        from src.utils.account_scope import normalize_account_scope
        assert normalize_account_scope("virtual") == "virtual"

    def test_normalize_paper_default(self):
        from src.utils.account_scope import normalize_account_scope
        assert normalize_account_scope(None) == "paper"
        assert normalize_account_scope("unknown") == "paper"

    def test_normalize_real(self):
        from src.utils.account_scope import normalize_account_scope
        assert normalize_account_scope("real") == "real"

    def test_is_virtual_scope(self):
        from src.utils.account_scope import is_virtual_scope
        assert is_virtual_scope("virtual") is True
        assert is_virtual_scope("paper") is False
        assert is_virtual_scope(None) is False

    def test_valid_scopes_set(self):
        from src.utils.account_scope import VALID_SCOPES
        assert "virtual" in VALID_SCOPES
        assert "paper" in VALID_SCOPES
        assert "real" in VALID_SCOPES


# ────────────────────────── PaperOrderRequest Tests ──────────────────────────


class TestPaperOrderRequestStrategyId:
    """PaperOrderRequest에 strategy_id 필드가 올바르게 추가되었는지 검증."""

    def test_strategy_id_default_none(self):
        from src.db.models import PaperOrderRequest
        order = PaperOrderRequest(
            ticker="005930", name="삼성전자", signal="BUY", price=70000,
        )
        assert order.strategy_id is None

    def test_strategy_id_explicit(self):
        from src.db.models import PaperOrderRequest
        order = PaperOrderRequest(
            ticker="005930", name="삼성전자", signal="BUY", price=70000,
            strategy_id="RL",
        )
        assert order.strategy_id == "RL"

    def test_extended_signal_source(self):
        from src.db.models import PaperOrderRequest
        for source in ["A", "B", "BLEND", "RL", "S", "L", "EXIT", "VIRTUAL"]:
            order = PaperOrderRequest(
                ticker="005930", name="삼성전자", signal="BUY", price=70000,
                signal_source=source,
            )
            assert order.signal_source == source


# ────────────────────────── Build Broker Tests ──────────────────────────


class TestBuildBrokerForScope:
    """build_broker_for_scope가 virtual 분기를 올바르게 처리하는지 검증."""

    def test_build_virtual_broker(self):
        from src.brokers import build_virtual_broker
        from src.brokers.virtual_broker import VirtualBroker
        broker = build_virtual_broker()
        assert isinstance(broker, VirtualBroker)

    @patch("src.brokers.get_settings")
    def test_build_broker_for_scope_virtual(self, mock_settings):
        mock_settings.return_value = MagicMock(paper_broker_backend="internal")
        from src.brokers import build_broker_for_scope
        from src.brokers.virtual_broker import VirtualBroker
        broker = build_broker_for_scope("virtual")
        assert isinstance(broker, VirtualBroker)


# ────────────────────────── VirtualBroker Tests ──────────────────────────


class TestVirtualBroker:
    """VirtualBroker 기본 구조 테스트."""

    def test_init(self):
        from src.brokers.virtual_broker import VirtualBroker
        broker = VirtualBroker()
        assert broker.broker_name == "virtual"

    def test_init_custom_name(self):
        from src.brokers.virtual_broker import VirtualBroker
        broker = VirtualBroker(broker_name="test-virtual")
        assert broker.broker_name == "test-virtual"


# ────────────────────────── PortfolioManager Tests ──────────────────────────


class TestPortfolioManagerStrategyId:
    """PortfolioManagerAgent strategy_id 격리 검증."""

    def test_init_default(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent
        pm = PortfolioManagerAgent()
        assert pm.strategy_id is None
        assert pm.agent_id == "portfolio_manager_agent"

    def test_init_with_strategy_id(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent
        pm = PortfolioManagerAgent(agent_id="pm_rl", strategy_id="RL")
        assert pm.strategy_id == "RL"
        assert pm.agent_id == "pm_rl"

    def test_virtual_broker_initialized(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent
        from src.brokers.virtual_broker import VirtualBroker
        pm = PortfolioManagerAgent(strategy_id="A")
        assert hasattr(pm, "virtual_broker")
        assert isinstance(pm.virtual_broker, VirtualBroker)

    def test_enabled_scopes_with_strategy_id(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent

        with patch("src.agents.portfolio_manager.get_settings") as mock:
            settings = MagicMock()
            settings.strategy_modes = json.dumps({
                "A": ["virtual"],
                "B": ["virtual", "paper"],
                "RL": ["virtual"],
            })
            mock.return_value = settings

            scopes_a = PortfolioManagerAgent._enabled_account_scopes_from_config(
                {}, strategy_id="A",
            )
            assert scopes_a == ["virtual"]

            scopes_b = PortfolioManagerAgent._enabled_account_scopes_from_config(
                {}, strategy_id="B",
            )
            assert scopes_b == ["virtual", "paper"]

    def test_enabled_scopes_no_strategy_id(self):
        """strategy_id=None일 때 기존 동작(paper/real)을 유지."""
        from src.agents.portfolio_manager import PortfolioManagerAgent
        cfg = {"enable_paper_trading": True, "enable_real_trading": False, "primary_account_scope": "paper"}
        scopes = PortfolioManagerAgent._enabled_account_scopes_from_config(cfg)
        assert "paper" in scopes
        assert "virtual" not in scopes

    def test_broker_for_scope_virtual(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent
        from src.brokers.virtual_broker import VirtualBroker
        virtual = VirtualBroker()
        paper = MagicMock()
        real = MagicMock()
        result = PortfolioManagerAgent._broker_for_scope("virtual", paper, real, virtual)
        assert result is virtual

    def test_broker_for_scope_paper(self):
        from src.agents.portfolio_manager import PortfolioManagerAgent
        virtual = MagicMock()
        paper = MagicMock()
        real = MagicMock()
        result = PortfolioManagerAgent._broker_for_scope("paper", paper, real, virtual)
        assert result is paper


# ────────────────────────── Orchestrator Tests ──────────────────────────


class TestOrchestratorIndependentPortfolio:
    """OrchestratorAgent --independent-portfolio 모드 검증."""

    @patch("src.agents.orchestrator.get_settings")
    @patch("src.agents.orchestrator.RLTradingAgent")
    @patch("src.agents.orchestrator.RLPolicyStoreV2")
    @patch("src.agents.orchestrator.RLPolicyStore")
    def test_independent_portfolio_init(self, mock_rps, mock_rps2, mock_rl, mock_settings):
        mock_settings.return_value = MagicMock(
            strategy_blend_weights='{"A": 0.5, "B": 0.5}',
        )
        from src.agents.orchestrator import OrchestratorAgent
        agent = OrchestratorAgent(
            strategies=["A", "B"],
            independent_portfolio=True,
        )
        assert agent.independent_portfolio is True
        assert "A" in agent._strategy_portfolios
        assert "B" in agent._strategy_portfolios
        assert agent._strategy_portfolios["A"].strategy_id == "A"
        assert agent._strategy_portfolios["B"].strategy_id == "B"

    @patch("src.agents.orchestrator.get_settings")
    @patch("src.agents.orchestrator.RLTradingAgent")
    @patch("src.agents.orchestrator.RLPolicyStoreV2")
    @patch("src.agents.orchestrator.RLPolicyStore")
    def test_non_independent_portfolio_init(self, mock_rps, mock_rps2, mock_rl, mock_settings):
        mock_settings.return_value = MagicMock(
            strategy_blend_weights='{"A": 0.5, "B": 0.5}',
        )
        from src.agents.orchestrator import OrchestratorAgent
        agent = OrchestratorAgent(
            strategies=["A", "B"],
            independent_portfolio=False,
        )
        assert agent.independent_portfolio is False
        assert len(agent._strategy_portfolios) == 0


# ────────────────────────── Config Tests ──────────────────────────


class TestConfigIndependentPortfolio:
    """config.py에 독립 포트폴리오 설정이 올바르게 추가되었는지 검증."""

    def test_settings_has_strategy_modes(self):
        from src.utils.config import Settings
        s = Settings()
        modes = json.loads(s.strategy_modes)
        assert isinstance(modes, dict)
        assert "A" in modes
        assert "RL" in modes

    def test_settings_has_capital_allocation(self):
        from src.utils.config import Settings
        s = Settings()
        alloc = json.loads(s.strategy_capital_allocation)
        assert isinstance(alloc, dict)
        assert alloc.get("A") == 2000000

    def test_settings_virtual_initial_capital(self):
        from src.utils.config import Settings
        s = Settings()
        assert s.virtual_initial_capital == 10_000_000
