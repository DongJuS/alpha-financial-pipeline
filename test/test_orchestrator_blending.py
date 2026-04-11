"""
test/test_orchestrator_blending.py — N-way 블렌딩 로직 테스트

OrchestratorAgent의 _blend_nway_predictions, _normalize_active_weights,
_execute_blended_signals를 검증합니다.
"""
from __future__ import annotations

import pytest
from datetime import date

from src.agents.orchestrator import OrchestratorAgent, DEFAULT_BLEND_WEIGHTS
from src.db.models import PredictionSignal


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_signal(
    ticker: str = "005930",
    signal: str = "BUY",
    confidence: float = 0.8,
    strategy: str = "A",
) -> PredictionSignal:
    return PredictionSignal(
        agent_id=f"test_{strategy}",
        llm_model="test",
        strategy=strategy,
        ticker=ticker,
        signal=signal,
        confidence=confidence,
        target_price=70000,
        stop_loss=65000,
        reasoning_summary="test",
        trading_date=date(2026, 4, 11),
    )


# ── Normalize Weights Tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestNormalizeActiveWeights:
    """가중치 재정규화 테스트."""

    def test_all_strategies_active(self):
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        result = orch._normalize_active_weights({"A", "B", "RL"})
        total = sum(result.values())
        assert abs(total - 1.0) < 1e-6
        assert set(result.keys()) == {"A", "B", "RL"}

    def test_one_strategy_excluded(self):
        """RL이 빠지면 A,B가 재분배."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        result = orch._normalize_active_weights({"A", "B"})
        assert abs(sum(result.values()) - 1.0) < 1e-6
        assert abs(result["A"] - 0.5) < 1e-6
        assert abs(result["B"] - 0.5) < 1e-6
        assert "RL" not in result

    def test_single_strategy_active(self):
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        result = orch._normalize_active_weights({"A"})
        assert abs(result["A"] - 1.0) < 1e-6

    def test_no_active_strategies(self):
        orch = OrchestratorAgent()
        result = orch._normalize_active_weights(set())
        assert result == {}

    def test_all_zero_weights_equal_distribution(self):
        """모든 가중치가 0이면 동일 분배."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.0, "B": 0.0}
        )
        result = orch._normalize_active_weights({"A", "B"})
        assert abs(result["A"] - 0.5) < 1e-6
        assert abs(result["B"] - 0.5) < 1e-6

    def test_unknown_strategy_in_active_set(self):
        """활성 세트에 알 수 없는 전략이 있으면 동일 분배 로직 진행."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.5, "B": 0.5}
        )
        result = orch._normalize_active_weights({"A", "B", "UNKNOWN"})
        # UNKNOWN의 가중치가 0이므로 A,B만 결과에 포함
        assert "UNKNOWN" not in result
        assert abs(sum(result.values()) - 1.0) < 1e-6


# ── N-way Blending Tests ────────────────────────────────────────────────────


@pytest.mark.unit
class TestBlendNwayPredictions:
    """N-way 블렌딩 로직 테스트."""

    def test_single_strategy_blending(self):
        """단일 전략이면 그대로 통과."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 1.0}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.9, "A")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal == "BUY"
        assert blended[0].ticker == "005930"

    def test_unanimous_buy_signal(self):
        """모든 전략이 BUY → 블렌딩 결과도 BUY."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.9, "A")],
            "B": [_make_signal("005930", "BUY", 0.8, "B")],
            "RL": [_make_signal("005930", "BUY", 0.7, "RL")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal == "BUY"
        assert blended[0].confidence > 0

    def test_conflicting_signals_majority_wins(self):
        """2 BUY vs 1 SELL → BUY 승리."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.9, "A")],
            "B": [_make_signal("005930", "BUY", 0.8, "B")],
            "RL": [_make_signal("005930", "SELL", 0.7, "RL")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal == "BUY"

    def test_high_confidence_sell_overrides(self):
        """SELL의 confidence*weight가 높으면 SELL 승리."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.2, "B": 0.2, "RL": 0.6}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.3, "A")],
            "B": [_make_signal("005930", "BUY", 0.3, "B")],
            "RL": [_make_signal("005930", "SELL", 0.95, "RL")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal == "SELL"

    def test_multiple_tickers_blending(self):
        """여러 티커가 각각 독립적으로 블렌딩."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.5, "B": 0.5}
        )
        predictions = {
            "A": [
                _make_signal("005930", "BUY", 0.9, "A"),
                _make_signal("035720", "SELL", 0.8, "A"),
            ],
            "B": [
                _make_signal("005930", "BUY", 0.7, "B"),
                _make_signal("035720", "SELL", 0.9, "B"),
            ],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 2
        signals_by_ticker = {s.ticker: s.signal for s in blended}
        assert signals_by_ticker["005930"] == "BUY"
        assert signals_by_ticker["035720"] == "SELL"

    def test_empty_strategy_excluded_from_blending(self):
        """빈 시그널 전략은 블렌딩에서 제외되고 나머지 가중치 재정규화."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.9, "A")],
            "B": [_make_signal("005930", "BUY", 0.7, "B")],
            "RL": [],  # 빈 시그널
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal == "BUY"
        # 내부에서 fallback 기록이 남아야 함
        assert orch._last_blend_fallback is not None
        assert "RL" in orch._last_blend_fallback["excluded"]

    def test_all_strategies_empty(self):
        """모든 전략이 빈 시그널이면 빈 결과."""
        orch = OrchestratorAgent()
        predictions = {"A": [], "B": [], "RL": []}
        blended = orch._blend_nway_predictions(predictions)
        assert blended == []

    def test_blended_signal_properties(self):
        """블렌딩된 시그널의 속성 검증."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 1.0})
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.85, "A")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        s = blended[0]
        assert s.agent_id == "orchestrator_blend"
        assert s.llm_model == "blend"
        assert s.strategy == "BLEND"
        assert 0 <= s.confidence <= 1.0
        assert "N-way blend" in s.reasoning_summary

    def test_hold_signal_in_blending(self):
        """HOLD 시그널이 블렌딩에 포함."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        predictions = {
            "A": [_make_signal("005930", "HOLD", 0.9, "A")],
            "B": [_make_signal("005930", "HOLD", 0.8, "B")],
            "RL": [_make_signal("005930", "BUY", 0.3, "RL")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal == "HOLD"

    def test_confidence_bounded_zero_to_one(self):
        """블렌딩된 confidence는 0~1 범위."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        predictions = {
            "A": [_make_signal("005930", "BUY", 1.0, "A")],
            "B": [_make_signal("005930", "BUY", 1.0, "B")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert 0 <= blended[0].confidence <= 1.0

    def test_ticker_not_in_all_strategies(self):
        """일부 전략에만 있는 티커도 블렌딩에 포함."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.5, "B": 0.5}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.9, "A")],
            "B": [_make_signal("035720", "SELL", 0.8, "B")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 2


# ── Dynamic Weight Optimization Tests ────────────────────────────────────────


@pytest.mark.unit
class TestDynamicWeights:
    """동적 가중치 최적화 관련 테스트."""

    def test_default_blend_weights_sum(self):
        """기본 가중치 합은 1.0."""
        total = sum(DEFAULT_BLEND_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-6

    def test_custom_weights_preserved(self):
        custom = {"A": 0.6, "B": 0.4}
        orch = OrchestratorAgent(strategy_blend_weights=custom)
        assert orch.strategy_blend_weights["A"] == 0.6
        assert orch.strategy_blend_weights["B"] == 0.4


# ── Blend Meta Tests ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBlendMeta:
    """블렌딩 메타 정보 검증."""

    def test_blend_fallback_initialized_none(self):
        orch = OrchestratorAgent()
        # _last_blend_fallback은 초기에는 None (attribute가 없을 수도 있음)
        assert not hasattr(orch, "_last_blend_fallback") or orch._last_blend_fallback is None


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBlendingEdgeCases:
    """블렌딩 에지 케이스."""

    def test_single_ticker_all_hold(self):
        """모든 전략이 HOLD이면 HOLD."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        predictions = {
            "A": [_make_signal("005930", "HOLD", 0.5, "A")],
            "B": [_make_signal("005930", "HOLD", 0.5, "B")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert blended[0].signal == "HOLD"

    def test_zero_confidence_signals(self):
        """confidence가 0이면 스코어에 기여 없음."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.0, "A")],
            "B": [_make_signal("005930", "SELL", 0.9, "B")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert blended[0].signal == "SELL"

    def test_many_tickers_performance(self):
        """100개 티커 블렌딩 성능 테스트."""
        orch = OrchestratorAgent(strategy_blend_weights={"A": 0.5, "B": 0.5})
        predictions = {
            "A": [_make_signal(f"{i:06d}", "BUY", 0.8, "A") for i in range(100)],
            "B": [_make_signal(f"{i:06d}", "BUY", 0.7, "B") for i in range(100)],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 100

    def test_equal_buy_sell_hold_scores(self):
        """BUY/SELL/HOLD 스코어가 동일하면 max()가 하나를 선택."""
        orch = OrchestratorAgent(
            strategy_blend_weights={"A": 0.33, "B": 0.33, "RL": 0.34}
        )
        predictions = {
            "A": [_make_signal("005930", "BUY", 0.5, "A")],
            "B": [_make_signal("005930", "SELL", 0.5, "B")],
            "RL": [_make_signal("005930", "HOLD", 0.5, "RL")],
        }
        blended = orch._blend_nway_predictions(predictions)
        assert len(blended) == 1
        assert blended[0].signal in ("BUY", "SELL", "HOLD")
