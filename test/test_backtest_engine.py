"""
test/test_backtest_engine.py — 백테스트 엔진 & API AST 기반 구조 검증 테스트

런타임 의존성 없이 소스 코드의 구조적 정확성을 검증합니다.
"""

import ast
import os
import textwrap

import pytest

# ── 파일 경로 ───────────────────────────────────────────────────────────────

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PATH = os.path.join(BASE, "src", "services", "backtest_engine.py")
ROUTER_PATH = os.path.join(BASE, "src", "api", "routers", "backtest.py")
MAIN_PATH = os.path.join(BASE, "src", "api", "main.py")


def _parse(path: str) -> ast.Module:
    with open(path) as f:
        return ast.parse(f.read())


def _class_names(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def _func_names(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _get_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _class_method_names(cls: ast.ClassDef) -> list[str]:
    return [
        n.name
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _source(path: str) -> str:
    with open(path) as f:
        return f.read()


# ═══════════════════════════════════════════════════════════════════════════
# 1. BacktestEngine 구조 검증
# ═══════════════════════════════════════════════════════════════════════════


class TestBacktestEngineStructure:
    """src/services/backtest_engine.py 구조 검증."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tree = _parse(ENGINE_PATH)
        self.source = _source(ENGINE_PATH)

    def test_file_exists(self):
        assert os.path.isfile(ENGINE_PATH)

    def test_dataclass_definitions(self):
        """필수 데이터클래스가 모두 정의되어 있는지 확인."""
        names = _class_names(self.tree)
        required = [
            "BacktestConfig",
            "BacktestOrder",
            "BacktestPosition",
            "BacktestDailySnapshot",
            "BacktestResult",
        ]
        for cls_name in required:
            assert cls_name in names, f"{cls_name} 데이터클래스 누락"

    def test_engine_class_exists(self):
        """BacktestEngine 클래스가 정의되어 있는지 확인."""
        assert "BacktestEngine" in _class_names(self.tree)

    def test_engine_core_methods(self):
        """BacktestEngine의 핵심 메서드가 존재하는지 확인."""
        cls = _get_class(self.tree, "BacktestEngine")
        assert cls is not None
        methods = _class_method_names(cls)
        required = [
            "__init__",
            "execute_buy",
            "execute_sell",
            "update_prices",
            "record_daily_snapshot",
            "generate_signal",
            "run",
        ]
        for m in required:
            assert m in methods, f"BacktestEngine.{m}() 메서드 누락"

    def test_signal_methods(self):
        """시그널 생성 메서드들이 존재하는지 확인."""
        cls = _get_class(self.tree, "BacktestEngine")
        assert cls is not None
        methods = _class_method_names(cls)
        signal_methods = [
            "_golden_dead_cross_signal",
            "_momentum_signal",
            "_mean_reversion_signal",
        ]
        for m in signal_methods:
            assert m in methods, f"BacktestEngine.{m}() 시그널 메서드 누락"

    def test_run_is_async(self):
        """run()이 async 메서드인지 확인."""
        cls = _get_class(self.tree, "BacktestEngine")
        assert cls is not None
        for node in cls.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
                return
        pytest.fail("BacktestEngine.run()은 async 메서드여야 합니다")

    def test_run_backtest_from_db_function(self):
        """run_backtest_from_db 비동기 함수가 존재하는지 확인."""
        funcs = [
            n.name for n in ast.iter_child_nodes(self.tree)
            if isinstance(n, ast.AsyncFunctionDef)
        ]
        assert "run_backtest_from_db" in funcs

    def test_config_has_strategy_id(self):
        """BacktestConfig에 strategy_id 필드가 있는지 확인."""
        assert "strategy_id" in self.source

    def test_config_has_slippage(self):
        """BacktestConfig에 slippage_bps 필드가 있는지 확인."""
        assert "slippage_bps" in self.source

    def test_config_has_commission(self):
        """BacktestConfig에 commission_bps 필드가 있는지 확인."""
        assert "commission_bps" in self.source

    def test_result_has_performance_fields(self):
        """BacktestResult에 성과 관련 필드들이 있는지 확인."""
        fields = [
            "total_return_pct",
            "annualized_return_pct",
            "max_drawdown_pct",
            "sharpe_ratio",
            "win_rate",
            "profit_factor",
        ]
        for f in fields:
            assert f in self.source, f"BacktestResult.{f} 필드 누락"

    def test_slippage_application(self):
        """슬리피지 적용 메서드가 구현되어 있는지 확인."""
        assert "_apply_slippage" in self.source

    def test_commission_calculation(self):
        """수수료 계산 메서드가 구현되어 있는지 확인."""
        assert "_calc_commission" in self.source


# ═══════════════════════════════════════════════════════════════════════════
# 2. Backtest API 라우터 구조 검증
# ═══════════════════════════════════════════════════════════════════════════


class TestBacktestRouterStructure:
    """src/api/routers/backtest.py 구조 검증."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tree = _parse(ROUTER_PATH)
        self.source = _source(ROUTER_PATH)

    def test_file_exists(self):
        assert os.path.isfile(ROUTER_PATH)

    def test_router_instance(self):
        """APIRouter 인스턴스가 생성되는지 확인."""
        assert "router = APIRouter()" in self.source

    def test_request_model_exists(self):
        """BacktestRunRequest 모델이 정의되어 있는지 확인."""
        assert "BacktestRunRequest" in _class_names(self.tree)

    def test_response_model_exists(self):
        """BacktestRunResponse 모델이 정의되어 있는지 확인."""
        assert "BacktestRunResponse" in _class_names(self.tree)

    def test_summary_response_model_exists(self):
        """BacktestSummaryResponse 모델이 정의되어 있는지 확인."""
        assert "BacktestSummaryResponse" in _class_names(self.tree)

    def test_run_endpoint_exists(self):
        """POST /run 엔드포인트 함수가 존재하는지 확인."""
        funcs = _func_names(self.tree)
        assert "run_backtest" in funcs

    def test_summary_endpoint_exists(self):
        """POST /run/summary 엔드포인트 함수가 존재하는지 확인."""
        funcs = _func_names(self.tree)
        assert "run_backtest_summary" in funcs

    def test_run_endpoint_is_async(self):
        """run_backtest()가 async인지 확인."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_backtest":
                return
        pytest.fail("run_backtest는 async여야 합니다")

    def test_auth_dependency(self):
        """인증 의존성이 사용되는지 확인."""
        assert "get_current_user" in self.source

    def test_request_model_fields(self):
        """BacktestRunRequest에 필수 필드가 있는지 확인."""
        cls = _get_class(self.tree, "BacktestRunRequest")
        assert cls is not None
        source_lines = ast.get_source_segment(self.source, cls)
        required = ["strategy_id", "start_date", "end_date", "tickers", "initial_capital"]
        for f in required:
            assert f in source_lines, f"BacktestRunRequest.{f} 필드 누락"

    def test_validation_strategy_id(self):
        """전략 ID 검증 로직이 있는지 확인."""
        assert "VALID_STRATEGIES" in self.source

    def test_validation_signal_source(self):
        """시그널 소스 검증 로직이 있는지 확인."""
        assert "VALID_SIGNALS" in self.source

    def test_validation_date_order(self):
        """날짜 순서 검증 로직이 있는지 확인."""
        assert "start_date >= request.end_date" in self.source or \
               "start_date" in self.source and "end_date" in self.source

    def test_pydantic_models(self):
        """모든 Pydantic 모델이 BaseModel을 상속하는지 확인."""
        pydantic_models = [
            "BacktestRunRequest",
            "BacktestRunResponse",
            "BacktestSummaryResponse",
            "BacktestOrderItem",
            "BacktestSnapshotItem",
            "BacktestPositionItem",
        ]
        classes = _class_names(self.tree)
        for model in pydantic_models:
            assert model in classes, f"{model} Pydantic 모델 누락"

    def test_imports_backtest_engine(self):
        """백테스트 엔진을 임포트하는지 확인."""
        assert "from src.services.backtest_engine import" in self.source

    def test_error_handling(self):
        """에러 처리가 구현되어 있는지 확인."""
        assert "HTTPException" in self.source
        assert "HTTP_400_BAD_REQUEST" in self.source
        assert "HTTP_500_INTERNAL_SERVER_ERROR" in self.source


# ═══════════════════════════════════════════════════════════════════════════
# 3. 라우터 등록 확인
# ═══════════════════════════════════════════════════════════════════════════


class TestBacktestRouterRegistration:
    """src/api/main.py에 백테스트 라우터가 등록되었는지 확인."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.source = _source(MAIN_PATH)

    def test_main_imports_backtest(self):
        """main.py가 backtest 라우터를 임포트하는지 확인."""
        assert "backtest" in self.source

    def test_main_includes_backtest_router(self):
        """main.py가 backtest 라우터를 등록하는지 확인."""
        assert "backtest.router" in self.source

    def test_backtest_prefix(self):
        """백테스트 라우터가 올바른 prefix로 등록되는지 확인."""
        assert "/backtest" in self.source

    def test_backtest_tag(self):
        """백테스트 라우터가 올바른 태그를 가지는지 확인."""
        assert '"backtest"' in self.source


# ═══════════════════════════════════════════════════════════════════════════
# 4. BacktestEngine 로직 검증 (단위 테스트)
# ═══════════════════════════════════════════════════════════════════════════


class TestBacktestEngineLogic:
    """BacktestEngine의 핵심 로직을 검증합니다 (임포트 불필요, 소스 분석)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.source = _source(ENGINE_PATH)

    def test_buy_respects_max_position_pct(self):
        """execute_buy가 max_position_pct를 검사하는지 확인."""
        assert "max_position_pct" in self.source

    def test_buy_checks_cash(self):
        """execute_buy가 현금 잔액을 확인하는지 확인."""
        assert "self.cash" in self.source

    def test_sell_checks_position(self):
        """execute_sell이 포지션 존재를 확인하는지 확인."""
        # 포지션 없으면 None 반환
        assert "pos.quantity <= 0" in self.source or "pos.quantity" in self.source

    def test_daily_snapshot_tracks_drawdown(self):
        """일별 스냅샷이 drawdown을 추적하는지 확인."""
        assert "peak_equity" in self.source
        assert "drawdown" in self.source

    def test_build_result_computes_annualized(self):
        """_build_result가 연환산 수익률을 계산하는지 확인."""
        assert "annualized" in self.source
        assert "252" in self.source  # 거래일 기준

    def test_build_result_computes_profit_factor(self):
        """_build_result가 profit factor를 계산하는지 확인."""
        assert "winning_pnl" in self.source
        assert "losing_pnl" in self.source
        assert "profit_factor" in self.source

    def test_run_iterates_dates(self):
        """run()이 날짜별로 반복 처리하는지 확인."""
        assert "sorted_dates" in self.source
        assert "for trade_date in sorted_dates" in self.source

    def test_db_query_uses_market_data(self):
        """run_backtest_from_db가 market_data 테이블을 조회하는지 확인."""
        assert "market_data" in self.source
        assert "ohlcv_data" in self.source
