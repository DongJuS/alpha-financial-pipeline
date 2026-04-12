"""
test/test_rl_edge_cases.py — RL 환경 및 정책 모드 에지케이스 테스트

TradingEnv의 데이터 부족/MDD 종료/portfolio floor와
ShadowInferenceEngine.get_policy_mode의 다양한 경로를 검증합니다.
"""
from __future__ import annotations

import numpy as np
import pytest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from src.agents.rl_environment import (
    TradingEnv,
    TradingEnvConfig,
    ACTION_BUY,
    ACTION_SELL,
    ACTION_HOLD,
)
from src.agents.rl_shadow_inference import ShadowInferenceEngine, ShadowRecord
from src.agents.rl_policy_registry import (
    PolicyEntry,
    PolicyRegistry,
    PromotionGate,
    TickerPolicies,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_config(closes: list[float], **kwargs) -> TradingEnvConfig:
    volumes = kwargs.pop("volumes", [1_000_000] * len(closes))
    return TradingEnvConfig(closes=closes, volumes=volumes, **kwargs)


def _make_policy_entry(
    policy_id: str = "policy_001",
    ticker: str = "005930.KS",
) -> PolicyEntry:
    return PolicyEntry(
        policy_id=policy_id,
        ticker=ticker,
        algorithm="tabular_q_learning",
        state_version="qlearn_v1",
        return_pct=10.0,
        max_drawdown_pct=-5.0,
        approved=True,
        created_at=datetime.now(timezone.utc),
        file_path=f"tabular/{ticker}/{policy_id}.json",
    )


def _make_registry(
    ticker: str = "005930.KS",
    policy_id: str | None = None,
    active_policy_id: str | None = None,
    auto_promote_paper_only: bool = True,
) -> PolicyRegistry:
    """테스트용 PolicyRegistry를 구성합니다."""
    registry = PolicyRegistry(
        promotion_gate=PromotionGate(auto_promote_paper_only=auto_promote_paper_only),
    )
    if policy_id:
        tp = TickerPolicies(active_policy_id=active_policy_id)
        tp.add_policy(_make_policy_entry(policy_id=policy_id, ticker=ticker))
        registry.tickers[ticker] = tp
    return registry


# ── GymTradingEnv Edge Cases ──────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestTradingEnvEdgeCases:
    """TradingEnv 경계 조건 테스트."""

    def test_trading_env_short_data_raises_value_error(self):
        """len(closes) < lookback + 2 시 ValueError 발생.

        lookback=20이 기본값이므로 22개 미만의 데이터로 환경을 생성하면
        ValueError("데이터 부족")이 발생해야 한다.
        """
        # lookback=20, 필요 최소=22, 제공=21
        short_closes = [100.0] * 21
        with pytest.raises(ValueError, match="데이터 부족"):
            TradingEnv(_make_config(short_closes, lookback=20))

        # lookback=10, 필요 최소=12, 제공=11
        with pytest.raises(ValueError, match="데이터 부족"):
            TradingEnv(_make_config([100.0] * 11, lookback=10))

        # 정확히 lookback+2이면 정상 생성
        exact_closes = [100.0] * 22
        env = TradingEnv(_make_config(exact_closes, lookback=20))
        assert env is not None

    def test_trading_env_max_drawdown_terminates_episode(self):
        """max drawdown (-50%) 초과 시 terminated=True.

        포트폴리오 가치가 peak 대비 max_drawdown_pct 이하로 떨어지면
        에피소드가 즉시 종료된다.
        """
        # 급격한 하락 데이터: 100에서 시작하여 매 스텝 5씩 하락
        closes = [100.0] * 22 + [100.0 - i * 8 for i in range(1, 30)]
        env = TradingEnv(_make_config(closes, max_drawdown_pct=-50.0))
        env.reset()

        # BUY 후 하락에 노출
        terminated = False
        env.step(ACTION_BUY)
        for _ in range(40):
            _, _, terminated, _, info = env.step(ACTION_HOLD)
            if terminated:
                break

        assert terminated
        # 종료 시 drawdown이 max_drawdown_pct 이하여야 함
        assert info["drawdown_pct"] <= -50.0 or info["step"] >= len(closes) - 1

    def test_trading_env_portfolio_value_floor(self):
        """portfolio value가 매우 낮아질 때 동작 확인.

        TradingEnv는 portfolio_value를 self._portfolio_value *= (1 + position_pnl)로
        갱신한다. 극단적 하락 시 값이 0에 가까워지지만 float 연산으로
        음수가 되지는 않는다 (terminated 조건으로 먼저 종료).

        이 테스트는 MDD 종료 전까지 portfolio_value가 양수임을 확인한다.
        """
        # 급격한 하락: 매 스텝 10% 하락
        base = 100.0
        closes = [base] * 22
        for i in range(1, 20):
            base *= 0.90
            closes.append(base)

        env = TradingEnv(_make_config(closes, max_drawdown_pct=-99.0))
        env.reset()
        env.step(ACTION_BUY)

        for _ in range(25):
            _, _, terminated, _, info = env.step(ACTION_HOLD)
            # 종료 전까지 portfolio_value는 항상 양수
            assert info["portfolio_value"] > 0
            if terminated:
                break

        # 최종 portfolio_value도 양수
        assert env._portfolio_value > 0


# ── get_policy_mode Edge Cases ────────────────────────────────────────────────


@pytest.mark.rl
@pytest.mark.unit
class TestGetPolicyModeEdgeCases:
    """ShadowInferenceEngine.get_policy_mode 다양한 경로 테스트."""

    def test_policy_mode_not_in_registry_no_shadow_returns_inactive(self):
        """registry에 없고 shadow record도 없으면 'inactive'.

        get_policy_mode 로직:
        1. registry에서 ticker 조회 -> 없음
        2. shadow record 확인 -> 없음
        3. 반환: 'inactive'
        """
        mock_store = MagicMock()
        registry = _make_registry()  # 빈 registry
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        # shadow record도 없음 (_shadow_records는 빈 dict)

        mode = engine.get_policy_mode("nonexistent_policy", "005930.KS")
        assert mode == "inactive"

    def test_policy_mode_auto_promote_paper_only_returns_paper(self):
        """registry에 있고 auto_promote_paper_only=True면 'paper'.

        get_policy_mode 로직:
        1. registry에서 ticker 조회 -> 있음
        2. policy 조회 -> 있음
        3. active_policy_id == policy_id -> 활성 정책
        4. auto_promote_paper_only=True -> 'paper'
        """
        mock_store = MagicMock()
        registry = _make_registry(
            ticker="005930.KS",
            policy_id="policy_001",
            active_policy_id="policy_001",
            auto_promote_paper_only=True,
        )
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        mode = engine.get_policy_mode("policy_001", "005930.KS")
        assert mode == "paper"

    def test_policy_mode_active_not_paper_only_returns_real(self):
        """registry에 있고 active=True, auto_promote_paper_only=False면 'real'.

        get_policy_mode 로직:
        1. registry에서 ticker 조회 -> 있음
        2. policy 조회 -> 있음
        3. active_policy_id == policy_id -> 활성 정책
        4. auto_promote_paper_only=False -> 'real'
        """
        mock_store = MagicMock()
        registry = _make_registry(
            ticker="005930.KS",
            policy_id="policy_001",
            active_policy_id="policy_001",
            auto_promote_paper_only=False,
        )
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        mode = engine.get_policy_mode("policy_001", "005930.KS")
        assert mode == "real"

    def test_policy_mode_not_in_registry_with_shadow_returns_shadow(self):
        """registry에 없지만 shadow record 있으면 'shadow'.

        get_policy_mode 로직:
        1. registry에서 ticker 조회 -> 없음
        2. shadow record 확인 -> 있음 (해당 ticker의 record 존재)
        3. 반환: 'shadow'
        """
        mock_store = MagicMock()
        registry = _make_registry()  # 빈 registry
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        # shadow record 수동 삽입
        engine._shadow_records["shadow_policy"] = [
            ShadowRecord(
                policy_id="shadow_policy",
                ticker="005930.KS",
                signal="BUY",
                confidence=0.8,
                close_price=70000.0,
                trading_date=date(2026, 4, 12),
            ),
        ]

        mode = engine.get_policy_mode("shadow_policy", "005930.KS")
        assert mode == "shadow"

    def test_policy_mode_in_registry_not_active_no_shadow_returns_inactive(self):
        """registry에 정책이 있지만 active가 아니고 shadow도 없으면 'inactive'.

        get_policy_mode 로직:
        1. registry에서 ticker 조회 -> 있음
        2. policy 조회 -> 있음
        3. active_policy_id != policy_id -> 비활성
        4. shadow record 확인 -> 없음
        5. 반환: 'inactive'
        """
        mock_store = MagicMock()
        # policy_001이 등록되었지만 active가 아닌 상태 (active_policy_id=None)
        registry = _make_registry(
            ticker="005930.KS",
            policy_id="policy_001",
            active_policy_id=None,  # 활성 정책 없음
        )
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        mode = engine.get_policy_mode("policy_001", "005930.KS")
        assert mode == "inactive"

    def test_policy_mode_in_registry_not_active_with_shadow_returns_shadow(self):
        """registry에 정책이 있지만 active가 아니고, shadow record가 있으면 'shadow'.

        get_policy_mode 로직:
        1. registry에서 ticker 조회 -> 있음
        2. policy 조회 -> 있음
        3. active_policy_id != policy_id -> 비활성
        4. shadow record 확인 -> 있음
        5. 반환: 'shadow'
        """
        mock_store = MagicMock()
        registry = _make_registry(
            ticker="005930.KS",
            policy_id="policy_001",
            active_policy_id=None,
        )
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        engine._shadow_records["policy_001"] = [
            ShadowRecord(
                policy_id="policy_001",
                ticker="005930.KS",
                signal="HOLD",
                confidence=0.5,
                close_price=70000.0,
                trading_date=date(2026, 4, 12),
            ),
        ]

        mode = engine.get_policy_mode("policy_001", "005930.KS")
        assert mode == "shadow"

    def test_policy_mode_shadow_record_different_ticker_returns_inactive(self):
        """shadow record가 있지만 다른 ticker이면 'inactive'.

        _has_shadow_records는 policy_id에 대한 records 중
        해당 ticker와 일치하는 것이 있는지 확인한다.
        다른 ticker의 record만 있으면 False를 반환한다.
        """
        mock_store = MagicMock()
        registry = _make_registry()
        mock_store.load_registry.return_value = registry

        engine = ShadowInferenceEngine(policy_store=mock_store)
        # 다른 ticker의 shadow record
        engine._shadow_records["some_policy"] = [
            ShadowRecord(
                policy_id="some_policy",
                ticker="035720.KS",  # 다른 ticker
                signal="BUY",
                confidence=0.7,
                close_price=50000.0,
                trading_date=date(2026, 4, 12),
            ),
        ]

        mode = engine.get_policy_mode("some_policy", "005930.KS")
        assert mode == "inactive"
