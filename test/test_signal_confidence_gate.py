"""
test/test_signal_confidence_gate.py — RL/LLM signal confidence gate 단위 테스트

배경: 사용자 mandate "최대한 hold" 반영 (2026-07-08).
    - buy_confidence_threshold / sell_confidence_threshold (기본 0.60) 이상만 실행.
    - hold_bias_enabled=false 로 gate off 가능.
    - Phase A rule-based exit (trigger_source 있음) 는 예외 — confidence 무관 실행.
    - Legacy signal (confidence=None) 는 gate 통과 — backward compat.

Mock 전략: process_signal 내부 broker/DB 호출은 mock. gate 로직 판정만 검증.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.db.models import PredictionSignal


# ── Fixtures ────────────────────────────────────────────────────


CFG_GATE_ON = {
    "hold_bias_enabled": True,
    "buy_confidence_threshold": 0.60,
    "sell_confidence_threshold": 0.60,
    "max_position_pct": 20,
    "daily_loss_limit_pct": 3,
    "enable_paper_trading": True,
    "enable_real_trading": False,
    "primary_account_scope": "paper",
}


def _signal(
    action: str,
    ticker: str = "005930",
    confidence: float | None = 0.8,
    trigger_source: str | None = None,
) -> PredictionSignal:
    return PredictionSignal(
        agent_id="test-agent",
        llm_model="test-model",
        strategy="RL",
        ticker=ticker,
        signal=action,
        confidence=confidence,
        trading_date=date.today(),
        trigger_source=trigger_source,
    )


def _make_agent() -> PortfolioManagerAgent:
    # PortfolioManagerAgent 는 broker 를 내부 build 함수로 자동 세팅 (인자 X).
    # test 에서는 attribute 재할당으로 mock 대체 — gate 판정만 검증.
    agent = PortfolioManagerAgent(agent_id="test-pm")
    agent.paper_broker = AsyncMock()
    agent.real_broker = AsyncMock()
    agent.virtual_broker = AsyncMock()
    return agent


# ── gate ON: 임계값 미만이면 return None ─────────────────────────


@pytest.mark.asyncio
async def test_buy_below_threshold_skips_execution():
    """confidence 0.5 < 0.60 → BUY 스킵, return None."""
    agent = _make_agent()
    signal = _signal("BUY", confidence=0.50)

    result = await agent.process_signal(signal, risk_config=CFG_GATE_ON)

    assert result is None
    agent.paper_broker.execute_order.assert_not_called()


@pytest.mark.asyncio
async def test_sell_below_threshold_skips_execution():
    """SELL confidence 0.4 < 0.60 → 스킵. Phase A stop-loss 는 별도 (trigger_source 있음)."""
    agent = _make_agent()
    signal = _signal("SELL", confidence=0.40)

    result = await agent.process_signal(signal, risk_config=CFG_GATE_ON)

    assert result is None
    agent.paper_broker.execute_order.assert_not_called()


# ── gate ON: 임계값 이상이면 실행 (broker 도달) ─────────────────


@pytest.mark.asyncio
async def test_buy_at_or_above_threshold_proceeds():
    """confidence 0.75 ≥ 0.60 → gate 통과. 이후 로직으로 진행."""
    agent = _make_agent()
    signal = _signal("BUY", confidence=0.75)

    # _resolve_name_and_price 를 mock 해서 price=0 로 만들면 gate 통과 후
    # "가격 없음" 로그로 return None. 그래도 gate 는 뚫었다는 의미.
    with patch.object(
        agent, "_resolve_name_and_price", new=AsyncMock(return_value=("삼성전자", 0))
    ):
        result = await agent.process_signal(signal, risk_config=CFG_GATE_ON)

    # gate 는 통과. price=0 로 인해 skip 됐지만 gate 판정 자체는 성공.
    assert result is None
    agent._resolve_name_and_price.assert_awaited_once()


# ── trigger_source 있는 signal (Phase A) → gate 무시 ──────────────


@pytest.mark.asyncio
async def test_rule_based_exit_bypasses_gate():
    """
    Phase A rule-based exit (예: hard_stop_L1) 은 trigger_source 가 있으므로
    낮은 confidence 로도 실행되어야 함. 사용자 원칙: 낙폭 보호는 무조건.
    """
    agent = _make_agent()
    signal = _signal(
        "SELL",
        confidence=0.10,  # 매우 낮음
        trigger_source="hard_stop_L1",
    )

    with patch.object(
        agent, "_resolve_name_and_price", new=AsyncMock(return_value=("삼성전자", 0))
    ):
        result = await agent.process_signal(signal, risk_config=CFG_GATE_ON)

    # gate 미적용 (trigger_source 있음). price=0 이후 skip 이지만 gate 판정
    # 이 skip 아님. _resolve_name_and_price 호출로 확인.
    assert result is None
    agent._resolve_name_and_price.assert_awaited_once()


# ── hold_bias_enabled=false → gate off ─────────────────────────────


@pytest.mark.asyncio
async def test_gate_disabled_ignores_low_confidence():
    """hold_bias_enabled=false 면 confidence 무관하게 실행."""
    agent = _make_agent()
    cfg = {**CFG_GATE_ON, "hold_bias_enabled": False}
    signal = _signal("BUY", confidence=0.10)

    with patch.object(
        agent, "_resolve_name_and_price", new=AsyncMock(return_value=("삼성전자", 0))
    ):
        result = await agent.process_signal(signal, risk_config=cfg)

    assert result is None  # price=0 이유로만 skip
    agent._resolve_name_and_price.assert_awaited_once()  # gate 뚫음


# ── confidence=None (legacy) → 통과 (backward compat) ──────────────


@pytest.mark.asyncio
async def test_confidence_none_passes_gate():
    """Legacy signal 로 confidence 저장 안 됐으면 gate 통과."""
    agent = _make_agent()
    signal = _signal("BUY", confidence=None)

    with patch.object(
        agent, "_resolve_name_and_price", new=AsyncMock(return_value=("삼성전자", 0))
    ):
        result = await agent.process_signal(signal, risk_config=CFG_GATE_ON)

    assert result is None  # price=0 이유로만 skip
    agent._resolve_name_and_price.assert_awaited_once()


# ── HOLD signal → 원래 early return (gate 관여 X) ──────────────────


@pytest.mark.asyncio
async def test_hold_signal_still_returns_none_early():
    """HOLD 는 gate 앞에 있는 early return 로 처리. 회귀 확인."""
    agent = _make_agent()
    signal = _signal("HOLD", confidence=0.99)

    result = await agent.process_signal(signal, risk_config=CFG_GATE_ON)

    assert result is None
    # HOLD 는 early return 이라 _resolve_name_and_price 도 호출 안 됨.
    agent.paper_broker.execute_order.assert_not_called()
