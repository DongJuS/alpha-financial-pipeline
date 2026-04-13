"""
test/test_rl_shadow_inference.py — Shadow Inference & Promotion Gate 테스트

ShadowInferenceEngine의 시그널 생성, 성과 추적, 승격 게이트 평가를 검증합니다.
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.agents.rl_shadow_inference import (
    ShadowInferenceEngine,
    ShadowRecord,
    PaperPromotionCriteria,
    RealPromotionCriteria,
    PromotionCheckResult,
)
from src.db.models import PredictionSignal


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_policy_store():
    """RLPolicyStoreV2 mock (DB 기반)."""
    store = MagicMock()
    store.list_policies = AsyncMock(return_value=[])
    store.list_active_policies = AsyncMock(return_value={})
    store.list_all_tickers = AsyncMock(return_value=[])
    return store


def _engine(**kwargs):
    return ShadowInferenceEngine(
        policy_store=_mock_policy_store(),
        **kwargs,
    )


# ── Shadow Signal Creation Tests ─────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestShadowSignalCreation:
    """Shadow 시그널 생성 테스트."""

    def test_create_shadow_signal_returns_prediction(self):
        engine = _engine()
        signal = engine.create_shadow_signal(
            policy_id="test_policy",
            ticker="005930",
            signal="BUY",
            confidence=0.8,
            close_price=70000.0,
        )
        assert isinstance(signal, PredictionSignal)
        assert signal.is_shadow is True
        assert signal.signal == "BUY"
        assert signal.ticker == "005930"
        assert signal.confidence == 0.8
        assert signal.strategy == "RL"
        assert "[SHADOW]" in signal.reasoning_summary

    def test_shadow_signal_records_stored(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1",
            ticker="005930",
            signal="BUY",
            confidence=0.7,
            close_price=70000.0,
        )
        assert len(engine._shadow_records["p1"]) == 1

    def test_multiple_signals_same_policy(self):
        engine = _engine()
        for _ in range(5):
            engine.create_shadow_signal(
                policy_id="p1",
                ticker="005930",
                signal="BUY",
                confidence=0.6,
                close_price=70000.0,
            )
        assert len(engine._shadow_records["p1"]) == 5

    def test_multiple_policies(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=70000.0,
        )
        engine.create_shadow_signal(
            policy_id="p2", ticker="035720", signal="SELL",
            confidence=0.6, close_price=50000.0,
        )
        assert "p1" in engine._shadow_records
        assert "p2" in engine._shadow_records


# ── Shadow Performance Tests ─────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestShadowPerformance:
    """Shadow 성과 계산 테스트."""

    def test_empty_performance(self):
        engine = _engine()
        perf = engine.get_shadow_performance("nonexistent")
        assert perf.total_trades == 0
        assert perf.shadow_days == 0
        assert perf.simulated_return_pct == 0.0

    def test_performance_with_signals(self):
        engine = _engine()
        # 10일간 BUY/SELL 교대
        for i in range(10):
            sig = "BUY" if i % 2 == 0 else "SELL"
            engine.create_shadow_signal(
                policy_id="p1",
                ticker="005930",
                signal=sig,
                confidence=0.7,
                close_price=70000.0 + i * 100,
            )

        perf = engine.get_shadow_performance("p1", "005930")
        assert perf.buy_signals == 5
        assert perf.sell_signals == 5
        assert perf.hold_signals == 0
        assert perf.total_trades == 10
        assert perf.shadow_days >= 1

    def test_performance_avg_confidence(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.6, close_price=70000.0,
        )
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="SELL",
            confidence=0.8, close_price=71000.0,
        )
        perf = engine.get_shadow_performance("p1", "005930")
        assert perf.avg_confidence == pytest.approx(0.7, abs=0.01)

    def test_performance_ticker_filter(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=70000.0,
        )
        engine.create_shadow_signal(
            policy_id="p1", ticker="035720", signal="SELL",
            confidence=0.8, close_price=50000.0,
        )
        perf_930 = engine.get_shadow_performance("p1", "005930")
        assert perf_930.ticker == "005930"
        assert perf_930.buy_signals == 1
        assert perf_930.sell_signals == 0


# ── Shadow Return Simulation Tests ──────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestShadowReturnSimulation:
    """Shadow 수익률 시뮬레이션 테스트."""

    def test_simulate_buy_then_sell_profit(self):
        engine = _engine()
        records = [
            ShadowRecord(
                policy_id="p1", ticker="005930", signal="BUY",
                confidence=0.8, close_price=100.0,
                trading_date=date(2026, 4, 1),
            ),
            ShadowRecord(
                policy_id="p1", ticker="005930", signal="SELL",
                confidence=0.8, close_price=110.0,
                trading_date=date(2026, 4, 2),
            ),
        ]
        ret, mdd = engine._simulate_shadow_returns(records)
        assert ret == pytest.approx(10.0, abs=0.1)
        assert mdd <= 0.0

    def test_simulate_buy_then_sell_loss(self):
        engine = _engine()
        records = [
            ShadowRecord(
                policy_id="p1", ticker="005930", signal="BUY",
                confidence=0.8, close_price=100.0,
                trading_date=date(2026, 4, 1),
            ),
            ShadowRecord(
                policy_id="p1", ticker="005930", signal="SELL",
                confidence=0.8, close_price=90.0,
                trading_date=date(2026, 4, 2),
            ),
        ]
        ret, mdd = engine._simulate_shadow_returns(records)
        assert ret < 0

    def test_simulate_empty_records(self):
        engine = _engine()
        ret, mdd = engine._simulate_shadow_returns([])
        assert ret == 0.0
        assert mdd == 0.0

    def test_simulate_single_record(self):
        engine = _engine()
        records = [
            ShadowRecord(
                policy_id="p1", ticker="005930", signal="BUY",
                confidence=0.8, close_price=100.0,
                trading_date=date(2026, 4, 1),
            ),
        ]
        ret, mdd = engine._simulate_shadow_returns(records)
        assert ret == 0.0


# ── Promotion Gate: Shadow → Paper ──────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestShadowToPaperPromotion:
    """Shadow → Paper 승격 게이트 테스트."""

    def test_all_criteria_met(self):
        criteria = PaperPromotionCriteria(
            min_shadow_days=1,
            min_shadow_trades=1,
            min_return_pct=0.0,
            max_drawdown_limit_pct=-50.0,
            min_avg_confidence=0.3,
            require_walk_forward_approval=False,
        )
        engine = _engine(paper_criteria=criteria)

        # 충분한 기록 생성
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="SELL",
            confidence=0.7, close_price=110.0,
        )

        result = engine.evaluate_shadow_to_paper("p1", "005930")
        assert isinstance(result, PromotionCheckResult)
        assert result.passed is True
        assert result.promotion_type == "shadow_to_paper"

    def test_insufficient_days(self):
        criteria = PaperPromotionCriteria(
            min_shadow_days=100,
            require_walk_forward_approval=False,
        )
        engine = _engine(paper_criteria=criteria)
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        result = engine.evaluate_shadow_to_paper("p1", "005930")
        assert result.passed is False
        assert any("shadow_days" in f for f in result.failures)

    def test_insufficient_trades(self):
        criteria = PaperPromotionCriteria(
            min_shadow_days=1,
            min_shadow_trades=100,
            require_walk_forward_approval=False,
        )
        engine = _engine(paper_criteria=criteria)
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        result = engine.evaluate_shadow_to_paper("p1", "005930")
        assert result.passed is False
        assert any("total_trades" in f for f in result.failures)

    def test_walk_forward_required_but_not_run(self):
        criteria = PaperPromotionCriteria(
            min_shadow_days=1,
            min_shadow_trades=1,
            require_walk_forward_approval=True,
        )
        engine = _engine(paper_criteria=criteria)
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        result = engine.evaluate_shadow_to_paper(
            "p1", "005930", walk_forward_approved=None,
        )
        assert result.passed is False
        assert any("walk_forward" in f for f in result.failures)

    def test_walk_forward_failed(self):
        criteria = PaperPromotionCriteria(
            min_shadow_days=1,
            min_shadow_trades=1,
            require_walk_forward_approval=True,
        )
        engine = _engine(paper_criteria=criteria)
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        result = engine.evaluate_shadow_to_paper(
            "p1", "005930",
            walk_forward_approved=False,
            walk_forward_consistency=0.3,
        )
        assert result.passed is False

    def test_low_avg_confidence(self):
        criteria = PaperPromotionCriteria(
            min_shadow_days=1,
            min_shadow_trades=1,
            min_avg_confidence=0.9,
            require_walk_forward_approval=False,
        )
        engine = _engine(paper_criteria=criteria)
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.3, close_price=100.0,
        )
        result = engine.evaluate_shadow_to_paper("p1", "005930")
        assert result.passed is False
        assert any("avg_confidence" in f for f in result.failures)


# ── Promotion Gate: Paper → Real ────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestPaperToRealPromotion:
    """Paper → Real 승격 게이트 테스트."""

    def test_all_criteria_met(self):
        criteria = RealPromotionCriteria(
            require_walk_forward_approval=False,
        )
        engine = _engine(real_criteria=criteria)
        result = engine.evaluate_paper_to_real(
            "p1", "005930",
            paper_days=60,
            paper_trades=50,
            paper_return_pct=10.0,
            paper_max_drawdown_pct=-5.0,
            paper_sharpe_ratio=1.0,
        )
        assert result.passed is True
        assert result.promotion_type == "paper_to_real"

    def test_insufficient_paper_days(self):
        criteria = RealPromotionCriteria(
            min_paper_days=30,
            require_walk_forward_approval=False,
        )
        engine = _engine(real_criteria=criteria)
        result = engine.evaluate_paper_to_real(
            "p1", "005930",
            paper_days=10,
            paper_trades=50,
            paper_return_pct=10.0,
            paper_max_drawdown_pct=-5.0,
            paper_sharpe_ratio=1.0,
        )
        assert result.passed is False
        assert any("paper_days" in f for f in result.failures)

    def test_low_sharpe_ratio(self):
        criteria = RealPromotionCriteria(
            min_sharpe_ratio=1.0,
            require_walk_forward_approval=False,
        )
        engine = _engine(real_criteria=criteria)
        result = engine.evaluate_paper_to_real(
            "p1", "005930",
            paper_days=60,
            paper_trades=50,
            paper_return_pct=10.0,
            paper_max_drawdown_pct=-5.0,
            paper_sharpe_ratio=0.3,
        )
        assert result.passed is False
        assert any("sharpe" in f for f in result.failures)

    def test_excessive_drawdown(self):
        criteria = RealPromotionCriteria(
            max_drawdown_limit_pct=-15.0,
            require_walk_forward_approval=False,
        )
        engine = _engine(real_criteria=criteria)
        result = engine.evaluate_paper_to_real(
            "p1", "005930",
            paper_days=60,
            paper_trades=50,
            paper_return_pct=10.0,
            paper_max_drawdown_pct=-25.0,
            paper_sharpe_ratio=1.0,
        )
        assert result.passed is False
        assert any("drawdown" in f for f in result.failures)

    def test_multiple_failures(self):
        criteria = RealPromotionCriteria(
            min_paper_days=30,
            min_paper_trades=20,
            min_return_pct=5.0,
            max_drawdown_limit_pct=-15.0,
            min_sharpe_ratio=0.5,
            require_walk_forward_approval=False,
        )
        engine = _engine(real_criteria=criteria)
        result = engine.evaluate_paper_to_real(
            "p1", "005930",
            paper_days=5,
            paper_trades=2,
            paper_return_pct=-10.0,
            paper_max_drawdown_pct=-30.0,
            paper_sharpe_ratio=0.1,
        )
        assert result.passed is False
        assert len(result.failures) >= 4


# ── Shadow Records Management Tests ─────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestShadowRecordsManagement:
    """Shadow 기록 관리 테스트."""

    def test_clear_specific_policy(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        engine.create_shadow_signal(
            policy_id="p2", ticker="035720", signal="SELL",
            confidence=0.6, close_price=50000.0,
        )
        removed = engine.clear_shadow_records("p1")
        assert removed == 1
        assert "p1" not in engine._shadow_records
        assert "p2" in engine._shadow_records

    def test_clear_all_records(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        engine.create_shadow_signal(
            policy_id="p2", ticker="035720", signal="SELL",
            confidence=0.6, close_price=50000.0,
        )
        total = engine.clear_shadow_records()
        assert total == 2
        assert len(engine._shadow_records) == 0

    def test_get_shadow_records(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        records = engine.get_shadow_records("p1")
        assert len(records) == 1
        assert records[0]["ticker"] == "005930"

    def test_get_shadow_records_with_ticker_filter(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        engine.create_shadow_signal(
            policy_id="p1", ticker="035720", signal="SELL",
            confidence=0.6, close_price=50000.0,
        )
        records = engine.get_shadow_records("p1", "005930")
        assert len(records) == 1

    def test_list_shadow_policies(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        engine.create_shadow_signal(
            policy_id="p2", ticker="035720", signal="SELL",
            confidence=0.6, close_price=50000.0,
        )
        policies = engine.list_shadow_policies()
        assert len(policies) == 2
        policy_ids = {p["policy_id"] for p in policies}
        assert policy_ids == {"p1", "p2"}


# ── Policy Mode Tests ───────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestPolicyMode:
    """정책 모드 판별 테스트."""

    @pytest.mark.asyncio
    async def test_inactive_policy_no_records(self):
        engine = _engine()
        mode = await engine.get_policy_mode("unknown_policy", "005930")
        assert mode == "inactive"

    @pytest.mark.asyncio
    async def test_shadow_mode_with_records(self):
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        mode = await engine.get_policy_mode("p1", "005930")
        assert mode == "shadow"


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestShadowEdgeCases:
    """Shadow Inference 에지 케이스."""

    def test_zero_confidence_signal(self):
        engine = _engine()
        signal = engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="HOLD",
            confidence=0.0, close_price=70000.0,
        )
        assert signal.confidence == 0.0

    def test_zero_close_price(self):
        engine = _engine()
        signal = engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="SELL",
            confidence=0.5, close_price=0.0,
        )
        assert signal.target_price == 0

    def test_clear_nonexistent_policy(self):
        engine = _engine()
        removed = engine.clear_shadow_records("nonexistent")
        assert removed == 0

    def test_performance_hold_only(self):
        engine = _engine()
        for _ in range(5):
            engine.create_shadow_signal(
                policy_id="p1", ticker="005930", signal="HOLD",
                confidence=0.5, close_price=100.0,
            )
        perf = engine.get_shadow_performance("p1")
        assert perf.hold_signals == 5
        assert perf.total_trades == 0


# ── Policy Mode Branch Tests ──────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestPolicyModeBranches:
    """get_policy_mode의 다양한 분기 테스트 (DB 기반)."""

    def _make_entry(self, policy_id="p1", ticker="005930", is_active=False):
        from src.agents.rl_policy_registry import PolicyEntry
        return PolicyEntry(
            policy_id=policy_id,
            instrument_id=ticker,
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            return_pct=10.0,
            max_drawdown_pct=-5.0,
            approved=True,
            is_active=is_active,
            created_at=datetime.now(timezone.utc),
            file_path=f"tabular/{ticker}/{policy_id}.json",
        )

    @pytest.mark.asyncio
    async def test_no_policy_in_db_no_shadow_records(self):
        """DB에 정책 없고 shadow 기록도 없으면 inactive."""
        engine = _engine()
        mode = await engine.get_policy_mode("unknown_policy", "005930")
        assert mode == "inactive"

    @pytest.mark.asyncio
    async def test_no_policy_in_db_with_shadow_records(self):
        """DB에 정책 없지만 shadow 기록 있으면 shadow."""
        engine = _engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        mode = await engine.get_policy_mode("p1", "005930")
        assert mode == "shadow"

    @pytest.mark.asyncio
    async def test_policy_in_db_but_different_id(self):
        """DB에 티커는 있지만 해당 정책이 없으면 inactive."""
        store = _mock_policy_store()
        store.list_policies = AsyncMock(return_value=[
            self._make_entry(policy_id="other_policy", ticker="005930"),
        ])

        engine = ShadowInferenceEngine(policy_store=store)
        mode = await engine.get_policy_mode("p1", "005930")
        assert mode == "inactive"

    @pytest.mark.asyncio
    async def test_policy_exists_but_not_active(self):
        """정책이 존재하지만 활성이 아니면 shadow/inactive."""
        store = _mock_policy_store()
        store.list_policies = AsyncMock(return_value=[
            self._make_entry(policy_id="p1", ticker="005930", is_active=False),
        ])

        engine = ShadowInferenceEngine(policy_store=store)
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.7, close_price=100.0,
        )
        mode = await engine.get_policy_mode("p1", "005930")
        assert mode == "shadow"

    @pytest.mark.asyncio
    async def test_active_policy_returns_paper(self):
        """활성 정책 → paper."""
        store = _mock_policy_store()
        store.list_policies = AsyncMock(return_value=[
            self._make_entry(policy_id="p1", ticker="005930", is_active=True),
        ])

        engine = ShadowInferenceEngine(policy_store=store)
        mode = await engine.get_policy_mode("p1", "005930")
        assert mode == "paper"

    @pytest.mark.asyncio
    async def test_different_tickers_different_modes(self):
        """동일 정책이 티커에 따라 다른 모드일 수 있다."""
        store = _mock_policy_store()

        async def mock_list_policies(ticker):
            if ticker == "005930":
                return [self._make_entry(policy_id="p1", ticker="005930", is_active=True)]
            return []

        store.list_policies = AsyncMock(side_effect=mock_list_policies)

        engine = ShadowInferenceEngine(policy_store=store)
        assert await engine.get_policy_mode("p1", "005930") == "paper"
        assert await engine.get_policy_mode("p1", "035720") == "inactive"
