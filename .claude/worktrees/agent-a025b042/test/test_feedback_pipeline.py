"""
test/test_feedback_pipeline.py — 피드백 루프 파이프라인 테스트

datalake_reader, llm_feedback, rl_retrain_pipeline, backtest_engine,
feedback_orchestrator의 핵심 로직을 검증합니다.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════
# 1. datalake_reader 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestDatalakeReader(unittest.TestCase):
    """datalake_reader.py 핵심 유틸 테스트."""

    def test_date_range(self):
        from src.services.datalake_reader import _date_range
        start = date(2026, 3, 10)
        end = date(2026, 3, 13)
        result = _date_range(start, end)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0], date(2026, 3, 10))
        self.assertEqual(result[-1], date(2026, 3, 13))

    def test_date_range_single_day(self):
        from src.services.datalake_reader import _date_range
        d = date(2026, 3, 15)
        result = _date_range(d, d)
        self.assertEqual(len(result), 1)

    def test_prefix_for(self):
        from src.services.datalake_reader import _prefix_for
        from src.services.datalake import DataType
        prefix = _prefix_for(DataType.PREDICTIONS, date(2026, 3, 15))
        self.assertEqual(prefix, "predictions/year=2026/month=03/day=15/")

    def test_parquet_bytes_roundtrip(self):
        import pyarrow as pa
        from src.services.datalake import PREDICTION_SCHEMA, _records_to_parquet
        from src.services.datalake_reader import _parquet_bytes_to_records

        records = [
            {
                "ticker": "005930",
                "timestamp": None,
                "strategy": "A",
                "signal": "BUY",
                "confidence": 0.85,
                "target_price": 70000.0,
                "stop_loss": 65000.0,
                "reasoning": "test",
            }
        ]
        parquet_bytes = _records_to_parquet(records, PREDICTION_SCHEMA)
        loaded = _parquet_bytes_to_records(parquet_bytes, PREDICTION_SCHEMA)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["ticker"], "005930")
        self.assertEqual(loaded[0]["signal"], "BUY")
        self.assertAlmostEqual(loaded[0]["confidence"], 0.85)


# ══════════════════════════════════════════════════════════════════════════
# 2. llm_feedback 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestLLMFeedback(unittest.TestCase):
    """llm_feedback.py 분석 로직 테스트."""

    def test_analyze_error_patterns_buy_bias(self):
        from src.services.llm_feedback import _analyze_error_patterns

        records = [{"signal": "BUY", "was_correct": True, "confidence": 0.5}] * 8
        records += [{"signal": "SELL", "was_correct": False, "confidence": 0.5}] * 2
        patterns = _analyze_error_patterns(records)
        self.assertTrue(any("BUY 편향" in p for p in patterns))

    def test_analyze_error_patterns_high_confidence_wrong(self):
        from src.services.llm_feedback import _analyze_error_patterns

        records = [
            {"signal": "BUY", "was_correct": False, "confidence": 0.9, "ticker": f"T{i}"}
            for i in range(5)
        ]
        patterns = _analyze_error_patterns(records)
        self.assertTrue(any("높은 자신감" in p for p in patterns))

    def test_analyze_error_patterns_hold_excess(self):
        from src.services.llm_feedback import _analyze_error_patterns

        records = [{"signal": "HOLD", "was_correct": True, "confidence": 0.5}] * 6
        records += [{"signal": "BUY", "was_correct": True, "confidence": 0.5}] * 3
        patterns = _analyze_error_patterns(records)
        self.assertTrue(any("HOLD 비율" in p for p in patterns))

    def test_compute_signal_bias(self):
        from src.services.llm_feedback import _compute_signal_bias

        records = [
            {"signal": "BUY"}, {"signal": "BUY"}, {"signal": "BUY"},
            {"signal": "SELL"}, {"signal": "HOLD"},
        ]
        bias = _compute_signal_bias(records)
        self.assertAlmostEqual(bias["BUY"], 0.6)
        self.assertAlmostEqual(bias["SELL"], 0.2)
        self.assertAlmostEqual(bias["HOLD"], 0.2)

    def test_format_feedback_for_prompt(self):
        from src.services.llm_feedback import StrategyFeedback, TickerFeedback, format_feedback_for_prompt

        fb = StrategyFeedback(
            agent_id="predictor_1",
            strategy="A",
            period_start="2026-03-01",
            period_end="2026-03-14",
            total_predictions=50,
            evaluated_predictions=40,
            overall_accuracy=0.625,
            avg_pnl_pct=1.23,
            best_tickers=["005930"],
            worst_tickers=["000660"],
            signal_bias={"BUY": 0.5, "SELL": 0.3, "HOLD": 0.2},
            error_patterns=["BUY 편향 심각 (70%)"],
            ticker_details=[
                TickerFeedback(
                    ticker="005930", total=10, correct=7, incorrect=3,
                    avg_pnl_pct=2.1, buy_accuracy=0.8, sell_accuracy=0.5,
                ),
            ],
        )
        result = format_feedback_for_prompt(fb)
        self.assertIn("과거 성과 피드백", result)
        self.assertIn("62.5%", result)
        self.assertIn("005930", result)
        self.assertIn("BUY 편향", result)


# ══════════════════════════════════════════════════════════════════════════
# 3. backtest_engine 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestBacktestSimulator(unittest.TestCase):
    """backtest_engine.py 시뮬레이터 로직 테스트."""

    def test_buy_and_sell_basic(self):
        from src.services.backtest_engine import BacktestSimulator

        sim = BacktestSimulator(initial_capital=10_000_000, slippage_pct=0, trade_fee_pct=0)
        price_map = {"005930": 50000.0}

        sim._execute_buy("005930", 50000.0, "2026-03-01", 0.9, "A", price_map)
        self.assertIn("005930", sim.positions)
        self.assertGreater(sim.positions["005930"].quantity, 0)

        sim._execute_sell("005930", 55000.0, "2026-03-10", 0.8, "A")
        self.assertNotIn("005930", sim.positions)
        self.assertGreater(sim.cash, 10_000_000)  # 수익

    def test_max_position_limit(self):
        from src.services.backtest_engine import BacktestSimulator

        sim = BacktestSimulator(
            initial_capital=10_000_000, max_position_pct=0.10,
            slippage_pct=0, trade_fee_pct=0,
        )
        price_map = {"005930": 50000.0}

        sim._execute_buy("005930", 50000.0, "2026-03-01", 0.9, "A", price_map)
        position_value = sim.positions["005930"].quantity * 50000.0
        # 포지션 가치가 전체 자산의 10%를 초과하지 않아야 함
        self.assertLessEqual(position_value, 10_000_000 * 0.10 + 50000)

    def test_get_result_empty(self):
        from src.services.backtest_engine import BacktestSimulator

        sim = BacktestSimulator(initial_capital=10_000_000)
        result = sim.get_result("A")
        self.assertEqual(result.total_return_pct, 0.0)
        self.assertEqual(result.total_trades, 0)

    def test_process_signals_integration(self):
        from src.services.backtest_engine import BacktestSimulator

        sim = BacktestSimulator(
            initial_capital=100_000_000, slippage_pct=0, trade_fee_pct=0,
        )

        signals = {
            "2026-03-01": [{"ticker": "005930", "signal": "BUY", "confidence": 0.9, "strategy": "A"}],
            "2026-03-05": [{"ticker": "005930", "signal": "SELL", "confidence": 0.8, "strategy": "A"}],
        }
        bars = {
            "005930": {
                "2026-03-01": {"close": 50000},
                "2026-03-05": {"close": 55000},
            },
        }

        sim.process_signals(signals, bars)
        result = sim.get_result("A")
        self.assertGreater(result.total_return_pct, 0)  # 이익
        self.assertEqual(result.total_trades, 2)


# ══════════════════════════════════════════════════════════════════════════
# 4. rl_retrain_pipeline 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestRLRetrainPipeline(unittest.TestCase):
    """rl_retrain_pipeline.py 구조 테스트."""

    def test_retrain_result_dataclass(self):
        from src.services.rl_retrain_pipeline import RetrainResult

        r = RetrainResult(ticker="005930", status="success", data_points=100)
        self.assertEqual(r.ticker, "005930")
        self.assertEqual(r.status, "success")
        self.assertFalse(r.deployed)

    def test_retrain_result_default_values(self):
        from src.services.rl_retrain_pipeline import RetrainResult

        r = RetrainResult(ticker="000660", status="skipped", reason="데이터 부족")
        self.assertEqual(r.excess_return_pct, 0.0)
        self.assertFalse(r.walk_forward_passed)
        self.assertIsNone(r.prev_policy_return_pct)


# ══════════════════════════════════════════════════════════════════════════
# 5. feedback_orchestrator 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestFeedbackOrchestrator(unittest.TestCase):
    """feedback_orchestrator.py 구조 테스트."""

    def test_feedback_cycle_result_dataclass(self):
        from src.services.feedback_orchestrator import FeedbackCycleResult

        r = FeedbackCycleResult(scope="llm_only")
        self.assertEqual(r.scope, "llm_only")
        self.assertEqual(r.errors, [])
        self.assertEqual(r.llm_feedback, {})


# ══════════════════════════════════════════════════════════════════════════
# 6. PredictorAgent 피드백 주입 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestPredictorFeedbackIntegration(unittest.TestCase):
    """PredictorAgent가 피드백 컨텍스트를 프롬프트에 주입하는지 검증."""

    def test_predictor_has_feedback_method(self):
        """PredictorAgent에 _get_feedback_context 메서드가 존재하는지 확인."""
        import ast
        from pathlib import Path

        source = Path("src/agents/predictor.py").read_text()
        tree = ast.parse(source)

        method_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_get_feedback_context":
                method_names.append(node.name)

        self.assertIn("_get_feedback_context", method_names)

    def test_prompt_includes_feedback_call(self):
        """_llm_signal에서 feedback_ctx를 프롬프트에 포함하는지 확인."""
        source = open("src/agents/predictor.py").read()
        self.assertIn("feedback_ctx", source)
        self.assertIn("_get_feedback_context", source)
        self.assertIn("feedback:llm_context", source)


# ══════════════════════════════════════════════════════════════════════════
# 7. API 라우터 등록 테스트
# ══════════════════════════════════════════════════════════════════════════


class TestFeedbackAPIRegistration(unittest.TestCase):
    """feedback 라우터가 FastAPI에 등록되어 있는지 확인."""

    def test_main_imports_feedback(self):
        source = open("src/api/main.py").read()
        self.assertIn("feedback", source)
        self.assertIn("feedback.router", source)

    def test_feedback_router_endpoints(self):
        """feedback.py에 필수 엔드포인트가 정의되어 있는지 확인."""
        import ast

        source = open("src/api/routers/feedback.py").read()
        tree = ast.parse(source)

        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        expected = [
            "get_prediction_accuracy",
            "get_llm_feedback_context",
            "run_backtest_endpoint",
            "compare_strategies_endpoint",
            "retrain_single_ticker",
            "retrain_all_endpoint",
            "run_feedback_cycle_endpoint",
        ]
        for ep in expected:
            self.assertIn(ep, func_names, f"Missing endpoint: {ep}")


if __name__ == "__main__":
    unittest.main()
