"""
src/utils/risk_validation.py — 리스크 규칙 검증 유틸
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

from src.agents.portfolio_manager import PortfolioManagerAgent
from src.db.models import PredictionSignal


def _build_buy_signal() -> PredictionSignal:
    return PredictionSignal(
        agent_id="predictor_1",
        llm_model="manual",
        strategy="A",
        ticker="005930",
        signal="BUY",
        confidence=0.7,
        trading_date=date.today(),
    )


async def validate_max_position_limit() -> dict[str, Any]:
    agent = PortfolioManagerAgent()
    signal = _build_buy_signal()

    with (
        patch.object(
            agent,
            "_resolve_name_and_price",
            new=AsyncMock(return_value=("삼성전자", 1_000)),
        ),
        patch(
            "src.agents.portfolio_manager.get_position",
            new=AsyncMock(return_value={"quantity": 5, "current_price": 1_000, "avg_price": 1_000}),
        ),
        patch("src.agents.portfolio_manager.portfolio_total_value", new=AsyncMock(return_value=6_000)),
        patch("src.agents.portfolio_manager.save_position", new=AsyncMock()) as save_mock,
        patch("src.agents.portfolio_manager.insert_trade", new=AsyncMock()) as trade_mock,
    ):
        result = await agent.process_signal(
            signal,
            risk_config={"max_position_pct": 50, "is_paper_trading": True},
        )

    ok = result is None and save_mock.await_count == 0 and trade_mock.await_count == 0
    return {
        "key": "risk:max_position_limit",
        "ok": ok,
        "message": "최대 포지션 비중 초과 시 BUY 차단" if ok else "최대 포지션 비중 차단 검증 실패",
    }


async def validate_daily_loss_circuit_breaker() -> dict[str, Any]:
    agent = PortfolioManagerAgent()
    signal = _build_buy_signal()

    with (
        patch(
            "src.agents.portfolio_manager.get_portfolio_config",
            new=AsyncMock(return_value={"daily_loss_limit_pct": 3, "max_position_pct": 20}),
        ),
        patch(
            "src.agents.portfolio_manager.today_trade_totals",
            new=AsyncMock(return_value={"buy_total": 10_000, "sell_total": 9_200}),
        ),
        patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()) as publish_mock,
        patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()) as heartbeat_mock,
        patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()) as insert_hb_mock,
        patch.object(agent, "process_signal", new=AsyncMock()) as process_signal_mock,
    ):
        orders = await agent.process_predictions([signal])

    ok = (
        orders == []
        and process_signal_mock.await_count == 0
        and publish_mock.await_count == 1
        and heartbeat_mock.await_count == 1
        and insert_hb_mock.await_count == 1
    )
    return {
        "key": "risk:daily_loss_circuit_breaker",
        "ok": ok,
        "message": "일일 손실 한도 도달 시 주문 중단" if ok else "서킷브레이커 검증 실패",
    }


async def validate_daily_loss_allows_when_within_limit() -> dict[str, Any]:
    agent = PortfolioManagerAgent()
    signal = _build_buy_signal()
    expected_order = {"ticker": "005930", "side": "BUY", "quantity": 1, "price": 70000}

    with (
        patch(
            "src.agents.portfolio_manager.get_portfolio_config",
            new=AsyncMock(return_value={"daily_loss_limit_pct": 3, "max_position_pct": 20}),
        ),
        patch(
            "src.agents.portfolio_manager.today_trade_totals",
            new=AsyncMock(return_value={"buy_total": 10_000, "sell_total": 9_800}),
        ),
        patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()) as publish_mock,
        patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()) as heartbeat_mock,
        patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()) as insert_hb_mock,
        patch.object(agent, "process_signal", new=AsyncMock(return_value=expected_order)) as process_signal_mock,
    ):
        orders = await agent.process_predictions([signal])

    ok = (
        len(orders) == 1
        and orders[0]["ticker"] == expected_order["ticker"]
        and process_signal_mock.await_count == 1
        and publish_mock.await_count == 1
        and heartbeat_mock.await_count == 1
        and insert_hb_mock.await_count == 1
    )
    return {
        "key": "risk:daily_loss_normal_flow",
        "ok": ok,
        "message": "손실 한도 미도달 시 주문 처리 지속" if ok else "정상 주문 흐름 검증 실패",
    }


async def run_risk_rule_validation() -> dict[str, Any]:
    checks = [
        await validate_max_position_limit(),
        await validate_daily_loss_circuit_breaker(),
        await validate_daily_loss_allows_when_within_limit(),
    ]
    passed = all(check["ok"] for check in checks)
    summary = "리스크 규칙 검증 통과" if passed else "리스크 규칙 검증 실패"
    return {
        "passed": passed,
        "summary": summary,
        "checks": checks,
    }
