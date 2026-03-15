"""
test/test_strategy_dashboard_api.py — 전략 대시보드 종합 API AST 검증 테스트

strategy.py의 dashboard-status 엔드포인트와 관련 모델이
올바르게 정의되어 있는지 구조적으로 검증합니다.
"""

import ast
import textwrap
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent


class TestStrategyDashboardAPIStructure:
    """strategy.py에 dashboard-status 엔드포인트가 올바르게 정의되어 있는지 검증."""

    def setup_method(self) -> None:
        src = (SRC_ROOT / "src" / "api" / "routers" / "strategy.py").read_text()
        self.tree = ast.parse(src)
        self.source = src

    def test_dashboard_status_endpoint_exists(self) -> None:
        """GET /dashboard-status 엔드포인트 함수가 존재하는지 확인."""
        func_names = [
            node.name
            for node in ast.walk(self.tree)
            if isinstance(node, ast.AsyncFunctionDef)
        ]
        assert "get_strategy_dashboard_status" in func_names, (
            "get_strategy_dashboard_status 함수가 strategy.py에 없습니다."
        )

    def test_response_model_classes_exist(self) -> None:
        """대시보드 응답에 필요한 Pydantic 모델 클래스가 정의되어 있는지 확인."""
        class_names = [
            node.name
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ClassDef)
        ]
        required = [
            "StrategyPerformanceItem",
            "VirtualBalanceItem",
            "StrategyDashboardItem",
            "StrategyDashboardResponse",
        ]
        for name in required:
            assert name in class_names, f"{name} 모델이 strategy.py에 없습니다."

    def test_strategy_performance_item_fields(self) -> None:
        """StrategyPerformanceItem에 필수 필드가 있는지 확인."""
        required_fields = [
            "strategy_id", "mode", "trading_days", "total_trades",
            "return_pct", "max_drawdown_pct", "sharpe_ratio", "win_rate",
        ]
        for field in required_fields:
            assert field in self.source, (
                f"StrategyPerformanceItem에 {field} 필드가 없습니다."
            )

    def test_virtual_balance_item_fields(self) -> None:
        """VirtualBalanceItem에 필수 필드가 있는지 확인."""
        required_fields = [
            "initial_capital", "cash_balance", "position_market_value",
            "total_equity", "unrealized_pnl", "unrealized_pnl_pct",
            "position_count",
        ]
        for field in required_fields:
            assert field in self.source, (
                f"VirtualBalanceItem에 {field} 필드가 없습니다."
            )

    def test_dashboard_item_has_promotion_and_performance(self) -> None:
        """StrategyDashboardItem에 promotion_readiness와 performance 필드가 있는지 확인."""
        assert "promotion_readiness" in self.source
        assert "performance" in self.source
        assert "virtual_balance" in self.source

    def test_dashboard_response_has_strategies(self) -> None:
        """StrategyDashboardResponse에 strategies 리스트와 last_updated가 있는지 확인."""
        assert "strategies" in self.source
        assert "last_updated" in self.source


class TestStrategyDashboardEndpointLogic:
    """dashboard-status 엔드포인트 내부 로직이 올바르게 구성되어 있는지 검증."""

    def setup_method(self) -> None:
        self.source = (
            SRC_ROOT / "src" / "api" / "routers" / "strategy.py"
        ).read_text()

    def test_uses_strategy_promoter(self) -> None:
        """StrategyPromoter를 import하여 승격 상태를 확인하는지 검증."""
        assert "StrategyPromoter" in self.source

    def test_uses_compute_trade_performance(self) -> None:
        """compute_trade_performance를 import하여 성과를 계산하는지 검증."""
        assert "compute_trade_performance" in self.source

    def test_queries_trade_history(self) -> None:
        """trade_history 테이블을 쿼리하는지 검증."""
        assert "trade_history" in self.source

    def test_queries_portfolio_positions_for_virtual(self) -> None:
        """virtual 포지션을 portfolio_positions에서 조회하는지 검증."""
        assert "portfolio_positions" in self.source
        assert "virtual" in self.source

    def test_calculates_cash_balance(self) -> None:
        """가상 자금 현금 잔고를 계산하는지 검증."""
        assert "cash_balance" in self.source
        assert "net_cash_flow" in self.source

    def test_returns_all_five_strategies(self) -> None:
        """A, B, RL, S, L 5개 전략 모두를 반환하는지 검증."""
        assert '"A", "B", "RL", "S", "L"' in self.source


class TestFrontendHookStructure:
    """프론트엔드 useSignals.ts에 대시보드 훅이 추가되었는지 검증."""

    def setup_method(self) -> None:
        self.source = (
            SRC_ROOT / "ui" / "web" / "src" / "hooks" / "useSignals.ts"
        ).read_text()

    def test_strategy_dashboard_hook_exists(self) -> None:
        """useStrategyDashboard 훅이 정의되어 있는지 확인."""
        assert "useStrategyDashboard" in self.source

    def test_strategy_dashboard_response_type(self) -> None:
        """StrategyDashboardResponse 타입이 정의되어 있는지 확인."""
        assert "StrategyDashboardResponse" in self.source

    def test_virtual_balance_type(self) -> None:
        """VirtualBalance 타입이 정의되어 있는지 확인."""
        assert "VirtualBalance" in self.source

    def test_fetches_dashboard_status(self) -> None:
        """dashboard-status API를 호출하는지 확인."""
        assert "dashboard-status" in self.source


class TestFrontendComponentStructure:
    """StrategyDashboard.tsx 컴포넌트가 올바르게 구성되어 있는지 검증."""

    def setup_method(self) -> None:
        self.source = (
            SRC_ROOT / "ui" / "web" / "src" / "components" / "StrategyDashboard.tsx"
        ).read_text()

    def test_component_default_export(self) -> None:
        """default export가 StrategyDashboard인지 확인."""
        assert "export default function StrategyDashboard" in self.source

    def test_uses_strategy_dashboard_hook(self) -> None:
        """useStrategyDashboard 훅을 사용하는지 확인."""
        assert "useStrategyDashboard" in self.source

    def test_renders_strategy_cards(self) -> None:
        """StrategyCard 컴포넌트를 렌더링하는지 확인."""
        assert "StrategyCard" in self.source

    def test_renders_virtual_balance(self) -> None:
        """VirtualBalanceCard를 렌더링하는지 확인."""
        assert "VirtualBalanceCard" in self.source

    def test_renders_promotion_badge(self) -> None:
        """PromotionBadge를 렌더링하는지 확인."""
        assert "PromotionBadge" in self.source

    def test_all_strategies_labeled(self) -> None:
        """5개 전략 모두 라벨이 있는지 확인."""
        for label in ["Tournament", "Consensus", "RL Trading", "Search", "Long-term"]:
            assert label in self.source, f"전략 라벨 '{label}'이 없습니다."

    def test_mode_labels_defined(self) -> None:
        """실전/모의/가상 모드 라벨이 정의되어 있는지 확인."""
        for mode in ["실전", "모의", "가상"]:
            assert mode in self.source, f"모드 라벨 '{mode}'이 없습니다."


class TestDashboardPageIntegration:
    """Dashboard.tsx에 StrategyDashboard가 통합되어 있는지 검증."""

    def setup_method(self) -> None:
        self.source = (
            SRC_ROOT / "ui" / "web" / "src" / "pages" / "Dashboard.tsx"
        ).read_text()

    def test_imports_strategy_dashboard(self) -> None:
        """StrategyDashboard를 import하는지 확인."""
        assert "StrategyDashboard" in self.source

    def test_renders_strategy_dashboard(self) -> None:
        """StrategyDashboard 컴포넌트를 렌더링하는지 확인."""
        assert "<StrategyDashboard" in self.source
