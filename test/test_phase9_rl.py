"""
test/test_phase9_rl.py — Phase 9 RL Trading Lane 통합 테스트

Phase 9 구현 항목:
1. RLDatasetBuilderV2 — 기술지표 + 매크로 컨텍스트 확장 데이터셋
2. TradingEnv — Gymnasium 호환 트레이딩 환경
3. WalkForwardEvaluator — Walk-forward 교차 검증
4. ShadowInferenceEngine — Shadow 추론 + 승격 게이트
5. RL REST API — 정책 관리 / 실험 / shadow / promotion 엔드포인트
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timezone

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# 1. RLDatasetBuilderV2
# ═══════════════════════════════════════════════════════════════════════════


class TestRLDatasetBuilderV2:
    """기술지표 계산과 상태 벡터 변환을 검증합니다."""

    def test_technical_features_calculation(self):
        from src.agents.rl_dataset_builder_v2 import TechnicalFeatures

        # 충분한 길이의 가격 데이터 생성
        closes = [10000 + i * 100 for i in range(70)]
        volumes = [1_000_000 + random.randint(-100_000, 100_000) for _ in range(70)]

        features = TechnicalFeatures.compute(closes, volumes, index=69)

        assert features.sma_5 > 0
        assert features.sma_20 > 0
        assert features.sma_60 > 0
        assert 0.0 <= features.rsi_14 <= 100.0
        assert features.volatility_10 >= 0.0
        assert features.volume_ratio > 0.0
        assert isinstance(features.return_1d, float)

    def test_technical_features_insufficient_data(self):
        from src.agents.rl_dataset_builder_v2 import TechnicalFeatures

        closes = [10000, 10100, 10200]
        volumes = [1000, 1100, 1200]

        features = TechnicalFeatures.compute(closes, volumes, index=2)
        # SMA_60은 데이터 부족 시 사용 가능한 만큼으로 계산
        assert features.sma_5 > 0 or features.sma_60 == 0.0

    def test_enriched_dataset_state_vector(self):
        from src.agents.rl_dataset_builder_v2 import (
            EnrichedRLDataset,
            MarketContext,
            TechnicalFeatures,
        )

        features_list = []
        for i in range(10):
            features_list.append(
                TechnicalFeatures(
                    sma_5=10000.0 + i * 50,
                    sma_20=10000.0 + i * 20,
                    sma_60=10000.0 + i * 10,
                    rsi_14=50.0 + i,
                    volatility_10=0.02,
                    volume_ratio=1.1,
                    return_1d=0.01,
                )
            )

        dataset = EnrichedRLDataset(
            ticker="005930",
            closes=[10000 + i * 100 for i in range(10)],
            volumes=[1_000_000] * 10,
            timestamps=["2026-03-01"] * 10,
            features=features_list,
            market_context=MarketContext(),
        )

        state_vector = dataset.to_state_vector(9)
        assert isinstance(state_vector, dict)
        assert "sma_5" in state_vector
        assert "rsi_14" in state_vector
        assert "kospi_change_pct" in state_vector


# ═══════════════════════════════════════════════════════════════════════════
# 2. TradingEnv
# ═══════════════════════════════════════════════════════════════════════════


class TestTradingEnv:
    """Gymnasium 호환 트레이딩 환경을 검증합니다."""

    def _make_env(self, n_steps: int = 100):
        from src.agents.rl_environment import TradingEnv, TradingEnvConfig

        closes = [10000 + i * 50 + random.randint(-30, 30) for i in range(n_steps)]
        volumes = [1_000_000] * n_steps
        config = TradingEnvConfig(lookback=5)
        return TradingEnv(closes=closes, volumes=volumes, config=config)

    def test_reset(self):
        env = self._make_env()
        obs = env.reset()
        assert isinstance(obs, dict)
        assert env.current_step >= 0

    def test_step_hold(self):
        env = self._make_env()
        env.reset()
        obs, reward, done, info = env.step(2)  # HOLD=2
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert "portfolio_value" in info

    def test_full_episode(self):
        env = self._make_env(50)
        env.reset()
        done = False
        steps = 0
        while not done:
            action = random.randint(0, 2)  # BUY/SELL/HOLD
            obs, reward, done, info = env.step(action)
            steps += 1
            if steps > 200:
                break
        summary = env.get_episode_summary()
        assert "total_return_pct" in summary
        assert "max_drawdown_pct" in summary
        assert "trades" in summary

    def test_buy_sell_sequence(self):
        env = self._make_env(20)
        env.reset()
        # BUY
        obs, reward, done, info = env.step(0)  # BUY
        assert env.position == 1
        # SELL
        obs, reward, done, info = env.step(1)  # SELL
        assert env.position == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. WalkForwardEvaluator
# ═══════════════════════════════════════════════════════════════════════════


class TestWalkForwardEvaluator:
    """Walk-forward 교차 검증을 검증합니다."""

    def test_evaluate_basic(self):
        from src.agents.rl_walk_forward import WalkForwardEvaluator

        # 충분한 데이터
        closes = [10000 + i * 10 for i in range(200)]

        evaluator = WalkForwardEvaluator(n_folds=3, expanding_window=True)

        # V1 trainer 사용
        from src.agents.rl_trading import TabularQTrainer

        trainer = TabularQTrainer()
        result = evaluator.evaluate(closes, trainer)

        assert result.n_folds == 3
        assert len(result.folds) == 3
        assert 0.0 <= result.consistency_score <= 1.0
        assert isinstance(result.approved, bool)

    def test_evaluate_insufficient_data(self):
        from src.agents.rl_walk_forward import WalkForwardEvaluator

        closes = [10000, 10100, 10200]
        evaluator = WalkForwardEvaluator(n_folds=2)

        from src.agents.rl_trading import TabularQTrainer

        trainer = TabularQTrainer()

        with pytest.raises(ValueError):
            evaluator.evaluate(closes, trainer)

    def test_sliding_vs_expanding(self):
        from src.agents.rl_walk_forward import WalkForwardEvaluator

        closes = [10000 + i * 10 for i in range(200)]
        from src.agents.rl_trading import TabularQTrainer

        trainer = TabularQTrainer()

        expanding = WalkForwardEvaluator(n_folds=3, expanding_window=True)
        sliding = WalkForwardEvaluator(n_folds=3, expanding_window=False)

        result_e = expanding.evaluate(closes, trainer)
        result_s = sliding.evaluate(closes, trainer)

        # 둘 다 3-fold 결과 생성
        assert len(result_e.folds) == 3
        assert len(result_s.folds) == 3

    def test_result_to_dict(self):
        from src.agents.rl_walk_forward import WalkForwardEvaluator
        from src.agents.rl_trading import TabularQTrainer

        closes = [10000 + i * 10 for i in range(200)]
        evaluator = WalkForwardEvaluator(n_folds=2)
        trainer = TabularQTrainer()
        result = evaluator.evaluate(closes, trainer)

        d = result.to_dict()
        assert "n_folds" in d
        assert "consistency_score" in d
        assert "approved" in d
        assert "folds" in d


# ═══════════════════════════════════════════════════════════════════════════
# 4. ShadowInferenceEngine
# ═══════════════════════════════════════════════════════════════════════════


class TestShadowInferenceEngine:
    """Shadow 추론 및 승격 게이트를 검증합니다."""

    def _make_engine(self):
        from src.agents.rl_shadow_inference import ShadowInferenceEngine

        return ShadowInferenceEngine()

    def test_create_shadow_signal(self):
        engine = self._make_engine()
        signal = engine.create_shadow_signal(
            policy_id="test-policy-001",
            ticker="005930",
            signal="BUY",
            confidence=0.75,
            close_price=72000,
        )
        assert signal.is_shadow is True
        assert signal.strategy == "RL"
        assert signal.signal == "BUY"
        assert "[SHADOW]" in signal.reasoning_summary

    def test_shadow_performance_tracking(self):
        engine = self._make_engine()
        policy_id = "test-policy-002"

        for i in range(5):
            engine.create_shadow_signal(
                policy_id=policy_id,
                ticker="005930",
                signal="BUY" if i % 2 == 0 else "SELL",
                confidence=0.6 + i * 0.05,
                close_price=70000 + i * 500,
            )

        perf = engine.get_shadow_performance(policy_id, "005930")
        assert perf.policy_id == policy_id
        assert perf.total_trades == 5  # 3 BUY + 2 SELL
        assert perf.buy_signals == 3
        assert perf.sell_signals == 2
        assert perf.avg_confidence > 0

    def test_shadow_to_paper_gate_fail(self):
        engine = self._make_engine()
        # 기록 없이 평가하면 실패
        result = engine.evaluate_shadow_to_paper(
            policy_id="nonexistent",
            ticker="005930",
        )
        assert result.passed is False
        assert len(result.failures) > 0
        assert result.promotion_type == "shadow_to_paper"

    def test_shadow_to_paper_gate_with_walk_forward(self):
        engine = self._make_engine()
        policy_id = "test-policy-wf"

        # Shadow 기록 충분히 생성
        for i in range(15):
            engine.create_shadow_signal(
                policy_id=policy_id,
                ticker="005930",
                signal="BUY" if i % 3 == 0 else ("SELL" if i % 3 == 1 else "HOLD"),
                confidence=0.7,
                close_price=70000 + i * 200,
            )

        # Walk-forward 미통과
        result = engine.evaluate_shadow_to_paper(
            policy_id=policy_id,
            ticker="005930",
            walk_forward_approved=False,
            walk_forward_consistency=0.3,
        )
        assert result.passed is False
        assert any("walk_forward" in f for f in result.failures)

    def test_paper_to_real_gate(self):
        engine = self._make_engine()
        result = engine.evaluate_paper_to_real(
            policy_id="test-real",
            ticker="005930",
            paper_days=60,
            paper_trades=30,
            paper_return_pct=8.0,
            paper_max_drawdown_pct=-8.0,
            paper_sharpe_ratio=1.2,
            walk_forward_approved=True,
        )
        assert result.passed is True
        assert result.promotion_type == "paper_to_real"

    def test_paper_to_real_gate_insufficient(self):
        engine = self._make_engine()
        result = engine.evaluate_paper_to_real(
            policy_id="test-real-fail",
            ticker="005930",
            paper_days=10,  # < 30
            paper_trades=5,  # < 20
            paper_return_pct=1.0,  # < 5.0
            paper_max_drawdown_pct=-20.0,  # < -15.0
            paper_sharpe_ratio=0.2,  # < 0.5
        )
        assert result.passed is False
        assert len(result.failures) >= 4

    def test_list_shadow_policies(self):
        engine = self._make_engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.6, close_price=70000,
        )
        engine.create_shadow_signal(
            policy_id="p2", ticker="035720", signal="SELL",
            confidence=0.7, close_price=45000,
        )
        policies = engine.list_shadow_policies()
        assert len(policies) == 2
        tickers = {p["ticker"] for p in policies}
        assert "005930" in tickers
        assert "035720" in tickers

    def test_clear_shadow_records(self):
        engine = self._make_engine()
        engine.create_shadow_signal(
            policy_id="p1", ticker="005930", signal="BUY",
            confidence=0.6, close_price=70000,
        )
        removed = engine.clear_shadow_records("p1")
        assert removed == 1
        assert engine.get_shadow_records("p1") == []

    def test_policy_mode(self):
        engine = self._make_engine()
        # 기록 없는 정책 → inactive
        mode = engine.get_policy_mode("unknown", "005930")
        assert mode == "inactive"

        # Shadow 기록 있는 정책 → shadow
        engine.create_shadow_signal(
            policy_id="shadow-p1", ticker="005930", signal="BUY",
            confidence=0.6, close_price=70000,
        )
        mode = engine.get_policy_mode("shadow-p1", "005930")
        assert mode == "shadow"


# ═══════════════════════════════════════════════════════════════════════════
# 5. RL API (구조 검증)
# ═══════════════════════════════════════════════════════════════════════════


class TestRLAPIModels:
    """API 모델과 라우터 구조를 검증합니다."""

    def test_policy_summary_model(self):
        from src.api.routers.rl import PolicySummary

        summary = PolicySummary(
            policy_id="test",
            ticker="005930",
            algorithm="tabular_q_learning",
            state_version="qlearn_v1",
            return_pct=5.0,
            max_drawdown_pct=-10.0,
            trades=15,
            win_rate=0.55,
            approved=True,
            created_at="2026-03-15T00:00:00Z",
        )
        data = summary.model_dump()
        assert data["policy_id"] == "test"
        assert data["approved"] is True

    def test_training_job_request_validation(self):
        from src.api.routers.rl import TrainingJobRequest

        req = TrainingJobRequest(tickers=["005930", "035720"])
        assert len(req.tickers) == 2
        assert req.policy_family == "tabular_q_v2"
        assert req.dataset_interval == "daily"

        # 빈 tickers 는 실패
        with pytest.raises(Exception):
            TrainingJobRequest(tickers=[])

    def test_walk_forward_request_model(self):
        from src.api.routers.rl import WalkForwardRequestModel

        req = WalkForwardRequestModel(ticker="005930")
        assert req.n_folds == 5
        assert req.expanding_window is True
        assert req.trainer_version == "v2"

    def test_shadow_signal_request_model(self):
        from src.api.routers.rl import ShadowSignalRequest

        req = ShadowSignalRequest(
            policy_id="p1",
            ticker="005930",
            signal="BUY",
            close_price=72000,
        )
        assert req.confidence == 0.5  # default
        assert req.signal == "BUY"

    def test_router_has_all_endpoints(self):
        from src.api.routers.rl import router

        paths = [route.path for route in router.routes]

        expected = [
            "/policies",
            "/policies/active",
            "/policies/{ticker}",
            "/policies/{policy_id}/activate",
            "/experiments",
            "/experiments/{run_id}",
            "/evaluations",
            "/training-jobs",
            "/training-jobs/{job_id}",
            "/walk-forward",
            "/shadow/signals",
            "/shadow/policies",
            "/shadow/performance/{policy_id}",
            "/shadow/records/{policy_id}",
            "/promotion/shadow-to-paper",
            "/promotion/paper-to-real",
            "/promotion/policy-mode/{policy_id}",
        ]

        for path in expected:
            assert path in paths, f"엔드포인트 누락: {path}"
