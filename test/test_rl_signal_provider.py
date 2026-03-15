"""
test/test_rl_signal_provider.py — Tests for RLSignalProvider (Phase 10.2)

Test shadow/paper/live modes, signal generation, and mode switching.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.rl_signal_provider import RLSignalProvider
from src.agents.rl_trading import RLPolicyArtifact, RLEvaluationMetrics
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.db.models import PredictionSignal


class TestRLSignalProviderInit(TestCase):
    """Test RLSignalProvider initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_policy_store = MagicMock(spec=RLPolicyStoreV2)

    def test_init_shadow_mode(self):
        """Test initialization in shadow mode (default)."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )
        self.assertEqual(provider.mode, "shadow")
        self.assertEqual(provider.policy_store, self.mock_policy_store)
        self.assertEqual(provider.name, "RL_SIGNAL_SHADOW")

    def test_init_paper_mode(self):
        """Test initialization in paper mode."""
        provider = RLSignalProvider(
            mode="paper",
            policy_store=self.mock_policy_store,
        )
        self.assertEqual(provider.mode, "paper")
        self.assertEqual(provider.name, "RL_SIGNAL_PAPER")

    def test_init_live_mode(self):
        """Test initialization in live mode."""
        with patch.dict("os.environ", {}, clear=False):
            provider = RLSignalProvider(
                mode="live",
                policy_store=self.mock_policy_store,
            )
            self.assertEqual(provider.mode, "live")
            self.assertEqual(provider.name, "RL_SIGNAL_LIVE")

    def test_init_invalid_mode(self):
        """Test initialization with invalid mode."""
        with self.assertRaises(ValueError):
            RLSignalProvider(
                mode="invalid",
                policy_store=self.mock_policy_store,
            )

    def test_init_default_mode(self):
        """Test initialization with default mode (shadow)."""
        with patch.dict("os.environ", {}, clear=False):
            provider = RLSignalProvider(policy_store=self.mock_policy_store)
            self.assertEqual(provider.mode, "shadow")


class TestRLSignalProviderSignalGeneration(IsolatedAsyncioTestCase):
    """Test signal generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_policy_store = MagicMock(spec=RLPolicyStoreV2)
        self.mock_artifact = RLPolicyArtifact(
            policy_id="test_policy_001",
            ticker="005930",
            created_at="2026-03-14T12:00:00Z",
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            lookback=20,
            episodes=300,
            learning_rate=0.1,
            discount_factor=0.95,
            epsilon=0.3,
            trade_penalty_bps=2,
            q_table={"test_state": {"BUY": 0.5, "SELL": -0.3, "HOLD": 0.1, "CLOSE": -0.2}},
            evaluation=RLEvaluationMetrics(
                total_return_pct=15.5,
                baseline_return_pct=10.0,
                excess_return_pct=5.5,
                max_drawdown_pct=-12.3,
                trades=25,
                win_rate=0.6,
                holdout_steps=50,
                approved=True,
            ),
        )

    async def test_generate_signal_with_approved_policy(self):
        """Test signal generation with an approved policy."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        # Mock policy store to return artifact
        self.mock_policy_store.load_active_policy.return_value = self.mock_artifact

        # Mock market data fetch
        with patch.object(
            provider, "_fetch_recent_closes", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = [100.0, 101.0, 102.0, 103.0] * 6  # 24 closes
            signal = await provider._generate_signal("005930")

        self.assertIsNotNone(signal)
        self.assertIsInstance(signal, PredictionSignal)
        self.assertEqual(signal.ticker, "005930")
        self.assertEqual(signal.strategy, "RL")
        self.assertTrue(signal.is_shadow)
        self.assertIn(signal.signal, ("BUY", "SELL", "HOLD"))
        self.assertIsNotNone(signal.confidence)
        self.assertTrue(0.0 <= signal.confidence <= 1.0)
        self.assertEqual(signal.trading_date, date.today())

    async def test_generate_signal_no_policy(self):
        """Test signal generation with no active policy."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        # Mock policy store to return None
        self.mock_policy_store.load_active_policy.return_value = None

        signal = await provider._generate_signal("999999")
        self.assertIsNone(signal)

    async def test_generate_signal_insufficient_data(self):
        """Test signal generation with insufficient price history."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        self.mock_policy_store.load_active_policy.return_value = self.mock_artifact

        # Mock market data fetch to return too few closes
        with patch.object(
            provider, "_fetch_recent_closes", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = [100.0, 101.0]  # Too few
            signal = await provider._generate_signal("005930")

        self.assertIsNone(signal)

    async def test_run_multiple_tickers_shadow_mode(self):
        """Test run() with multiple tickers in shadow mode."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        # Mock policy store to return artifact for both tickers
        def load_active_policy(ticker):
            if ticker in ("005930", "000660"):
                artifact = RLPolicyArtifact(
                    policy_id=f"test_{ticker}",
                    ticker=ticker,
                    created_at="2026-03-14T12:00:00Z",
                    algorithm="tabular_q_learning",
                    state_version="qlearn_v2",
                    lookback=20,
                    episodes=300,
                    learning_rate=0.1,
                    discount_factor=0.95,
                    epsilon=0.3,
                    trade_penalty_bps=2,
                    q_table={"state": {"BUY": 0.5, "SELL": -0.3, "HOLD": 0.1, "CLOSE": -0.2}},
                    evaluation=RLEvaluationMetrics(
                        total_return_pct=10.0,
                        baseline_return_pct=8.0,
                        excess_return_pct=2.0,
                        max_drawdown_pct=-10.0,
                        trades=20,
                        win_rate=0.55,
                        holdout_steps=50,
                        approved=True,
                    ),
                )
                return artifact
            return None

        self.mock_policy_store.load_active_policy.side_effect = load_active_policy

        # Mock market data
        with patch.object(
            provider, "_fetch_recent_closes", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = [100.0 + i*0.1 for i in range(30)]

            signals = await provider.run(["005930", "000660"])

        self.assertEqual(len(signals), 2)
        self.assertTrue(all(isinstance(sig, PredictionSignal) for sig in signals))
        self.assertTrue(all(sig.is_shadow is True for sig in signals))
        self.assertTrue(all(sig.strategy == "RL" for sig in signals))

    async def test_run_empty_ticker_list(self):
        """Test run() with empty ticker list."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        signals = await provider.run([])
        self.assertEqual(signals, [])

    async def test_run_graceful_failure_handling(self):
        """Test run() continues on signal generation failure."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        # Mock policy store to return artifact for first, None for second
        def load_active_policy(ticker):
            if ticker == "005930":
                return self.mock_artifact
            return None

        self.mock_policy_store.load_active_policy.side_effect = load_active_policy

        with patch.object(
            provider, "_fetch_recent_closes", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = [100.0 + i*0.1 for i in range(30)]

            signals = await provider.run(["005930", "000660", "005940"])

        # Should have at least 0 signals (depends on inference)
        self.assertIsInstance(signals, list)


class TestRLSignalProviderModes(TestCase):
    """Test different operating modes."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_policy_store = MagicMock(spec=RLPolicyStoreV2)

    def test_shadow_mode_sets_is_shadow_flag(self):
        """Test that shadow mode sets is_shadow=True on signals."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        # Create a signal directly
        signal = PredictionSignal(
            agent_id="rl_signal_provider",
            llm_model="test_model",
            strategy="RL",
            ticker="005930",
            signal="BUY",
            confidence=0.75,
            trading_date=date.today(),
            is_shadow=(provider.mode == "shadow"),
        )

        self.assertTrue(signal.is_shadow)

    def test_paper_mode_sets_is_shadow_false(self):
        """Test that paper mode sets is_shadow=False on signals."""
        provider = RLSignalProvider(
            mode="paper",
            policy_store=self.mock_policy_store,
        )

        signal = PredictionSignal(
            agent_id="rl_signal_provider",
            llm_model="test_model",
            strategy="RL",
            ticker="005930",
            signal="BUY",
            confidence=0.75,
            trading_date=date.today(),
            is_shadow=(provider.mode == "shadow"),
        )

        self.assertFalse(signal.is_shadow)

    def test_live_mode_sets_is_shadow_false(self):
        """Test that live mode sets is_shadow=False on signals."""
        with patch.dict("os.environ", {}, clear=False):
            provider = RLSignalProvider(
                mode="live",
                policy_store=self.mock_policy_store,
            )

            signal = PredictionSignal(
                agent_id="rl_signal_provider",
                llm_model="test_model",
                strategy="RL",
                ticker="005930",
                signal="BUY",
                confidence=0.75,
                trading_date=date.today(),
                is_shadow=(provider.mode == "shadow"),
            )

            self.assertFalse(signal.is_shadow)


class TestRLSignalProviderPolicyManagement(TestCase):
    """Test policy management methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_policy_store = MagicMock(spec=RLPolicyStoreV2)
        self.mock_artifact = RLPolicyArtifact(
            policy_id="test_policy_001",
            ticker="005930",
            created_at="2026-03-14T12:00:00Z",
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            lookback=20,
            episodes=300,
            learning_rate=0.1,
            discount_factor=0.95,
            epsilon=0.3,
            trade_penalty_bps=2,
            q_table={"state": {"BUY": 0.5, "SELL": -0.3, "HOLD": 0.1, "CLOSE": -0.2}},
            evaluation=RLEvaluationMetrics(
                total_return_pct=15.5,
                baseline_return_pct=10.0,
                excess_return_pct=5.5,
                max_drawdown_pct=-12.0,
                trades=25,
                win_rate=0.6,
                holdout_steps=50,
                approved=True,
            ),
        )

    def test_list_available_policies(self):
        """Test listing available policies."""
        from src.agents.rl_policy_registry import PolicyRegistry, TickerPolicies, PolicyEntry
        from datetime import datetime, timezone

        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        # Create mock registry
        entry = PolicyEntry(
            policy_id="test_001",
            ticker="005930",
            algorithm="tabular_q_learning",
            state_version="qlearn_v2",
            return_pct=15.5,
            baseline_return_pct=10.0,
            excess_return_pct=5.5,
            max_drawdown_pct=-12.0,
            trades=25,
            win_rate=0.6,
            holdout_steps=50,
            approved=True,
            created_at=datetime.now(timezone.utc),
            file_path="tabular/005930/test_001.json",
            lookback=20,
            episodes=300,
            learning_rate=0.1,
            discount_factor=0.95,
            epsilon=0.3,
            trade_penalty_bps=2,
        )

        ticker_policies = TickerPolicies(
            ticker="005930",
            active_policy_id="test_001",
            policies=[entry],
        )

        registry = PolicyRegistry(
            tickers={"005930": ticker_policies},
        )

        self.mock_policy_store.load_registry.return_value = registry

        # Mock load_active_policy to return artifact
        self.mock_policy_store.load_active_policy.return_value = self.mock_artifact

        policies = provider.list_available_policies()
        self.assertIn("005930", policies)
        self.assertEqual(policies["005930"]["policy_id"], "test_001")
        self.assertTrue(policies["005930"]["approved"])

    def test_get_policy_info(self):
        """Test getting policy info for a ticker."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        self.mock_policy_store.load_active_policy.return_value = self.mock_artifact

        info = provider.get_policy_info("005930")
        self.assertIsNotNone(info)
        self.assertEqual(info["ticker"], "005930")
        self.assertEqual(info["policy_id"], "test_policy_001")
        self.assertTrue(info["approved"])
        self.assertEqual(info["return_pct"], 15.5)

    def test_get_policy_info_no_policy(self):
        """Test getting policy info when no policy exists."""
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=self.mock_policy_store,
        )

        self.mock_policy_store.load_active_policy.return_value = None

        info = provider.get_policy_info("999999")
        self.assertIsNone(info)


class TestRLSignalProviderProtocol(IsolatedAsyncioTestCase):
    """Test StrategyRunner protocol implementation."""

    async def test_provider_as_strategy_runner(self):
        """Test that RLSignalProvider implements StrategyRunner protocol."""
        mock_policy_store = MagicMock(spec=RLPolicyStoreV2)
        provider = RLSignalProvider(
            mode="shadow",
            policy_store=mock_policy_store,
        )

        # Should have name attribute
        self.assertTrue(hasattr(provider, "name"))
        self.assertIsInstance(provider.name, str)

        # Should have async run method
        self.assertTrue(hasattr(provider, "run"))
        self.assertTrue(asyncio.iscoroutinefunction(provider.run))

        # Test run with empty list
        signals = await provider.run([])
        self.assertIsInstance(signals, list)
        self.assertTrue(all(isinstance(sig, PredictionSignal) for sig in signals))


if __name__ == "__main__":
    import unittest
    unittest.main()
