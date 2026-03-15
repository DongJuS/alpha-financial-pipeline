#!/usr/bin/env python3
"""
test/validate_phase2_followup.py — Phase 2 후속 구현 검증 스크립트

Docker/pip 의존성 없이 파일 존재 여부, 구문 검증, 모듈 구조를 확인합니다.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    status = "✅" if ok else "❌"
    msg = f"  {status} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    if ok:
        PASS += 1
    else:
        FAIL += 1


def syntax_check(filepath: Path) -> bool:
    """Python 파일의 구문이 올바른지 확인합니다."""
    try:
        ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
        return True
    except SyntaxError as e:
        return False


def has_class(filepath: Path, classname: str) -> bool:
    """파일에 특정 클래스가 정의되어 있는지 확인합니다."""
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == classname:
            return True
    return False


def has_function(filepath: Path, funcname: str) -> bool:
    """파일에 특정 함수가 정의되어 있는지 확인합니다."""
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == funcname:
            return True
    return False


def has_text(filepath: Path, text: str) -> bool:
    """파일에 특정 텍스트가 포함되어 있는지 확인합니다."""
    return text in filepath.read_text(encoding="utf-8")


def main() -> None:
    print("\n=== Phase 2 후속 구현 검증 ===\n")

    # ── 1. 파일 존재 확인 ────────────────────────────────────────────────────
    print("[1] 파일 존재 확인")
    required_files = [
        "src/utils/account_scope.py",
        "src/utils/config.py",
        "src/utils/strategy_promotion.py",
        "src/utils/aggregate_risk.py",
        "src/brokers/virtual_broker.py",
        "src/brokers/__init__.py",
        "scripts/seed_historical_data.py",
        "scripts/promote_strategy.py",
        "scripts/db/init_db.py",
        "src/api/routers/strategy.py",
        "test/test_data_pipeline.py",
        "test/test_strategy_promotion.py",
        "test/test_aggregate_risk.py",
        "test/test_virtual_slippage.py",
    ]
    for f in required_files:
        p = ROOT / f
        check(f, p.exists())

    # ── 2. 구문 검증 ────────────────────────────────────────────────────────
    print("\n[2] Python 구문 검증")
    py_files = [
        "src/utils/account_scope.py",
        "src/utils/config.py",
        "src/utils/strategy_promotion.py",
        "src/utils/aggregate_risk.py",
        "src/brokers/virtual_broker.py",
        "src/brokers/__init__.py",
        "src/agents/collector.py",
        "scripts/seed_historical_data.py",
        "scripts/promote_strategy.py",
        "src/api/routers/strategy.py",
        "test/test_data_pipeline.py",
        "test/test_strategy_promotion.py",
        "test/test_aggregate_risk.py",
        "test/test_virtual_slippage.py",
    ]
    for f in py_files:
        p = ROOT / f
        if p.exists():
            ok = syntax_check(p)
            check(f"구문 OK: {f}", ok)

    # ── 3. 클래스/함수 존재 확인 ──────────────────────────────────────────────
    print("\n[3] 핵심 클래스/함수 존재 확인")

    # account_scope
    scope_path = ROOT / "src/utils/account_scope.py"
    check("AccountScope에 'virtual' 포함", has_text(scope_path, '"virtual"'))
    check("is_virtual_scope() 함수", has_function(scope_path, "is_virtual_scope"))

    # config.py
    config_path = ROOT / "src/utils/config.py"
    check("virtual_slippage_bps 설정", has_text(config_path, "virtual_slippage_bps"))
    check("virtual_fill_delay_max_sec 설정", has_text(config_path, "virtual_fill_delay_max_sec"))
    check("virtual_partial_fill_enabled 설정", has_text(config_path, "virtual_partial_fill_enabled"))
    check("max_single_stock_exposure_pct 설정", has_text(config_path, "max_single_stock_exposure_pct"))
    check("promotion_criteria_override 설정", has_text(config_path, "promotion_criteria_override"))
    check("strategy_modes 설정", has_text(config_path, "strategy_modes"))
    check("strategy_capital_allocation 설정", has_text(config_path, "strategy_capital_allocation"))

    # virtual_broker.py
    vb_path = ROOT / "src/brokers/virtual_broker.py"
    check("VirtualBroker 클래스", has_class(vb_path, "VirtualBroker"))
    check("VirtualBrokerExecution 클래스", has_class(vb_path, "VirtualBrokerExecution"))
    check("_apply_slippage() 메서드", has_function(vb_path, "_apply_slippage"))
    check("_calc_partial_fill() 메서드", has_function(vb_path, "_calc_partial_fill"))
    check("_simulate_delay() 메서드", has_function(vb_path, "_simulate_delay"))
    check("execute_order() 메서드", has_function(vb_path, "execute_order"))

    # strategy_promotion.py
    sp_path = ROOT / "src/utils/strategy_promotion.py"
    check("StrategyPromoter 클래스", has_class(sp_path, "StrategyPromoter"))
    check("PromotionCheckResult 클래스", has_class(sp_path, "PromotionCheckResult"))
    check("evaluate_promotion_readiness() 메서드", has_function(sp_path, "evaluate_promotion_readiness"))
    check("promote_strategy() 메서드", has_function(sp_path, "promote_strategy"))
    check("get_all_strategy_status() 메서드", has_function(sp_path, "get_all_strategy_status"))

    # aggregate_risk.py
    ar_path = ROOT / "src/utils/aggregate_risk.py"
    check("AggregateRiskMonitor 클래스", has_class(ar_path, "AggregateRiskMonitor"))
    check("check_total_exposure() 메서드", has_function(ar_path, "check_total_exposure"))
    check("check_strategy_correlation() 메서드", has_function(ar_path, "check_strategy_correlation"))
    check("get_risk_summary() 메서드", has_function(ar_path, "get_risk_summary"))
    check("record_risk_snapshot() 메서드", has_function(ar_path, "record_risk_snapshot"))

    # collector.py
    col_path = ROOT / "src/agents/collector.py"
    check("fetch_historical_ohlcv() 메서드", has_function(col_path, "fetch_historical_ohlcv"))
    check("_fetch_historical_daily() 메서드", has_function(col_path, "_fetch_historical_daily"))
    check("_fetch_historical_intraday() 메서드", has_function(col_path, "_fetch_historical_intraday"))
    check("check_data_exists() 메서드", has_function(col_path, "check_data_exists"))

    # brokers/__init__.py
    bi_path = ROOT / "src/brokers/__init__.py"
    check("build_virtual_broker() 함수", has_function(bi_path, "build_virtual_broker"))
    check("build_broker_for_scope에 virtual 분기", has_text(bi_path, '"virtual"'))

    # seed_historical_data.py
    seed_path = ROOT / "scripts/seed_historical_data.py"
    check("run_seed() 함수", has_function(seed_path, "run_seed"))
    check("--ticker-file 지원", has_text(seed_path, "ticker-file"))
    check("--dry-run 지원", has_text(seed_path, "dry-run"))
    check("--force 지원", has_text(seed_path, "force"))

    # promote_strategy.py
    ps_path = ROOT / "scripts/promote_strategy.py"
    check("run_promote() 함수", has_function(ps_path, "run_promote"))
    check("--list 옵션", has_text(ps_path, "--list"))
    check("--check 옵션", has_text(ps_path, "--check"))
    check("--force 옵션", has_text(ps_path, "--force"))

    # strategy.py API
    api_path = ROOT / "src/api/routers/strategy.py"
    check("promotion-status 엔드포인트", has_text(api_path, "promotion-status"))
    check("promotion-readiness 엔드포인트", has_text(api_path, "promotion-readiness"))
    check("promote 엔드포인트", has_text(api_path, "/promote"))

    # init_db.py
    db_path = ROOT / "scripts/db/init_db.py"
    check("strategy_promotions 테이블", has_text(db_path, "strategy_promotions"))
    check("aggregate_risk_snapshots 테이블", has_text(db_path, "aggregate_risk_snapshots"))
    check("account_scope CHECK virtual 추가", has_text(db_path, "'virtual'"))
    check("strategy_id 컬럼 추가", has_text(db_path, "strategy_id VARCHAR(10)"))

    # ── 4. 테스트 클래스 존재 확인 ──────────────────────────────────────────
    print("\n[4] 테스트 클래스 존재 확인")
    tests = {
        "test/test_data_pipeline.py": [
            "TestCollectorHistoricalDaily",
            "TestCollectorCheckDataExists",
            "TestSeedHistoricalDataCLI",
        ],
        "test/test_strategy_promotion.py": [
            "TestPromotionCriteria",
            "TestPromotionReadiness",
            "TestPromoteStrategy",
        ],
        "test/test_aggregate_risk.py": [
            "TestAggregateRiskMonitorConfig",
            "TestExposureCheck",
            "TestStrategyCorrelation",
        ],
        "test/test_virtual_slippage.py": [
            "TestVirtualBrokerSlippage",
            "TestVirtualBrokerPartialFill",
            "TestVirtualBrokerConfig",
            "TestAccountScopeVirtual",
            "TestBuildBrokerForScope",
        ],
    }
    for fpath, classes in tests.items():
        p = ROOT / fpath
        for cls in classes:
            check(f"{cls} in {fpath}", has_class(p, cls))

    # ── 결과 ────────────────────────────────────────────────────────────────
    total = PASS + FAIL
    print(f"\n=== 결과: {PASS}/{total} 통과 ({FAIL}건 실패) ===\n")

    if FAIL > 0:
        sys.exit(1)
    print("🎉 Phase 2 후속 구현 검증 완료!")


if __name__ == "__main__":
    main()
