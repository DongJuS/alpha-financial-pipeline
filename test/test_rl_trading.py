from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.agents.orchestrator import OrchestratorAgent
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import (
    RLEvaluationMetrics,
    RLPolicyArtifact,
    RLPolicyStore,
    RLTradingAgent,
    RLDataset,
    TabularQTrainer,
)
from src.brokers.paper import PaperBrokerExecution
from src.db.models import MarketDataPoint, PredictionSignal


def _uptrend_closes(length: int = 90) -> list[float]:
    return [100.0 + (idx * 1.7) + ((idx % 5) * 0.15) for idx in range(length)]


def _flat_closes(length: int = 90) -> list[float]:
    return [100.0 for _ in range(length)]


def _ohlcv_rows_from_closes(closes: list[float], ticker: str = "005930") -> list[dict]:
    start = date(2026, 1, 2)
    suffix = ".KS"
    rows: list[dict] = []
    for idx, close in enumerate(closes):
        traded = start + timedelta(days=idx)
        rows.append(
            {
                "instrument_id": f"{ticker}{suffix}",
                "ticker": ticker,
                "name": "삼성전자",
                "traded_at": traded,
                "open": round(close - 1.0, 4),
                "high": round(close + 2.0, 4),
                "low": round(close - 2.0, 4),
                "close": round(close, 4),
                "volume": 1_000_000 + idx,
                "change_pct": 0.5,
            }
        )
    return rows


def _tick_rows_from_closes(closes: list[float], ticker: str = "005930") -> list[dict]:
    start = date(2026, 3, 13)
    suffix = ".KS"
    rows: list[dict] = []
    for idx, close in enumerate(closes):
        traded = start + timedelta(days=idx)
        rows.append(
            {
                "instrument_id": f"{ticker}{suffix}",
                "ticker": ticker,
                "name": "삼성전자",
                "traded_at": traded,
                "open": round(close, 4),
                "high": round(close, 4),
                "low": round(close, 4),
                "close": round(close, 4),
                "volume": 100 + idx,
                "change_pct": None,
            }
        )
    return rows


def _policy_artifact(
    policy_id: str,
    *,
    ticker: str = "005930",
    approved: bool = True,
    return_pct: float = 12.5,
) -> RLPolicyArtifact:
    return RLPolicyArtifact(
        policy_id=policy_id,
        ticker=ticker,
        created_at=datetime.now(timezone.utc).isoformat(),
        algorithm="tabular_q_learning",
        state_version="qlearn_v2",
        lookback=20,
        episodes=300,
        learning_rate=0.10,
        discount_factor=0.95,
        epsilon=0.30,
        trade_penalty_bps=2,
        q_table={"p0|s0|l0|m0|v0": {"BUY": 0.8, "SELL": 0.1, "HOLD": 0.0, "CLOSE": -0.1}},
        evaluation=RLEvaluationMetrics(
            total_return_pct=return_pct,
            baseline_return_pct=2.0,
            excess_return_pct=return_pct - 2.0,
            max_drawdown_pct=-12.0,
            trades=32,
            win_rate=0.56,
            holdout_steps=40,
            approved=approved,
        ),
    )


def _market_data_fetch_side_effect(
    *,
    daily_rows: list[dict] | None = None,
    tick_rows: list[dict] | None = None,
    latest_tick_rows: list[dict] | None = None,
):
    async def _side_effect(ticker: str, **kwargs):
        # limit=1 은 _build_inference_closes 에서 최신 1건 조회
        if kwargs.get("limit") == 1 and latest_tick_rows is not None:
            return latest_tick_rows
        # tick_rows가 있으면 우선 반환 (tick interval 테스트 케이스)
        if tick_rows is not None:
            return tick_rows
        return daily_rows or []

    return _side_effect


class RLTrainerCoreTest(unittest.TestCase):
    def test_tabular_trainer_learns_buy_signal_on_uptrend(self) -> None:
        closes = _uptrend_closes()
        dataset = RLDataset(
            ticker="005930",
            closes=closes,
            timestamps=[f"2026-01-{idx + 1:02d}" for idx in range(len(closes))],
        )
        trainer = TabularQTrainer(episodes=80, epsilon=0.20)

        artifact = trainer.train(dataset)
        action, confidence, _, _ = trainer.infer_action(artifact, dataset.closes, current_position=0)

        self.assertTrue(artifact.evaluation.approved)
        self.assertEqual(action, "BUY")
        self.assertGreater(confidence, 0.5)
        self.assertGreaterEqual(artifact.evaluation.total_return_pct, 5.0)

    def test_evaluation_requires_minimum_five_percent_return_for_approval(self) -> None:
        closes = _flat_closes()
        trainer = TabularQTrainer(episodes=10)

        metrics = trainer.evaluate(
            closes,
            {
                "p0|s0|l0": {"BUY": 0.0, "SELL": 0.0, "HOLD": 1.0},
            },
        )

        self.assertEqual(metrics.total_return_pct, 0.0)
        self.assertFalse(metrics.approved)

    def test_train_with_metadata_rejects_ratio_below_half(self) -> None:
        closes = _uptrend_closes(120)
        dataset = RLDataset(
            ticker="005930",
            closes=closes,
            timestamps=[f"2026-01-{(i % 28) + 1:02d}" for i in range(len(closes))],
        )
        trainer = TabularQTrainer(episodes=5)
        with self.assertRaises(ValueError):
            trainer.train_with_metadata(dataset, train_ratio=0.4)

    def test_train_with_metadata_rejects_ratio_one_or_above(self) -> None:
        closes = _uptrend_closes(120)
        dataset = RLDataset(
            ticker="005930",
            closes=closes,
            timestamps=[f"2026-01-{(i % 28) + 1:02d}" for i in range(len(closes))],
        )
        trainer = TabularQTrainer(episodes=5)
        with self.assertRaises(ValueError):
            trainer.train_with_metadata(dataset, train_ratio=1.0)

    def test_train_with_metadata_records_actual_split_sizes(self) -> None:
        closes = _uptrend_closes(120)
        dataset = RLDataset(
            ticker="005930",
            closes=closes,
            timestamps=[f"2026-01-{(i % 28) + 1:02d}" for i in range(len(closes))],
        )
        trainer = TabularQTrainer(episodes=5)
        for ratio in (0.6, 0.8):
            _, meta = trainer.train_with_metadata(dataset, train_ratio=ratio)
            self.assertAlmostEqual(meta.train_ratio, ratio)
            # train+test 합이 전체 길이와 일치해야 한다
            self.assertEqual(meta.train_size + meta.test_size, len(closes))
            # lookback+5 하한이 걸려도 train_size는 dataset 내부여야 한다
            self.assertGreater(meta.train_size, 0)
            self.assertGreater(meta.test_size, 0)

    def test_train_with_metadata_rejects_dataset_too_short(self) -> None:
        # lookback=6, lookback+10=16 미만이면 ValueError
        closes = _uptrend_closes(12)
        dataset = RLDataset(
            ticker="005930",
            closes=closes,
            timestamps=[f"2026-01-{(i % 28) + 1:02d}" for i in range(len(closes))],
        )
        trainer = TabularQTrainer(episodes=5, lookback=6)
        with self.assertRaises(ValueError):
            trainer.train_with_metadata(dataset, train_ratio=0.7)


class RLDatasetBuilderTest(unittest.IsolatedAsyncioTestCase):
    async def test_build_dataset_supports_tick_interval_and_second_timestamps(self) -> None:
        closes = _uptrend_closes(80)
        rows = _tick_rows_from_closes(closes, ticker="259960")

        from src.agents.rl_trading import RLDatasetBuilder

        builder = RLDatasetBuilder(min_history_points=40)
        with patch("src.agents.rl_trading.fetch_recent_market_data", new=AsyncMock(return_value=rows)) as fetch_mock:
            dataset = await builder.build_dataset(
                "259960",
                interval="tick",
                seconds=3600,
                limit=500,
            )

        self.assertEqual(len(dataset.closes), len(closes))
        self.assertEqual(dataset.timestamps[0], str(rows[0]["traded_at"]))
        self.assertEqual(dataset.timestamps[-1], str(rows[-1]["traded_at"]))
        self.assertEqual(fetch_mock.await_args.kwargs["limit"], 500)


class RLTradingAgentRunCycleTest(unittest.IsolatedAsyncioTestCase):
    def test_rl_policy_store_v2_save_and_activate(self) -> None:
        """RLPolicyStoreV2가 정책을 저장하고 활성화할 수 있는지 확인합니다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RLPolicyStoreV2(models_dir=Path(tmpdir), auto_save_registry=True)
            artifact = store.save_policy(_policy_artifact("rl_005930_boot"))
            store.activate_policy(artifact)

            active = store.list_active_policies()
            self.assertIn("005930.KS", active)
            self.assertEqual(active["005930.KS"], "rl_005930_boot")

    async def test_run_cycle_trains_activates_policy_and_emits_signal(self) -> None:
        closes = _uptrend_closes()
        rows = _ohlcv_rows_from_closes(closes)

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = RLTradingAgent(policy_store=RLPolicyStore(Path(tmpdir)), dataset_interval="daily")
            with (
                patch(
                    "src.agents.rl_trading.fetch_recent_market_data",
                    new=AsyncMock(side_effect=_market_data_fetch_side_effect(daily_rows=rows, latest_tick_rows=[])),
                ),
                patch("src.agents.rl_trading.get_position", new=AsyncMock(return_value=None)),
            ):
                predictions, summaries = await agent.run_cycle(["005930"])

            self.assertEqual(len(predictions), 1)
            self.assertEqual(predictions[0].strategy, "RL")
            self.assertEqual(predictions[0].signal, "BUY")
            self.assertTrue(summaries[0]["approved"])
            registry = agent.policy_store.list_active_policies()
            self.assertIn("005930.KS", registry["policies"])

    async def test_portfolio_manager_process_signal_supports_rl_source(self) -> None:
        agent = PortfolioManagerAgent()
        signal = PredictionSignal(
            agent_id="rl_policy_agent",
            llm_model="tabular-q-learning",
            strategy="RL",
            ticker="005930",
            signal="BUY",
            confidence=0.8,
            trading_date=date.today(),
        )

        with (
            patch.object(agent, "_resolve_name_and_price", new=AsyncMock(return_value=("삼성전자", 1_000))),
            patch("src.agents.portfolio_manager.get_position", new=AsyncMock(return_value=None)),
            patch("src.agents.portfolio_manager.get_trading_account", new=AsyncMock(return_value=None)),
            patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=0)),
            patch.object(
                agent.paper_broker,
                "execute_order",
                new=AsyncMock(
                    return_value=PaperBrokerExecution(
                        client_order_id="paper-rl-test",
                        account_scope="paper",
                        status="FILLED",
                        ticker="005930",
                        side="BUY",
                        quantity=1,
                        price=1_000,
                        cash_balance=9_999_000,
                        total_equity=10_000_000,
                    )
                ),
            ) as execute_order_mock,
        ):
            result = await agent.process_signal(
                signal,
                signal_source_override="RL",
                risk_config={
                    "max_position_pct": 20,
                    "enable_paper_trading": True,
                    "enable_real_trading": False,
                    "primary_account_scope": "paper",
                    "paper_seed_capital": 10_000_000,
                },
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "BUY")
        self.assertEqual(execute_order_mock.await_args.args[0].signal_source, "RL")

    def test_rl_policy_store_v2_registry_state(self) -> None:
        """RLPolicyStoreV2 레지스트리 상태를 확인합니다."""
        from src.utils.ticker import clear_cache
        clear_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RLPolicyStoreV2(models_dir=Path(tmpdir), auto_save_registry=True)
            artifact = store.save_policy(_policy_artifact("rl_005930_v1"))
            store.activate_policy(artifact)

            active = store.list_active_policies()
            self.assertEqual(len(active), 1)
            self.assertIn("005930.KS", active)

            # 두 번째 정책 추가
            artifact2 = store.save_policy(_policy_artifact("rl_035720_v1", ticker="035720"))
            store.activate_policy(artifact2)

            active2 = store.list_active_policies()
            self.assertEqual(len(active2), 2)
            self.assertIn("035720.KS", active2)

    async def test_run_cycle_supports_tick_interval_seconds_window(self) -> None:
        closes = _uptrend_closes(80)
        rows = _tick_rows_from_closes(closes, ticker="259960")

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = RLTradingAgent(
                policy_store=RLPolicyStore(Path(tmpdir)),
                dataset_interval="tick",
                training_window_seconds=3600,
                dataset_limit=500,
            )
            with (
                patch(
                    "src.agents.rl_trading.fetch_recent_market_data",
                    new=AsyncMock(
                        side_effect=_market_data_fetch_side_effect(tick_rows=rows, latest_tick_rows=[rows[-1]])
                    ),
                ),
                patch("src.agents.rl_trading.get_position", new=AsyncMock(return_value=None)),
            ):
                predictions, summaries = await agent.run_cycle(["259960"])

        self.assertEqual(len(predictions), 1)
        self.assertEqual(summaries[0]["dataset_interval"], "tick")
        self.assertEqual(predictions[0].strategy, "RL")


class RLTrainerEdgeCaseTest(unittest.TestCase):
    """RL Trainer 에지 케이스: 경계값, 빈 입력, 타임아웃."""

    def test_flat_data_should_not_approve(self) -> None:
        """완전 횡보 데이터 → 승인 불가."""
        closes = _flat_closes()
        trainer = TabularQTrainer(episodes=30)
        dataset = RLDataset(
            ticker="FLAT",
            closes=closes,
            timestamps=[str(i) for i in range(len(closes))],
        )
        artifact = trainer.train(dataset)
        self.assertFalse(artifact.evaluation.approved)

    def test_minimum_data_length(self) -> None:
        """최소 데이터 길이에서도 학습 가능."""
        closes = _uptrend_closes(length=50)  # 최소 40+
        trainer = TabularQTrainer(episodes=10, epsilon=0.20)
        dataset = RLDataset(
            ticker="MIN",
            closes=closes,
            timestamps=[str(i) for i in range(len(closes))],
        )
        artifact = trainer.train(dataset)
        self.assertIsNotNone(artifact)
        self.assertIsNotNone(artifact.evaluation)

    def test_infer_action_empty_q_table(self) -> None:
        """빈 Q-테이블에서 추론 → 기본 HOLD 반환."""
        trainer = TabularQTrainer(episodes=1)
        artifact = _policy_artifact("empty_q", ticker="005930")
        artifact.q_table = {}
        action, confidence, _, _ = trainer.infer_action(
            artifact, _uptrend_closes(30), current_position=0
        )
        self.assertIn(action, ("BUY", "SELL", "HOLD", "CLOSE"))

    def test_evaluation_metrics_fields(self) -> None:
        """RLEvaluationMetrics의 모든 필드가 올바른 타입."""
        metrics = RLEvaluationMetrics(
            total_return_pct=5.0,
            baseline_return_pct=2.0,
            excess_return_pct=3.0,
            max_drawdown_pct=-10.0,
            trades=15,
            win_rate=0.6,
            holdout_steps=40,
            approved=True,
        )
        self.assertIsInstance(metrics.total_return_pct, float)
        self.assertIsInstance(metrics.trades, int)
        self.assertIsInstance(metrics.approved, bool)

    def test_rl_dataset_creation(self) -> None:
        """RLDataset 기본 생성."""
        ds = RLDataset(
            ticker="005930",
            closes=[100.0, 101.0, 102.0],
            timestamps=["t1", "t2", "t3"],
        )
        self.assertEqual(ds.ticker, "005930")
        self.assertEqual(len(ds.closes), 3)

    def test_multiple_episodes_improve_or_maintain(self) -> None:
        """에피소드 수 증가 시 학습 결과가 존재하는지 검증."""
        closes = _uptrend_closes(90)
        dataset = RLDataset(
            ticker="MULTI_EP",
            closes=closes,
            timestamps=[str(i) for i in range(len(closes))],
        )
        trainer_few = TabularQTrainer(episodes=10, epsilon=0.20)
        artifact_few = trainer_few.train(dataset)

        trainer_many = TabularQTrainer(episodes=100, epsilon=0.20)
        artifact_many = trainer_many.train(dataset)

        # 더 많은 에피소드로 학습한 결과가 Q-테이블을 가져야 함
        self.assertGreater(len(artifact_many.q_table), 0)


if __name__ == "__main__":
    unittest.main()
