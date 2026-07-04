"""
test/test_hard_stop_loss.py — Phase A Hard Stop-Loss 단위 테스트.

docs/plans/SELL_STRATEGY_PHASES.md §3 스펙 검증:
    - L1 개별 -7% 트리거 + trigger_source='hard_stop_L1' + snapshot attach
    - Take profit +5% 트리거 + trigger_source='take_profit'
    - L2 포트 dd -8% 트리거 + 최약체 2 종목 + trigger_source='hard_stop_L2'
    - L1 이 이미 잡은 종목은 L2 중복 발주 X
    - L3 lockout 시 L1/L2 발주 X
    - Dry-run True 시 broker.execute_order 미호출

Mock 전략: DB 함수 (get_positions_for_scope, fetchrow, get_portfolio_config)
와 Redis 락, broker 는 AsyncMock 로 대체. 순수 결정 로직 (임계 비교 · 최약체
선정 · trigger metadata attach) 만 unit test.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.portfolio_manager import PortfolioManagerAgent


# ── Fixtures ────────────────────────────────────────────────────


CFG_DEFAULT = {
    "individual_stop_loss_pct": 7,
    "take_profit_pct": 5,
    "portfolio_drawdown_limit_pct": 8,
    "daily_loss_limit_pct": 3,
    "enable_paper_trading": True,
    "enable_real_trading": False,
    "primary_account_scope": "paper",
}


def _position(ticker: str, qty: int, avg_price: int, current_price: int) -> dict:
    return {
        "ticker": ticker,
        "quantity": qty,
        "avg_price": avg_price,
        "current_price": current_price,
    }


# ── _check_rule_based_exits — Layer 1 & take profit ────────────────


@pytest.mark.asyncio
async def test_l1_stop_loss_triggers_at_minus_7pct():
    """개별 -7% 도달 시 hard_stop_L1 signal 생성 + snapshot attach.

    avg_fill_price wavg (broker_orders) 사용, snapshot.avg_fill_source
    는 broker_orders_wavg.
    """
    agent = PortfolioManagerAgent()
    positions = [_position("005930", qty=10, avg_price=70000, current_price=65100)]  # -7%
    with (
        patch("src.db.queries.get_positions_for_scope", new=AsyncMock(return_value=positions)),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={"005930": 70000}),  # broker wavg 70000
        ),
    ):
        signals = await agent._check_rule_based_exits([], CFG_DEFAULT, "paper")

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal == "SELL"
    assert sig.strategy == "EXIT"
    assert sig.trigger_source == "hard_stop_L1"
    assert sig.trigger_snapshot is not None
    assert sig.trigger_snapshot["layer"] == 1
    assert sig.trigger_snapshot["stop_line_pct"] == -7
    assert sig.trigger_snapshot["avg_fill_price"] == 70000
    assert sig.trigger_snapshot["avg_fill_source"] == "broker_orders_wavg"
    assert sig.trigger_snapshot["current_price"] == 65100


@pytest.mark.asyncio
async def test_l1_uses_broker_wavg_over_position_avg_price():
    """avg_fill_price wavg 가 avg_price 와 다르면 wavg 기준으로 판정.

    slippage 시나리오: avg_price=70000 (요청가) 이지만 실 체결 wavg=70300 (슬리피지).
    -7% 임계 계산은 70300 기준.
    """
    agent = PortfolioManagerAgent()
    # current_price=65379 → 70300 대비 -7.0%, 70000 대비 -6.6%
    positions = [_position("005930", qty=10, avg_price=70000, current_price=65379)]
    with (
        patch("src.db.queries.get_positions_for_scope", new=AsyncMock(return_value=positions)),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={"005930": 70300}),
        ),
    ):
        signals = await agent._check_rule_based_exits([], CFG_DEFAULT, "paper")

    assert len(signals) == 1
    assert signals[0].trigger_source == "hard_stop_L1"
    assert signals[0].trigger_snapshot["avg_fill_price"] == 70300


@pytest.mark.asyncio
async def test_l1_fallback_to_position_avg_price_when_broker_empty():
    """broker_orders 없으면 portfolio_positions.avg_price fallback."""
    agent = PortfolioManagerAgent()
    positions = [_position("005930", qty=10, avg_price=70000, current_price=65100)]
    with (
        patch("src.db.queries.get_positions_for_scope", new=AsyncMock(return_value=positions)),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={}),  # broker 데이터 없음
        ),
    ):
        signals = await agent._check_rule_based_exits([], CFG_DEFAULT, "paper")

    assert len(signals) == 1
    assert signals[0].trigger_snapshot["avg_fill_price"] == 70000
    assert signals[0].trigger_snapshot["avg_fill_source"] == "portfolio_positions_fallback"


@pytest.mark.asyncio
async def test_l1_does_not_trigger_above_threshold():
    """-6% 는 임계 미도달 → signal 없음."""
    agent = PortfolioManagerAgent()
    positions = [_position("005930", qty=10, avg_price=70000, current_price=65800)]  # -6%
    with (
        patch("src.db.queries.get_positions_for_scope", new=AsyncMock(return_value=positions)),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={"005930": 70000}),
        ),
    ):
        signals = await agent._check_rule_based_exits([], CFG_DEFAULT, "paper")
    assert signals == []


@pytest.mark.asyncio
async def test_take_profit_triggers_at_plus_5pct():
    """+5% 도달 시 take_profit signal 생성."""
    agent = PortfolioManagerAgent()
    positions = [_position("005930", qty=10, avg_price=70000, current_price=73500)]  # +5%
    with (
        patch("src.db.queries.get_positions_for_scope", new=AsyncMock(return_value=positions)),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={"005930": 70000}),
        ),
    ):
        signals = await agent._check_rule_based_exits([], CFG_DEFAULT, "paper")

    assert len(signals) == 1
    sig = signals[0]
    assert sig.trigger_source == "take_profit"
    assert sig.trigger_snapshot["take_profit_line_pct"] == 5
    assert sig.trigger_snapshot["stop_line_pct"] is None
    assert sig.trigger_snapshot["layer"] is None


@pytest.mark.asyncio
async def test_config_override_stop_loss_pct():
    """cfg.individual_stop_loss_pct=10 → -10% 에서만 트리거."""
    agent = PortfolioManagerAgent()
    cfg = {**CFG_DEFAULT, "individual_stop_loss_pct": 10}
    positions = [_position("005930", qty=10, avg_price=70000, current_price=65100)]  # -7%
    with (
        patch("src.db.queries.get_positions_for_scope", new=AsyncMock(return_value=positions)),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={"005930": 70000}),
        ),
    ):
        signals = await agent._check_rule_based_exits([], cfg, "paper")
    assert signals == []  # -7% 는 -10% 임계 미도달


# ── _check_portfolio_drawdown — Layer 2 ────────────────────────


@pytest.mark.asyncio
async def test_l2_no_baseline_returns_empty():
    """Baseline 스냅샷 없으면 판정 불가 → 빈 리스트."""
    agent = PortfolioManagerAgent()
    with (
        patch(
            "src.utils.db_client.fetchrow",
            new=AsyncMock(
                side_effect=[
                    {"total_equity": 900_000},  # 현재
                    None,  # baseline 없음
                ]
            ),
        ),
        patch(
            "src.db.queries.get_positions_for_scope",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={}),
        ),
    ):
        signals = await agent._check_portfolio_drawdown(CFG_DEFAULT, "paper")
    assert signals == []


@pytest.mark.asyncio
async def test_l2_triggers_weakest_two_when_dd_exceeds_limit():
    """포트 dd -10% ≤ -8% 임계 → 최약체 2 종목 SELL."""
    agent = PortfolioManagerAgent()
    positions = [
        _position("A", qty=10, avg_price=1000, current_price=850),   # -15% (worst)
        _position("B", qty=10, avg_price=1000, current_price=900),   # -10%
        _position("C", qty=10, avg_price=1000, current_price=950),   # -5%
        _position("D", qty=10, avg_price=1000, current_price=1100),  # +10%
    ]
    with (
        patch(
            "src.utils.db_client.fetchrow",
            new=AsyncMock(
                side_effect=[
                    {"total_equity": 900_000},
                    {"total_equity": 1_000_000},  # dd -10%
                ]
            ),
        ),
        patch(
            "src.db.queries.get_positions_for_scope",
            new=AsyncMock(return_value=positions),
        ),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={"A": 1000, "B": 1000, "C": 1000, "D": 1000}),
        ),
    ):
        signals = await agent._check_portfolio_drawdown(CFG_DEFAULT, "paper")

    assert len(signals) == 2
    tickers = {s.ticker for s in signals}
    assert tickers == {"A", "B"}  # 최약체 2 종목
    for sig in signals:
        assert sig.trigger_source == "hard_stop_L2"
        assert sig.trigger_snapshot["layer"] == 2
        assert sig.trigger_snapshot["portfolio_dd_pct"] < -8
        assert sig.trigger_snapshot["avg_fill_source"] == "broker_orders_wavg"


@pytest.mark.asyncio
async def test_l2_does_not_trigger_within_limit():
    """포트 dd -5% > -8% → 트리거 X."""
    agent = PortfolioManagerAgent()
    with (
        patch(
            "src.utils.db_client.fetchrow",
            new=AsyncMock(
                side_effect=[
                    {"total_equity": 950_000},
                    {"total_equity": 1_000_000},  # dd -5%
                ]
            ),
        ),
        patch(
            "src.db.queries.get_positions_for_scope",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.db.queries.compute_avg_fill_price_by_ticker",
            new=AsyncMock(return_value={}),
        ),
    ):
        signals = await agent._check_portfolio_drawdown(CFG_DEFAULT, "paper")
    assert signals == []


# ── _hard_stop_scan — 통합 흐름 ──────────────────────────────────


@pytest.mark.asyncio
async def test_hard_stop_scan_l3_lockout_returns_empty():
    """L3 (일일 -3%) 도달 시 L1/L2 판정 없이 조기 return + persistent flag 세팅."""
    agent = PortfolioManagerAgent()
    with (
        patch(
            "src.services.trading_mode.is_hard_stop_lockout_active",
            new=AsyncMock(return_value=False),
        ),
        patch("src.services.trading_mode.set_hard_stop_lockout", new=AsyncMock()),
        patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(True, -3.5))),
        patch.object(agent, "_publish_circuit_breaker", new=AsyncMock()),
        patch.object(agent, "_check_rule_based_exits", new=AsyncMock(return_value=[])) as l1_mock,
        patch.object(agent, "_check_portfolio_drawdown", new=AsyncMock(return_value=[])) as l2_mock,
    ):
        result = await agent._hard_stop_scan(CFG_DEFAULT, "paper")

    assert result == []
    assert l1_mock.await_count == 0  # L3 lockout 시 L1 조회 안 함
    assert l2_mock.await_count == 0


@pytest.mark.asyncio
async def test_hard_stop_scan_dry_run_skips_broker_execution():
    """Dry-run True 시 process_signal 호출 안 하고 return dict list."""
    from src.db.models import PredictionSignal

    agent = PortfolioManagerAgent()
    l1_sig = PredictionSignal(
        agent_id="rule_based_exit",
        llm_model="rule",
        strategy="EXIT",
        ticker="005930",
        signal="SELL",
        confidence=1.0,
        trading_date=date.today(),
        trigger_source="hard_stop_L1",
        trigger_snapshot={"layer": 1},
    )
    with (
        patch(
            "src.services.trading_mode.is_hard_stop_lockout_active",
            new=AsyncMock(return_value=False),
        ),
        patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(False, -0.5))),
        patch.object(agent, "_check_rule_based_exits", new=AsyncMock(return_value=[l1_sig])),
        patch.object(agent, "_check_portfolio_drawdown", new=AsyncMock(return_value=[])),
        patch(
            "src.services.trading_mode.is_hard_stop_dry_run",
            new=AsyncMock(return_value=True),
        ),
        patch.object(agent, "process_signal", new=AsyncMock()) as ps_mock,
    ):
        result = await agent._hard_stop_scan(CFG_DEFAULT, "paper")

    assert ps_mock.await_count == 0  # broker 발주 X
    assert len(result) == 1
    assert result[0]["dry_run"] is True
    assert result[0]["ticker"] == "005930"
    assert result[0]["trigger_source"] == "hard_stop_L1"


@pytest.mark.asyncio
async def test_hard_stop_scan_dedup_l2_when_l1_already_covers_ticker():
    """L1 이 이미 잡은 종목을 L2 가 중복 대상으로 지목해도 dedup 되어 L1 만 발주."""
    from src.db.models import PredictionSignal

    agent = PortfolioManagerAgent()
    l1_sig = PredictionSignal(
        agent_id="rule_based_exit", llm_model="rule", strategy="EXIT",
        ticker="005930", signal="SELL", confidence=1.0, trading_date=date.today(),
        trigger_source="hard_stop_L1", trigger_snapshot={"layer": 1},
    )
    l2_dup = PredictionSignal(
        agent_id="rule_based_exit", llm_model="rule", strategy="EXIT",
        ticker="005930", signal="SELL", confidence=1.0, trading_date=date.today(),
        trigger_source="hard_stop_L2", trigger_snapshot={"layer": 2},
    )
    l2_unique = PredictionSignal(
        agent_id="rule_based_exit", llm_model="rule", strategy="EXIT",
        ticker="000660", signal="SELL", confidence=1.0, trading_date=date.today(),
        trigger_source="hard_stop_L2", trigger_snapshot={"layer": 2},
    )
    with (
        patch(
            "src.services.trading_mode.is_hard_stop_lockout_active",
            new=AsyncMock(return_value=False),
        ),
        patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(False, -0.5))),
        patch.object(agent, "_check_rule_based_exits", new=AsyncMock(return_value=[l1_sig])),
        patch.object(agent, "_check_portfolio_drawdown", new=AsyncMock(return_value=[l2_dup, l2_unique])),
        patch(
            "src.services.trading_mode.is_hard_stop_dry_run",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await agent._hard_stop_scan(CFG_DEFAULT, "paper")

    # L1 (005930) + L2 (000660, 005930 중복 제거) = 2 개
    assert len(result) == 2
    tickers = {r["ticker"] for r in result}
    assert tickers == {"005930", "000660"}
    triggers_by_ticker = {r["ticker"]: r["trigger_source"] for r in result}
    assert triggers_by_ticker["005930"] == "hard_stop_L1"
    assert triggers_by_ticker["000660"] == "hard_stop_L2"


# ── is_hard_stop_dry_run — trading_mode 패턴 재활용 ─────────────


@pytest.mark.asyncio
async def test_dry_run_default_true_when_no_env_no_redis():
    """Redis 값 없고 env 미설정 시 default True (자본 보존 안전)."""
    import os

    from src.services.trading_mode import is_hard_stop_dry_run

    with (
        patch("src.services.trading_mode.get_redis", side_effect=Exception("no redis")),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("HARD_STOP_LOSS_DRY_RUN", None)
        assert (await is_hard_stop_dry_run()) is True


@pytest.mark.asyncio
async def test_dry_run_env_false_disables():
    """env HARD_STOP_LOSS_DRY_RUN=false → False."""
    import os

    from src.services.trading_mode import is_hard_stop_dry_run

    with (
        patch("src.services.trading_mode.get_redis", side_effect=Exception("no redis")),
        patch.dict(os.environ, {"HARD_STOP_LOSS_DRY_RUN": "false"}, clear=False),
    ):
        assert (await is_hard_stop_dry_run()) is False


@pytest.mark.asyncio
async def test_dry_run_redis_true_overrides_env_false():
    """Redis 값이 env 를 override."""
    import os

    from src.services.trading_mode import is_hard_stop_dry_run

    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value=b"true")

    with (
        patch("src.services.trading_mode.get_redis", new=AsyncMock(return_value=fake_redis)),
        patch.dict(os.environ, {"HARD_STOP_LOSS_DRY_RUN": "false"}, clear=False),
    ):
        assert (await is_hard_stop_dry_run()) is True


# ── L3 persistent lockout (다음 거래일까지) ─────────────────────


@pytest.mark.asyncio
async def test_hard_stop_scan_persistent_lockout_early_return():
    """전일 -3% 흔적 Redis flag 활성 시 L1/L2 판정 없이 조기 return."""
    agent = PortfolioManagerAgent()
    with (
        patch(
            "src.services.trading_mode.is_hard_stop_lockout_active",
            new=AsyncMock(return_value=True),
        ),
        patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock()) as daily_mock,
        patch.object(agent, "_check_rule_based_exits", new=AsyncMock(return_value=[])) as l1_mock,
        patch.object(agent, "_check_portfolio_drawdown", new=AsyncMock(return_value=[])) as l2_mock,
    ):
        result = await agent._hard_stop_scan(CFG_DEFAULT, "paper")

    assert result == []
    assert daily_mock.await_count == 0  # persistent flag 활성 시 daily 체크 안 함
    assert l1_mock.await_count == 0
    assert l2_mock.await_count == 0


@pytest.mark.asyncio
async def test_hard_stop_scan_l3_daily_trigger_sets_persistent_lockout():
    """L3 daily 트리거 시 set_hard_stop_lockout 호출로 다음 거래일까지 유지."""
    agent = PortfolioManagerAgent()
    with (
        patch(
            "src.services.trading_mode.is_hard_stop_lockout_active",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "src.services.trading_mode.set_hard_stop_lockout",
            new=AsyncMock(),
        ) as set_mock,
        patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock(return_value=(True, -3.7))),
        patch.object(agent, "_publish_circuit_breaker", new=AsyncMock()),
    ):
        result = await agent._hard_stop_scan(CFG_DEFAULT, "paper")

    assert result == []
    assert set_mock.await_count == 1
    call_args = set_mock.await_args
    assert call_args.args[0] == "paper"
    # 2 번째 인자는 datetime (next_trading_day_start 결과)
    from datetime import datetime
    assert isinstance(call_args.args[1], datetime)


def test_next_trading_day_start_weekday_to_next_weekday():
    """수요일 → 목요일 09:00."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.utils.market_hours import next_trading_day_start

    kst = ZoneInfo("Asia/Seoul")
    wed_afternoon = datetime(2026, 7, 8, 14, 30, tzinfo=kst)  # 수요일
    result = next_trading_day_start(wed_afternoon)
    assert result.weekday() == 3  # 목요일
    assert result.hour == 9
    assert result.minute == 0


def test_next_trading_day_start_friday_to_monday():
    """금요일 → 월요일 09:00 (주말 skip)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.utils.market_hours import next_trading_day_start

    kst = ZoneInfo("Asia/Seoul")
    fri_afternoon = datetime(2026, 7, 10, 14, 30, tzinfo=kst)  # 금요일
    result = next_trading_day_start(fri_afternoon)
    assert result.weekday() == 0  # 월요일
    assert result.hour == 9


def test_next_trading_day_start_saturday_to_monday():
    """토요일 → 월요일 09:00."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.utils.market_hours import next_trading_day_start

    kst = ZoneInfo("Asia/Seoul")
    sat = datetime(2026, 7, 11, 10, 0, tzinfo=kst)  # 토요일
    result = next_trading_day_start(sat)
    assert result.weekday() == 0  # 월요일


@pytest.mark.asyncio
async def test_process_predictions_respects_persistent_lockout():
    """process_predictions (LLM 사이클) 도 persistent lockout 존중.

    자정 넘어 다음 거래일 되어 _is_daily_loss_blocked 는 False 여도
    persistent flag 있으면 매매 skip.
    """
    from datetime import date

    from src.db.models import PredictionSignal

    agent = PortfolioManagerAgent()
    signal = PredictionSignal(
        agent_id="predictor_1",
        llm_model="manual",
        strategy="A",
        ticker="005930",
        signal="BUY",
        confidence=0.7,
        trading_date=date.today(),
    )

    with (
        patch(
            "src.agents.portfolio_manager.get_portfolio_config",
            new=AsyncMock(return_value=CFG_DEFAULT),
        ),
        patch(
            "src.agents.portfolio_manager.market_session_status",
            new=AsyncMock(return_value="open"),
        ),
        patch(
            "src.services.trading_mode.is_hard_stop_lockout_active",
            new=AsyncMock(return_value=True),
        ),
        patch.object(agent, "_is_daily_loss_blocked", new=AsyncMock()) as daily_mock,
        patch.object(agent, "process_signal", new=AsyncMock()) as ps_mock,
        patch("src.agents.portfolio_manager.publish_message", new=AsyncMock()),
        patch("src.agents.portfolio_manager.set_heartbeat", new=AsyncMock()),
        patch("src.agents.portfolio_manager.insert_heartbeat", new=AsyncMock()),
    ):
        orders = await agent.process_predictions([signal])

    assert orders == []
    assert daily_mock.await_count == 0  # persistent flag 있으면 daily 체크 skip
    assert ps_mock.await_count == 0  # 매매 X
