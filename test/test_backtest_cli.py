"""
test/test_backtest_cli.py — CLI 인자 파싱 + E2E 흐름 테스트
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backtest.cli import _build_parser, _date_type, _format_result, _result_to_dict
from src.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    TradeRecord,
)


# ── _date_type ────────────────────────────────────────────────────────

class TestDateType:
    def test_valid_date(self) -> None:
        assert _date_type("2025-07-01") == date(2025, 7, 1)

    def test_invalid_date_raises(self) -> None:
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            _date_type("not-a-date")

    def test_invalid_format_raises(self) -> None:
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            _date_type("01/07/2025")


# ── argparse ──────────────────────────────────────────────────────────

class TestArgParsing:
    def test_run_required_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "RL",
            "--train-start", "2024-01-01",
            "--train-end", "2025-06-30",
            "--test-start", "2025-07-01",
            "--test-end", "2025-12-31",
        ])
        assert args.command == "run"
        assert args.ticker == "005930"
        assert args.strategy == "RL"
        assert args.train_start == date(2024, 1, 1)
        assert args.test_end == date(2025, 12, 31)
        assert args.initial_capital == 10_000_000
        assert args.save_db is False
        assert args.output_json is None

    def test_run_optional_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "A",
            "--train-start", "2024-01-01",
            "--train-end", "2025-06-30",
            "--test-start", "2025-07-01",
            "--test-end", "2025-12-31",
            "--initial-capital", "50000000",
            "--commission", "0.02",
            "--tax", "0.25",
            "--slippage-bps", "5",
            "--save-db",
            "--output-json", "/tmp/result.json",
        ])
        assert args.initial_capital == 50_000_000
        assert args.commission == 0.02
        assert args.tax == 0.25
        assert args.slippage_bps == 5
        assert args.save_db is True
        assert args.output_json == "/tmp/result.json"

    def test_run_missing_ticker(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--strategy", "RL",
                               "--train-start", "2024-01-01", "--train-end", "2025-06-30",
                               "--test-start", "2025-07-01", "--test-end", "2025-12-31"])

    def test_run_invalid_strategy(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--ticker", "005930", "--strategy", "INVALID",
                               "--train-start", "2024-01-01", "--train-end", "2025-06-30",
                               "--test-start", "2025-07-01", "--test-end", "2025-12-31"])

    def test_optimize_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "optimize",
            "--ticker", "005930",
            "--train-start", "2024-01-01",
            "--train-end", "2025-06-30",
            "--test-start", "2025-07-01",
            "--test-end", "2025-12-31",
            "--mdd-constraint", "-15.0",
        ])
        assert args.command == "optimize"
        assert args.mdd_constraint == -15.0

    def test_no_command_shows_help(self) -> None:
        """커맨드 없이 실행하면 command=None."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_run_profile_default(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "RL",
            "--train-start", "2024-01-01",
            "--train-end", "2025-06-30",
            "--test-start", "2025-07-01",
            "--test-end", "2025-12-31",
        ])
        assert args.profile == "tabular_q_v2_momentum"

    def test_run_profile_v1(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "RL",
            "--train-start", "2024-01-01",
            "--train-end", "2025-06-30",
            "--test-start", "2025-07-01",
            "--test-end", "2025-12-31",
            "--profile", "tabular_q_v1_baseline",
        ])
        assert args.profile == "tabular_q_v1_baseline"


# ── 결과 포매팅 ──────────────────────────────────────────────────────

def _make_sample_result() -> BacktestResult:
    config = BacktestConfig(
        ticker="005930",
        strategy="RL",
        train_start=date(2024, 1, 1),
        train_end=date(2025, 6, 30),
        test_start=date(2025, 7, 1),
        test_end=date(2025, 12, 31),
    )
    metrics = BacktestMetrics(
        total_return_pct=12.45,
        annual_return_pct=26.18,
        sharpe_ratio=1.42,
        max_drawdown_pct=-8.23,
        win_rate=58.3,
        total_trades=24,
        avg_holding_days=5.2,
        baseline_return_pct=8.92,
        excess_return_pct=3.53,
    )
    trades = [
        TradeRecord(
            date=date(2025, 7, 5),
            side="BUY",
            ticker="005930",
            price=60000,
            quantity=100,
            commission=900,
            tax=0,
            slippage_cost=180,
            total_cost=1080,
        ),
        TradeRecord(
            date=date(2025, 7, 15),
            side="SELL",
            ticker="005930",
            price=65000,
            quantity=100,
            commission=975,
            tax=11700,
            slippage_cost=195,
            total_cost=12870,
            pnl=500000,
        ),
    ]
    return BacktestResult(config=config, metrics=metrics, trades=trades)


class TestFormatResult:
    def test_format_contains_key_fields(self) -> None:
        result = _make_sample_result()
        output = _format_result(result, profile_name="tabular_q_v2_momentum")
        assert "005930" in output
        assert "RL (tabular_q_v2_momentum)" in output
        assert "+12.45%" in output
        assert "1.42" in output
        assert "-8.23%" in output
        assert "58.3%" in output

    def test_format_cost_summary(self) -> None:
        result = _make_sample_result()
        output = _format_result(result)
        assert "1,875" in output  # 900 + 975
        assert "11,700" in output
        assert "375" in output  # 180 + 195


class TestResultToDict:
    def test_serializable(self) -> None:
        result = _make_sample_result()
        d = _result_to_dict(result)
        # date가 문자열로 변환됐는지 확인
        assert isinstance(d["config"]["train_start"], str)
        assert d["config"]["train_start"] == "2024-01-01"
        # JSON 직렬화 가능한지 확인
        json_str = json.dumps(d, ensure_ascii=False)
        assert "005930" in json_str

    def test_metrics_preserved(self) -> None:
        result = _make_sample_result()
        d = _result_to_dict(result)
        assert d["metrics"]["sharpe_ratio"] == 1.42
        assert d["metrics"]["total_trades"] == 24


# ── E2E 흐름 테스트 (모의 데이터) ─────────────────────────────────────

class TestRunBacktestE2E:
    """DB 없이 모의 데이터로 run 서브커맨드 흐름을 검증합니다."""

    @pytest.mark.asyncio
    async def test_run_rl_strategy_e2e(self) -> None:
        """RL 전략 E2E: 데이터 로딩 → 학습 → 엔진 실행 → 결과 출력."""
        from src.backtest.cli import _run_backtest

        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "RL",
            "--train-start", "2024-01-01",
            "--train-end", "2024-06-30",
            "--test-start", "2024-07-01",
            "--test-end", "2024-12-31",
        ])

        mock_rows = [
            {"traded_at": date(2024, 7, 1 + i), "close": 60000 + i * 100,
             "instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자",
             "open": 60000, "high": 61000, "low": 59000, "volume": 1000000,
             "change_pct": 0.1, "adj_close": 60000 + i * 100}
            for i in range(20)
        ]

        mock_signal = MagicMock()
        mock_signal.get_signal = MagicMock(return_value="HOLD")

        sample_result = _make_sample_result()
        mock_engine_instance = MagicMock()
        mock_engine_instance.run = MagicMock(return_value=sample_result)

        with (
            patch("src.backtest.cli._load_ohlcv", new=AsyncMock(return_value=mock_rows)),
            patch("src.backtest.cli._build_rl_signal_source", return_value=mock_signal),
            patch("src.backtest.cli.BacktestEngine", return_value=mock_engine_instance),
            patch("src.backtest.cli.CostModel"),
        ):
            await _run_backtest(args)

    @pytest.mark.asyncio
    async def test_run_strategy_a_e2e(self) -> None:
        """Strategy A Replay E2E."""
        from src.backtest.cli import _run_backtest

        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "A",
            "--train-start", "2024-01-01",
            "--train-end", "2024-06-30",
            "--test-start", "2024-07-01",
            "--test-end", "2024-12-31",
        ])

        mock_rows = [
            {"traded_at": date(2024, 7, 1 + i), "close": 60000 + i * 100,
             "instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자",
             "open": 60000, "high": 61000, "low": 59000, "volume": 1000000,
             "change_pct": 0.1, "adj_close": 60000 + i * 100}
            for i in range(20)
        ]

        mock_signal = MagicMock()
        mock_signal.get_signal = MagicMock(return_value="HOLD")

        sample_result = _make_sample_result()
        mock_engine_instance = MagicMock()
        mock_engine_instance.run = MagicMock(return_value=sample_result)

        with (
            patch("src.backtest.cli._load_ohlcv", new=AsyncMock(return_value=mock_rows)),
            patch("src.backtest.cli._build_replay_signal_source", new=AsyncMock(return_value=mock_signal)),
            patch("src.backtest.cli.BacktestEngine", return_value=mock_engine_instance),
            patch("src.backtest.cli.CostModel"),
        ):
            await _run_backtest(args)

    @pytest.mark.asyncio
    async def test_run_blend_strategy_raises(self) -> None:
        """BLEND 전략은 run에서 거부."""
        from src.backtest.cli import _run_backtest

        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "BLEND",
            "--train-start", "2024-01-01",
            "--train-end", "2024-06-30",
            "--test-start", "2024-07-01",
            "--test-end", "2024-12-31",
        ])

        mock_rows = [
            {"traded_at": date(2024, 7, 1 + i), "close": 60000,
             "instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자",
             "open": 60000, "high": 61000, "low": 59000, "volume": 1000000,
             "change_pct": 0.0, "adj_close": 60000}
            for i in range(10)
        ]

        with (
            patch("src.backtest.cli._load_ohlcv", new=AsyncMock(return_value=mock_rows)),
        ):
            with pytest.raises(SystemExit, match="BLEND"):
                await _run_backtest(args)

    @pytest.mark.asyncio
    async def test_run_empty_data_raises(self) -> None:
        """데이터 없으면 SystemExit."""
        from src.backtest.cli import _run_backtest

        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "999999",
            "--strategy", "RL",
            "--train-start", "2024-01-01",
            "--train-end", "2024-06-30",
            "--test-start", "2024-07-01",
            "--test-end", "2024-12-31",
        ])

        with patch("src.backtest.cli._load_ohlcv", new=AsyncMock(return_value=[])):
            with pytest.raises(SystemExit, match="데이터가 없습니다"):
                await _run_backtest(args)

    @pytest.mark.asyncio
    async def test_run_with_json_output(self, tmp_path: Path) -> None:
        """--output-json 옵션으로 JSON 파일 생성."""
        from src.backtest.cli import _run_backtest

        json_path = tmp_path / "result.json"
        parser = _build_parser()
        args = parser.parse_args([
            "run",
            "--ticker", "005930",
            "--strategy", "RL",
            "--train-start", "2024-01-01",
            "--train-end", "2024-06-30",
            "--test-start", "2024-07-01",
            "--test-end", "2024-12-31",
            "--output-json", str(json_path),
        ])

        mock_rows = [
            {"traded_at": date(2024, 7, 1 + i), "close": 60000,
             "instrument_id": "005930.KS", "ticker": "005930", "name": "삼성전자",
             "open": 60000, "high": 61000, "low": 59000, "volume": 1000000,
             "change_pct": 0.0, "adj_close": 60000}
            for i in range(20)
        ]

        mock_signal = MagicMock()
        mock_signal.get_signal = MagicMock(return_value="HOLD")

        sample_result = _make_sample_result()
        mock_engine_instance = MagicMock()
        mock_engine_instance.run = MagicMock(return_value=sample_result)

        with (
            patch("src.backtest.cli._load_ohlcv", new=AsyncMock(return_value=mock_rows)),
            patch("src.backtest.cli._build_rl_signal_source", return_value=mock_signal),
            patch("src.backtest.cli.BacktestEngine", return_value=mock_engine_instance),
            patch("src.backtest.cli.CostModel"),
        ):
            await _run_backtest(args)

        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["config"]["ticker"] == "005930"
        assert data["metrics"]["sharpe_ratio"] == 1.42
