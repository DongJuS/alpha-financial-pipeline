"""
test/test_orchestrator_independent.py — Tests for Orchestrator independent portfolio mode

테스트 전략:
- AST/import 기반 정적 검증 (실제 DB 불필요)
- --independent-portfolio 플래그 존재 확인
- 관련 클래스/메서드 존재 확인
- 타입 힌트 검증
"""
from __future__ import annotations

import argparse
import ast
import inspect
from pathlib import Path
from typing import Any

import pytest


# ── 테스트용 헬퍼 ──


def get_source_file(module_name: str) -> Path:
    """모듈 이름으로부터 소스 파일 경로를 가져옵니다."""
    root = Path(__file__).resolve().parents[1]
    if module_name.startswith("src."):
        parts = module_name.split(".")
        return root / "/".join(parts[:-1]) / f"{parts[-1]}.py"
    return root / f"{module_name}.py"


def parse_source_ast(file_path: Path) -> ast.Module:
    """소스 파일을 AST로 파싱합니다."""
    with open(file_path, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=str(file_path))


def find_class_in_ast(tree: ast.Module, class_name: str) -> ast.ClassDef | None:
    """AST에서 클래스를 찾습니다."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def find_method_in_class(
    class_def: ast.ClassDef,
    method_name: str,
) -> ast.FunctionDef | None:
    """클래스 내에서 메서드를 찾습니다."""
    for node in class_def.body:
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return node
    return None


def get_function_args(func_def: ast.FunctionDef) -> list[str]:
    """함수의 인자 목록을 반환합니다."""
    return [arg.arg for arg in func_def.args.args]


def get_class_init_args(class_def: ast.ClassDef) -> dict[str, Any]:
    """클래스의 __init__ 인자를 분석합니다."""
    init = find_method_in_class(class_def, "__init__")
    if not init:
        return {}

    args = {}
    for arg, default in zip(
        reversed(init.args.args),
        reversed(init.args.defaults or []),
    ):
        if arg.arg != "self":
            default_val = None
            if isinstance(default, ast.Constant):
                default_val = default.value
            elif isinstance(default, ast.NameConstant):
                default_val = default.value
            args[arg.arg] = default_val

    # 기본값 없는 인자들
    num_defaults = len(init.args.defaults or [])
    args_without_defaults = init.args.args[1 : len(init.args.args) - num_defaults]
    for arg in args_without_defaults:
        if arg.arg != "self":
            args[arg.arg] = ...  # Sentinel value

    return args


def check_imports_in_ast(tree: ast.Module, import_names: list[str]) -> dict[str, bool]:
    """AST에서 특정 임포트의 존재를 확인합니다."""
    result = {name: False for name in import_names}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full_name = f"{module}.{alias.name}".lstrip(".")
                for import_name in import_names:
                    if import_name in full_name or full_name in import_name:
                        result[import_name] = True

        elif isinstance(node, ast.Import):
            for alias in node.names:
                for import_name in import_names:
                    if import_name in alias.name:
                        result[import_name] = True

    return result


# ────────────────────────────── 테스트 클래스 ──────────────────────────────


class TestOrchestratorIndependentPortfolioInit:
    """독립 포트폴리오 모드 __init__ 인자 검증"""

    def test_orchestrator_has_independent_portfolio_parameter(self) -> None:
        """OrchestratorAgent.__init__에 independent_portfolio 파라미터가 있는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)
        orch_class = find_class_in_ast(tree, "OrchestratorAgent")

        assert orch_class is not None, "OrchestratorAgent 클래스를 찾을 수 없습니다."

        init_args = get_class_init_args(orch_class)
        assert (
            "independent_portfolio" in init_args
        ), (
            "independent_portfolio 파라미터가 __init__에 없습니다. "
            f"현재 인자: {list(init_args.keys())}"
        )

    def test_orchestrator_strategy_portfolios_dict_created(self) -> None:
        """OrchestratorAgent가 _strategy_portfolios 딕셔너리를 생성하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)
        orch_class = find_class_in_ast(tree, "OrchestratorAgent")

        assert orch_class is not None

        init_method = find_method_in_class(orch_class, "__init__")
        assert init_method is not None

        # AST에서 _strategy_portfolios 할당 찾기
        source_code = ast.get_source_segment(
            open(file_path, "r", encoding="utf-8").read(), init_method
        )
        assert (
            "_strategy_portfolios" in source_code
        ), "_strategy_portfolios 인스턴스 변수가 __init__에 없습니다."

    def test_orchestrator_strategy_virtual_brokers_dict_created(self) -> None:
        """OrchestratorAgent가 _strategy_virtual_brokers 딕셔너리를 생성하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)
        orch_class = find_class_in_ast(tree, "OrchestratorAgent")

        assert orch_class is not None

        init_method = find_method_in_class(orch_class, "__init__")
        assert init_method is not None

        source_code = ast.get_source_segment(
            open(file_path, "r", encoding="utf-8").read(), init_method
        )
        assert (
            "_strategy_virtual_brokers" in source_code
        ), (
            "_strategy_virtual_brokers 인스턴스 변수가 __init__에 없습니다."
        )


class TestOrchestratorMethods:
    """OrchestratorAgent의 필수 메서드 검증"""

    def test_get_portfolio_for_strategy_exists(self) -> None:
        """_get_portfolio_for_strategy 메서드가 존재하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)
        orch_class = find_class_in_ast(tree, "OrchestratorAgent")

        assert orch_class is not None
        method = find_method_in_class(orch_class, "_get_portfolio_for_strategy")
        assert (
            method is not None
        ), "_get_portfolio_for_strategy 메서드가 없습니다."

        args = get_function_args(method)
        assert "strategy_id" in args, "strategy_id 파라미터가 없습니다."

    def test_get_virtual_broker_for_strategy_exists(self) -> None:
        """_get_virtual_broker_for_strategy 메서드가 존재하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)
        orch_class = find_class_in_ast(tree, "OrchestratorAgent")

        assert orch_class is not None
        method = find_method_in_class(
            orch_class, "_get_virtual_broker_for_strategy"
        )
        assert (
            method is not None
        ), "_get_virtual_broker_for_strategy 메서드가 없습니다."

        args = get_function_args(method)
        assert "strategy_id" in args, "strategy_id 파라미터가 없습니다."

    def test_run_cycle_exists(self) -> None:
        """run_cycle 메서드가 존재하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)
        orch_class = find_class_in_ast(tree, "OrchestratorAgent")

        assert orch_class is not None
        method = find_method_in_class(orch_class, "run_cycle")
        assert method is not None, "run_cycle 메서드가 없습니다."


class TestAggregateRiskIntegration:
    """AggregateRiskMonitor 통합 검증"""

    def test_aggregate_risk_monitor_imported_in_orchestrator(self) -> None:
        """OrchestratorAgent가 AggregateRiskMonitor를 임포트하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)

        imports = check_imports_in_ast(tree, ["AggregateRiskMonitor"])
        assert imports["AggregateRiskMonitor"], (
            "AggregateRiskMonitor가 orchestrator.py에 임포트되지 않았습니다."
        )

    def test_aggregate_risk_monitor_file_exists(self) -> None:
        """AggregateRiskMonitor가 정의된 파일이 존재하는지 확인합니다."""
        file_path = Path(__file__).resolve().parents[1] / "src" / "utils" / "aggregate_risk.py"

        if not file_path.exists():
            pytest.skip(
                f"aggregate_risk.py 파일이 아직 생성되지 않았습니다: {file_path}"
            )

        tree = parse_source_ast(file_path)
        risk_class = find_class_in_ast(tree, "AggregateRiskMonitor")
        assert (
            risk_class is not None
        ), "AggregateRiskMonitor 클래스가 aggregate_risk.py에 없습니다."


class TestPromotionNotification:
    """StrategyPromoter 및 send_promotion_alert 검증"""

    def test_strategy_promoter_imported_in_orchestrator(self) -> None:
        """OrchestratorAgent가 StrategyPromoter를 임포트하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)

        imports = check_imports_in_ast(tree, ["StrategyPromoter"])
        assert imports["StrategyPromoter"], (
            "StrategyPromoter가 orchestrator.py에 임포트되지 않았습니다."
        )

    def test_send_promotion_alert_in_notifier(self) -> None:
        """NotifierAgent에 send_promotion_alert 메서드가 있는지 확인합니다."""
        file_path = get_source_file("src.agents.notifier")
        tree = parse_source_ast(file_path)

        notifier_class = find_class_in_ast(tree, "NotifierAgent")
        assert notifier_class is not None, "NotifierAgent 클래스를 찾을 수 없습니다."

        method = find_method_in_class(notifier_class, "send_promotion_alert")
        assert (
            method is not None
        ), "send_promotion_alert 메서드가 NotifierAgent에 없습니다."

        args = get_function_args(method)
        assert "strategy_id" in args, "strategy_id 파라미터가 없습니다."
        assert "from_mode" in args, "from_mode 파라미터가 없습니다."
        assert "to_mode" in args, "to_mode 파라미터가 없습니다."

    def test_strategy_promoter_file_exists(self) -> None:
        """StrategyPromoter가 정의된 파일이 존재하는지 확인합니다."""
        file_path = Path(__file__).resolve().parents[1] / "src" / "utils" / "strategy_promotion.py"

        if not file_path.exists():
            pytest.skip(
                f"strategy_promotion.py 파일이 아직 생성되지 않았습니다: {file_path}"
            )

        tree = parse_source_ast(file_path)
        promoter_class = find_class_in_ast(tree, "StrategyPromoter")
        assert (
            promoter_class is not None
        ), (
            "StrategyPromoter 클래스가 strategy_promotion.py에 없습니다."
        )


class TestOrchestratorCLI:
    """CLI argparse 검증"""

    def test_independent_portfolio_flag_in_cli(self) -> None:
        """--independent-portfolio 플래그가 CLI에 있는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)

        # main 함수 찾기
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                source_code = ast.get_source_segment(
                    open(file_path, "r", encoding="utf-8").read(), node
                )
                assert (
                    "--independent-portfolio" in source_code
                ), (
                    "--independent-portfolio 플래그가 CLI 파서에 없습니다."
                )
                return

        pytest.fail("main 함수를 찾을 수 없습니다.")

    def test_cli_independent_portfolio_uses_action_store_true(self) -> None:
        """--independent-portfolio이 action='store_true'를 사용하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # --independent-portfolio 플래그 근처 코드 검사
        if "--independent-portfolio" in content:
            # store_true가 그 근처에 있는지 확인
            idx = content.find("--independent-portfolio")
            context = content[max(0, idx - 200) : idx + 200]
            assert (
                "action=" in context and "store_true" in context
            ), (
                "--independent-portfolio가 store_true 액션을 사용하지 않습니다."
            )


class TestVirtualBrokerIntegration:
    """VirtualBroker 통합 검증"""

    def test_virtual_broker_imported_in_orchestrator(self) -> None:
        """OrchestratorAgent가 VirtualBroker를 임포트하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)

        imports = check_imports_in_ast(tree, ["VirtualBroker"])
        assert imports["VirtualBroker"], (
            "VirtualBroker가 orchestrator.py에 임포트되지 않았습니다."
        )

    def test_build_virtual_broker_imported(self) -> None:
        """build_virtual_broker 함수가 임포트되는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        tree = parse_source_ast(file_path)

        imports = check_imports_in_ast(tree, ["build_virtual_broker"])
        assert imports["build_virtual_broker"], (
            "build_virtual_broker가 orchestrator.py에 임포트되지 않았습니다."
        )


class TestIndependentPortfolioModeLogic:
    """독립 포트폴리오 모드 로직 검증"""

    def test_run_cycle_checks_independent_portfolio_flag(self) -> None:
        """run_cycle이 independent_portfolio 플래그를 확인하는지 검증합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert (
            "self.independent_portfolio" in content
        ), "run_cycle에서 independent_portfolio 플래그를 사용하지 않습니다."

    def test_run_cycle_contains_independent_portfolio_branch(self) -> None:
        """run_cycle에 if self.independent_portfolio 분기가 있는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert (
            "if self.independent_portfolio:" in content
        ), (
            "run_cycle에서 if self.independent_portfolio 분기가 없습니다."
        )

    def test_independent_mode_calls_aggregate_risk(self) -> None:
        """독립 모드에서 AggregateRiskMonitor를 호출하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 독립 포트폴리오 분기 찾기
        if "if self.independent_portfolio:" in content:
            idx = content.find("if self.independent_portfolio:")
            # 다음 else 또는 함수 끝까지의 코드
            section_end = content.find("\n        else:", idx)
            if section_end == -1:
                section_end = content.find("\n    async def ", idx + 1)
            if section_end == -1:
                section_end = len(content)

            section = content[idx : section_end]
            assert (
                "AggregateRiskMonitor" in section
            ), (
                "독립 모드에서 AggregateRiskMonitor를 사용하지 않습니다."
            )

    def test_independent_mode_calls_strategy_promoter(self) -> None:
        """독립 모드에서 StrategyPromoter를 호출하는지 확인합니다."""
        file_path = get_source_file("src.agents.orchestrator")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "if self.independent_portfolio:" in content:
            idx = content.find("if self.independent_portfolio:")
            section_end = content.find("\n        else:", idx)
            if section_end == -1:
                section_end = content.find("\n    async def ", idx + 1)
            if section_end == -1:
                section_end = len(content)

            section = content[idx : section_end]
            assert (
                "StrategyPromoter" in section
            ), (
                "독립 모드에서 StrategyPromoter를 사용하지 않습니다."
            )
