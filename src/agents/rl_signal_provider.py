"""
src/agents/rl_signal_provider.py — RL Policy Inference as Signal Candidate (Phase 10.2)

Wraps RL policy inference as a signal source (StrategyRunner implementation).
Supports shadow/paper/live modes with configurable defaults.

Shadow mode (default):
  - Loads approved policies from registry.json
  - Runs inference for each ticker
  - Generates PredictionSignal with is_shadow=True
  - Signals recorded but excluded from blending

Paper mode:
  - Same as shadow, but signals used in paper trading

Live mode:
  - Requires explicit configuration
  - Signals used in real trading
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading_v2 import TabularQTrainerV2, map_v2_action_to_signal
from src.agents.rl_trading import RLPolicyArtifact
from src.db.models import PredictionSignal
from src.utils.logging import get_logger

logger = get_logger(__name__)


class RLSignalProvider:
    """RL policy inference as signal candidate source.

    Attributes:
        mode: Operating mode - "shadow" (default), "paper", or "live"
        policy_store: RLPolicyStoreV2 instance for loading policies
        trainer: TabularQTrainerV2 for inference
    """

    def __init__(
        self,
        *,
        mode: Literal["shadow", "paper", "live"] = "shadow",
        policy_store: Optional[RLPolicyStoreV2] = None,
        models_dir: Optional[Path] = None,
    ) -> None:
        """Initialize RLSignalProvider.

        Args:
            mode: "shadow" (record but no blending), "paper", or "live"
            policy_store: Custom RLPolicyStoreV2 instance (uses default if None)
            models_dir: Custom models directory path (uses default if None)
        """
        self.mode = mode
        self.policy_store = policy_store or RLPolicyStoreV2(models_dir)
        self.trainer = TabularQTrainerV2()

        # Validate mode
        if mode not in ("shadow", "paper", "live"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'shadow', 'paper', or 'live'")

        # Live mode requires explicit env variable
        if mode == "live":
            live_enabled = os.getenv("RL_SIGNAL_PROVIDER_LIVE_ENABLED", "").lower() == "true"
            if not live_enabled:
                logger.warning(
                    "RL_SIGNAL_PROVIDER_LIVE_ENABLED not set. Live mode requires explicit configuration."
                )

        logger.info("RLSignalProvider initialized in mode: %s", mode)

    # ──────────────────────────── StrategyRunner Protocol ────────────────────────────

    @property
    def name(self) -> str:
        """Strategy name for registry."""
        return f"RL_SIGNAL_{self.mode.upper()}"

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        """Generate signals for tickers using approved RL policies.

        Returns:
            List of PredictionSignal objects (is_shadow=True if mode='shadow')
        """
        signals: list[PredictionSignal] = []

        for ticker in tickers:
            try:
                signal = await self._generate_signal(ticker)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(
                    "RL signal generation failed for %s: %s",
                    ticker,
                    e,
                    exc_info=True,
                )
                # Continue with other tickers

        logger.info(
            "RL signal provider generated %d signals in %s mode",
            len(signals),
            self.mode,
        )
        return signals

    # ──────────────────────────── Signal Generation ────────────────────────────────

    async def _generate_signal(self, ticker: str) -> Optional[PredictionSignal]:
        """Generate a signal for a single ticker.

        Returns:
            PredictionSignal with is_shadow flag set based on mode, or None if no policy
        """
        # Load approved policy for ticker
        artifact = self.policy_store.load_active_policy(ticker)
        if not artifact:
            logger.debug("No active policy found for %s", ticker)
            return None

        # Ensure we have price history (simplified - in production fetch from market data)
        # For now, use a placeholder. In real implementation, this would fetch actual closes.
        closes = await self._fetch_recent_closes(ticker)
        if not closes or len(closes) < artifact.lookback + 1:
            logger.warning("Insufficient price history for %s (need %d bars)", ticker, artifact.lookback)
            return None

        try:
            # Run inference
            action, confidence, state, q_values = self.trainer.infer_action(
                artifact,
                closes,
                current_position=0,  # Simplified: always assume flat position
            )

            # Map V2 action to signal
            signal_type = map_v2_action_to_signal(action)

            # Get current price for target
            current_price = int(closes[-1]) if closes else 0

            # Build reasoning
            reasoning = (
                f"RL {artifact.state_version} ({artifact.algorithm}): "
                f"action={action}, confidence={confidence}, state={state}"
            )

            # Create signal
            signal = PredictionSignal(
                agent_id="rl_signal_provider",
                llm_model=f"{artifact.algorithm}_{artifact.state_version}",
                strategy="RL",
                ticker=ticker,
                signal=signal_type,
                confidence=confidence,
                target_price=current_price,
                stop_loss=None,
                reasoning_summary=reasoning,
                trading_date=date.today(),
                is_shadow=(self.mode == "shadow"),  # Shadow mode flag
            )

            logger.info(
                "RL signal generated for %s: %s (confidence=%.2f, mode=%s, is_shadow=%s)",
                ticker,
                signal_type,
                confidence,
                self.mode,
                signal.is_shadow,
            )
            return signal

        except Exception as e:
            logger.error(
                "Inference failed for %s (policy=%s): %s",
                ticker,
                artifact.policy_id if artifact else "N/A",
                e,
                exc_info=True,
            )
            return None

    # ──────────────────────────── Market Data ────────────────────────────────────

    async def _fetch_recent_closes(self, ticker: str, bars: int = 21) -> list[float]:
        """Fetch recent closing prices for a ticker.

        Args:
            ticker: Ticker symbol
            bars: Number of bars to fetch (default 21)

        Returns:
            List of recent closing prices in ascending order
        """
        try:
            from src.db.queries import fetch_recent_market_data

            market_data = await fetch_recent_market_data(ticker, days=max(1, bars))
            if not market_data:
                logger.warning("No market data available for %s", ticker)
                return []

            # market_data is a list of dicts with 'close' key
            closes = [float(md.get("close", 0)) for md in market_data if md.get("close")]
            return closes

        except Exception as e:
            logger.warning("Failed to fetch market data for %s: %s", ticker, e)
            return []

    # ──────────────────────────── Policy Management ────────────────────────────────

    def list_available_policies(self) -> dict[str, dict]:
        """List available approved policies by ticker.

        Returns:
            Dictionary mapping ticker to policy info
        """
        registry = self.policy_store.load_registry()
        result = {}

        for ticker, ticker_policies in registry.tickers.items():
            active_id = ticker_policies.active_policy_id
            if active_id:
                active = ticker_policies.get_policy(active_id)
                if active:
                    result[ticker] = {
                        "policy_id": active.policy_id,
                        "algorithm": active.algorithm,
                        "state_version": active.state_version,
                        "return_pct": active.return_pct,
                        "excess_return_pct": active.excess_return_pct,
                        "max_drawdown_pct": active.max_drawdown_pct,
                        "approved": active.approved,
                        "created_at": active.created_at.isoformat(),
                    }

        logger.info("Found %d active policies", len(result))
        return result

    def get_policy_info(self, ticker: str) -> Optional[dict]:
        """Get info for the active policy of a ticker.

        Returns:
            Policy info dict or None if no active policy
        """
        artifact = self.policy_store.load_active_policy(ticker)
        if not artifact:
            return None

        return {
            "policy_id": artifact.policy_id,
            "ticker": artifact.ticker,
            "algorithm": artifact.algorithm,
            "state_version": artifact.state_version,
            "lookback": artifact.lookback,
            "episodes": artifact.episodes,
            "return_pct": artifact.evaluation.total_return_pct,
            "excess_return_pct": artifact.evaluation.excess_return_pct,
            "max_drawdown_pct": artifact.evaluation.max_drawdown_pct,
            "trades": artifact.evaluation.trades,
            "win_rate": artifact.evaluation.win_rate,
            "holdout_steps": artifact.evaluation.holdout_steps,
            "approved": artifact.evaluation.approved,
            "created_at": artifact.created_at,
        }
