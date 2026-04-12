"""
test/test_rl_runner.py — RLRunner 단위 테스트

run(), _infer_for_ticker(), _infer_sb3(), _map_action_to_signal(), _log_skip()
전체 경로를 검증합니다. DB/외부 의존성은 mock으로 격리.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.rl_runner import RLRunner, _format_q_values, _MIN_CLOSES_FOR_INFERENCE
from src.agents.rl_trading import RLEvaluationMetrics, RLPolicyArtifact


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_artifact(
    algorithm: str = "tabular_q_learning",
    model_path: str | None = None,
    q_table: dict | None = None,
) -> RLPolicyArtifact:
    return RLPolicyArtifact(
        policy_id="test_policy",
        ticker="005930.KS",
        created_at="2026-01-01T00:00:00Z",
        algorithm=algorithm,
        state_version="v2",
        lookback=20,
        episodes=10,
        learning_rate=0.001,
        discount_factor=0.95,
        epsilon=0.05,
        trade_penalty_bps=2,
        evaluation=RLEvaluationMetrics(
            total_return_pct=10.0,
            baseline_return_pct=5.0,
            excess_return_pct=5.0,
            max_drawdown_pct=-10.0,
            trades=20,
            win_rate=0.6,
            holdout_steps=40,
            approved=True,
        ),
        q_table=q_table or {"s1": {"BUY": 1.0, "SELL": 0.5, "HOLD": 0.3}},
        model_path=model_path,
    )


def _make_candles(n: int = 30) -> list[dict]:
    return [{"close": 100.0 + i * 0.5} for i in range(n)]


def _make_runner(store=None, trainer=None) -> RLRunner:
    runner = RLRunner.__new__(RLRunner)
    runner._store = store or AsyncMock()
    runner._trainer = trainer or MagicMock()
    return runner


# ── _map_action_to_signal Tests ──────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestMapActionToSignal:
    """_map_action_to_signal 매핑 테스트."""

    def test_buy(self):
        assert RLRunner._map_action_to_signal("BUY") == "BUY"

    def test_sell(self):
        assert RLRunner._map_action_to_signal("SELL") == "SELL"

    def test_hold(self):
        assert RLRunner._map_action_to_signal("HOLD") == "HOLD"

    def test_close_maps_to_hold(self):
        assert RLRunner._map_action_to_signal("CLOSE") == "HOLD"

    def test_unknown_maps_to_hold(self):
        assert RLRunner._map_action_to_signal("UNKNOWN") == "HOLD"

    def test_lowercase_buy(self):
        assert RLRunner._map_action_to_signal("buy") == "BUY"

    def test_mixed_case_sell(self):
        assert RLRunner._map_action_to_signal("Sell") == "SELL"


# ── _format_q_values Tests ──────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestFormatQValues:

    def test_basic_format(self):
        result = _format_q_values({"BUY": 1.5, "SELL": 0.3})
        assert "BUY=1.5000" in result
        assert "SELL=0.3000" in result

    def test_empty_dict(self):
        assert _format_q_values({}) == ""

    def test_sorted_output(self):
        result = _format_q_values({"SELL": 0.1, "BUY": 0.2, "HOLD": 0.3})
        keys = [part.split("=")[0] for part in result.split(", ")]
        assert keys == ["BUY", "HOLD", "SELL"]


# ── run() Tests ──────────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRLRunnerRun:
    """run() 메인 루프 테스트."""

    @pytest.mark.asyncio
    async def test_empty_tickers_returns_empty(self):
        runner = _make_runner()
        result = await runner.run([])
        assert result == []

    @pytest.mark.asyncio
    async def test_registry_load_failure_returns_empty(self):
        store = AsyncMock()
        store.list_active_policies.side_effect = RuntimeError("DB down")
        runner = _make_runner(store=store)
        with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
            result = await runner.run(["005930"])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_active_policies_returns_empty(self):
        store = AsyncMock()
        store.list_active_policies.return_value = {}
        runner = _make_runner(store=store)
        with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
            result = await runner.run(["005930"])
        assert result == []

    @pytest.mark.asyncio
    async def test_ticker_without_policy_skipped(self):
        store = AsyncMock()
        store.list_active_policies.return_value = {"005930.KS": "policy_a"}
        runner = _make_runner(store=store)
        with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
            with patch.object(runner, "_infer_for_ticker", new_callable=AsyncMock) as mock_infer:
                mock_infer.return_value = None
                result = await runner.run(["005930", "000660"])
        # 005930 has policy, 000660 doesn't
        mock_infer.assert_called_once()

    @pytest.mark.asyncio
    async def test_infer_exception_handled(self):
        store = AsyncMock()
        store.list_active_policies.return_value = {"005930.KS": "policy_a"}
        runner = _make_runner(store=store)
        with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
            with patch.object(
                runner, "_infer_for_ticker", new_callable=AsyncMock, side_effect=RuntimeError("boom")
            ):
                result = await runner.run(["005930"])
        assert result == []


# ── _infer_for_ticker Tests ──────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestInferForTicker:
    """_infer_for_ticker 단위 테스트."""

    @pytest.mark.asyncio
    async def test_policy_load_failure_returns_none(self):
        store = AsyncMock()
        store.load_policy.return_value = None
        runner = _make_runner(store=store)
        with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
            result = await runner._infer_for_ticker("005930", "policy_a", "005930.KS")
        assert result is None

    @pytest.mark.asyncio
    async def test_policy_load_retry_with_signal_ticker(self):
        """첫 번째 load 실패 시 signal_ticker로 재시도."""
        store = AsyncMock()
        store.load_policy.side_effect = [None, _make_artifact()]
        runner = _make_runner(store=store)
        with patch("src.agents.rl_runner.fetch_recent_ohlcv", new_callable=AsyncMock) as mock_ohlcv:
            mock_ohlcv.return_value = _make_candles()
            runner._trainer.infer_action.return_value = ("BUY", 0.8, "s1", {"BUY": 1.0})
            with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
                result = await runner._infer_for_ticker("005930", "policy_a", "005930.KS")
        assert store.load_policy.call_count == 2
        assert result is not None

    @pytest.mark.asyncio
    async def test_insufficient_candles_returns_none(self):
        store = AsyncMock()
        store.load_policy.return_value = _make_artifact()
        runner = _make_runner(store=store)
        with patch("src.agents.rl_runner.fetch_recent_ohlcv", new_callable=AsyncMock) as mock_ohlcv:
            mock_ohlcv.return_value = _make_candles(3)  # < _MIN_CLOSES_FOR_INFERENCE
            with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
                result = await runner._infer_for_ticker("005930", "policy_a")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_candles_returns_none(self):
        store = AsyncMock()
        store.load_policy.return_value = _make_artifact()
        runner = _make_runner(store=store)
        with patch("src.agents.rl_runner.fetch_recent_ohlcv", new_callable=AsyncMock) as mock_ohlcv:
            mock_ohlcv.return_value = None
            with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
                result = await runner._infer_for_ticker("005930", "policy_a")
        assert result is None

    @pytest.mark.asyncio
    async def test_tabular_q_inference_success(self):
        """Tabular Q 추론 성공 경로."""
        artifact = _make_artifact(algorithm="tabular_q_learning")
        store = AsyncMock()
        store.load_policy.return_value = artifact
        trainer = MagicMock()
        trainer.infer_action.return_value = ("BUY", 0.85, "s1", {"BUY": 1.0, "SELL": 0.3, "HOLD": 0.5})
        runner = _make_runner(store=store, trainer=trainer)

        with patch("src.agents.rl_runner.fetch_recent_ohlcv", new_callable=AsyncMock) as mock_ohlcv:
            mock_ohlcv.return_value = _make_candles(30)
            with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
                result = await runner._infer_for_ticker("005930", "policy_a", "005930.KS")

        assert result is not None
        assert result.signal == "BUY"
        assert result.confidence == 0.85
        assert result.strategy == "RL"
        assert result.llm_model == "rl-tabular_q_learning"

    @pytest.mark.asyncio
    async def test_sb3_inference_dispatch(self):
        """SB3 알고리즘일 때 _infer_sb3로 디스패치."""
        artifact = _make_artifact(algorithm="dqn", model_path="/tmp/model.zip")
        store = AsyncMock()
        store.load_policy.return_value = artifact
        runner = _make_runner(store=store)

        with patch("src.agents.rl_runner.fetch_recent_ohlcv", new_callable=AsyncMock) as mock_ohlcv:
            mock_ohlcv.return_value = _make_candles(30)
            with patch.object(
                runner, "_infer_sb3", return_value=("SELL", 0.7, "sb3_dqn|pos=0", {"BUY": 0.2, "SELL": 0.8})
            ) as mock_sb3:
                with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
                    result = await runner._infer_for_ticker("005930", "policy_a", "005930.KS")

        mock_sb3.assert_called_once()
        assert result.signal == "SELL"
        assert result.llm_model == "rl-dqn"

    @pytest.mark.asyncio
    async def test_signal_ticker_fallback_to_db_ticker(self):
        """original_ticker 없을 때 db_ticker 사용."""
        artifact = _make_artifact()
        store = AsyncMock()
        store.load_policy.return_value = artifact
        trainer = MagicMock()
        trainer.infer_action.return_value = ("HOLD", 0.5, "s1", {"HOLD": 0.5})
        runner = _make_runner(store=store, trainer=trainer)

        with patch("src.agents.rl_runner.fetch_recent_ohlcv", new_callable=AsyncMock) as mock_ohlcv:
            mock_ohlcv.return_value = _make_candles()
            with patch.object(RLRunner, "_log_skip", new_callable=AsyncMock):
                result = await runner._infer_for_ticker("005930", "policy_a")
        assert result.ticker == "005930"


# ── _log_skip Tests ──────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestLogSkip:
    """_log_skip 이벤트 로깅 테스트."""

    @pytest.mark.asyncio
    async def test_log_skip_basic(self):
        with patch("src.agents.rl_runner.RLRunner._log_skip.__wrapped__", create=True):
            # _log_skip은 내부에서 log_event를 import하므로 mock 필요
            with patch("src.utils.db_logger.log_event", new_callable=AsyncMock) as mock_log:
                await RLRunner._log_skip("test_reason", 5)
            mock_log.assert_called_once()
            data = mock_log.call_args[0][1]
            assert data["reason"] == "test_reason"
            assert data["ticker_count"] == 5

    @pytest.mark.asyncio
    async def test_log_skip_with_ticker_and_exc(self):
        with patch("src.utils.db_logger.log_event", new_callable=AsyncMock) as mock_log:
            await RLRunner._log_skip(
                "infer_fail", 1, ticker="005930", exc=ValueError("bad data")
            )
        data = mock_log.call_args[0][1]
        assert data["ticker"] == "005930"
        assert data["exc_type"] == "ValueError"
        assert "bad data" in data["exc_msg"]

    @pytest.mark.asyncio
    async def test_log_skip_db_failure_silent(self):
        """DB 로깅 실패 시 예외를 먹는다."""
        with patch("src.utils.db_logger.log_event", new_callable=AsyncMock, side_effect=RuntimeError):
            # 예외가 전파되지 않아야 한다
            await RLRunner._log_skip("test", 1)


# ── _infer_sb3 Tests ─────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestInferSB3:
    """_infer_sb3 메서드 단위 테스트."""

    def test_infer_sb3_creates_trainer(self):
        runner = _make_runner()
        artifact = _make_artifact(
            algorithm="dqn",
            model_path="/tmp/model.zip",
        )
        artifact.lookback = 20
        artifact.trade_penalty_bps = 2

        with patch("src.agents.rl_trading_sb3.SB3Trainer") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.infer_action.return_value = ("BUY", 0.8, "info", {"BUY": 0.8})
            mock_cls.return_value = mock_instance

            result = runner._infer_sb3(artifact, [100.0] * 30)

        mock_cls.assert_called_once_with(
            algorithm="dqn",
            lookback=20,
            trade_penalty_bps=2,
        )
        assert result == ("BUY", 0.8, "info", {"BUY": 0.8})

    def test_infer_sb3_passes_all_algorithms(self):
        for algo in ("dqn", "a2c", "ppo"):
            runner = _make_runner()
            artifact = _make_artifact(algorithm=algo, model_path="/tmp/model.zip")

            with patch("src.agents.rl_trading_sb3.SB3Trainer") as mock_cls:
                mock_instance = MagicMock()
                mock_instance.infer_action.return_value = ("HOLD", 0.5, "x", {})
                mock_cls.return_value = mock_instance
                runner._infer_sb3(artifact, [100.0] * 30)

            assert mock_cls.call_args[1]["algorithm"] == algo


# ── RLRunner Construction Tests ──────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestRLRunnerConstruction:
    """RLRunner 생성 테스트."""

    def test_name_attribute(self):
        assert RLRunner.name == "RL"

    def test_custom_store_and_trainer(self):
        store = MagicMock()
        trainer = MagicMock()
        runner = RLRunner(policy_store=store, trainer=trainer)
        assert runner._store is store
        assert runner._trainer is trainer
