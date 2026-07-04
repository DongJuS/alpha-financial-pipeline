"""
src/agents/portfolio_manager.py — PortfolioManagerAgent MVP (페이퍼 트레이딩)
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.brokers import build_paper_broker, build_real_broker, build_virtual_broker
from src.brokers.virtual_broker import VirtualBroker, VirtualBrokerExecution
from src.constants import PAPER_TRADING_INITIAL_CAPITAL
from src.db.models import AgentHeartbeatRecord, PaperOrderRequest, PredictionSignal
from src.db.queries import (
    fetch_recent_ohlcv,
    fetch_trade_rows_for_date,
    get_portfolio_config,
    get_position,
    get_trading_account,
    insert_heartbeat,
    portfolio_total_value,
)
from src.utils.account_scope import normalize_account_scope
from src.utils.logging import get_logger, setup_logging
from src.utils.market_hours import MARKET_HOURS_ENFORCED, market_session_status
from src.utils.performance import compute_trade_performance
from src.utils.redis_client import (
    KEY_LATEST_TICKS,
    TOPIC_ALERTS,
    TOPIC_ORDERS,
    get_redis,
    publish_message,
    set_heartbeat,
)

setup_logging()
logger = get_logger(__name__)


class PortfolioManagerAgent:
    def __init__(
        self,
        agent_id: str = "portfolio_manager_agent",
        virtual_broker: VirtualBroker | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.paper_broker = build_paper_broker()
        self.real_broker = build_real_broker()
        self.virtual_broker = virtual_broker

    @staticmethod
    def _primary_account_scope_from_config(cfg: dict) -> str:
        scope = cfg.get("primary_account_scope")
        if scope:
            return normalize_account_scope(scope)
        return normalize_account_scope("paper" if bool(cfg.get("is_paper_trading", True)) else "real")

    @classmethod
    def _enabled_account_scopes_from_config(cls, cfg: dict) -> list[str]:
        enable_paper = bool(cfg.get("enable_paper_trading", bool(cfg.get("is_paper_trading", True))))
        enable_real = bool(cfg.get("enable_real_trading", not bool(cfg.get("is_paper_trading", True))))
        primary = cls._primary_account_scope_from_config(cfg)
        enabled = {"paper": enable_paper, "real": enable_real}
        ordered_scopes = [primary, "real" if primary == "paper" else "paper"]
        return [scope for scope in ordered_scopes if enabled.get(scope, False)]

    @staticmethod
    def _broker_for_scope(
        account_scope: str,
        paper_broker,
        real_broker,
        virtual_broker: VirtualBroker | None = None,
    ):
        if account_scope == "virtual":
            if virtual_broker is not None:
                return virtual_broker
            return build_virtual_broker()
        return paper_broker if account_scope == "paper" else real_broker

    async def _daily_realized_pnl_pct(self, account_scope: str) -> float:
        rows = await fetch_trade_rows_for_date(datetime.utcnow().date(), account_scope=account_scope)
        metrics = compute_trade_performance(rows)
        invested_capital = float(metrics.get("invested_capital") or 0)
        realized_pnl = float(metrics.get("realized_pnl") or 0)
        if invested_capital <= 0:
            return 0.0
        return (realized_pnl / invested_capital) * 100.0

    async def _is_daily_loss_blocked(self, account_scope: str, cfg: dict) -> tuple[bool, float]:
        daily_loss_limit_pct = int(cfg.get("daily_loss_limit_pct", 3))
        pnl_pct = await self._daily_realized_pnl_pct(account_scope)
        return pnl_pct <= -daily_loss_limit_pct, pnl_pct

    async def _publish_circuit_breaker(self, account_scope: str, pnl_pct: float, daily_loss_limit_pct: int) -> None:
        message = (
            f"{account_scope} 계좌 일일 손실 한도 도달로 주문 중단 "
            f"(realized_pnl={pnl_pct:.2f}%, limit=-{daily_loss_limit_pct}%)"
        )
        logger.warning(message)
        await publish_message(
            TOPIC_ALERTS,
            json.dumps(
                {
                    "type": "circuit_breaker",
                    "account_scope": account_scope,
                    "message": message,
                },
                ensure_ascii=False,
            ),
        )

    async def _publish_orders_event(
        self,
        *,
        orders: list[dict],
        enabled_scopes: list[str],
        blocked_scopes: list[dict[str, object]],
        market_status: str,
        skip_reason: Optional[str] = None,
    ) -> None:
        await publish_message(
            TOPIC_ORDERS,
            json.dumps(
                {
                    "type": "orders_executed",
                    "agent_id": self.agent_id,
                    "count": len(orders),
                    "enabled_scopes": enabled_scopes,
                    "blocked_scopes": blocked_scopes,
                    "market_hours_enforced": MARKET_HOURS_ENFORCED,
                    "market_status": market_status,
                    "skip_reason": skip_reason,
                    "orders": orders,
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                },
                ensure_ascii=False,
            ),
        )

    async def _record_processing_heartbeat(
        self,
        *,
        status: str,
        last_action: str,
        orders_executed: int,
        enabled_scopes: list[str],
        blocked_scopes: list[dict[str, object]],
        market_status: str,
        skip_reason: Optional[str] = None,
    ) -> None:
        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status=status,
                last_action=last_action,
                metrics={
                    "orders_executed": orders_executed,
                    "enabled_scopes": enabled_scopes,
                    "blocked_scopes": blocked_scopes,
                    "market_hours_enforced": MARKET_HOURS_ENFORCED,
                    "market_status": market_status,
                    "skip_reason": skip_reason,
                },
            )
        )

    async def _resolve_name_and_price(self, ticker: str, target_price: Optional[int]) -> tuple[str, int]:
        if target_price:
            candles = await fetch_recent_ohlcv(ticker, days=5)
            name = candles[0]["name"] if candles else ticker
            return name, int(target_price)

        # 실시간 거래 시 Redis 최신 시세를 우선 사용
        try:
            redis = await get_redis()
            raw = await redis.get(KEY_LATEST_TICKS.format(ticker=ticker))
            if raw:
                payload = json.loads(raw)
                rt_name = str(payload.get("name") or ticker)
                rt_price = int(payload.get("current_price") or 0)
                if rt_price > 0:
                    return rt_name, rt_price
        except Exception as e:
            logger.debug("실시간 시세 조회 실패 [%s]: %s", ticker, e)

        candles = await fetch_recent_ohlcv(ticker, days=5)
        name = candles[0]["name"] if candles else ticker
        latest_close = int(candles[0]["close"]) if candles else 0
        return name, latest_close

    async def _execute_via_broker(
        self,
        broker,
        order: PaperOrderRequest,
    ) -> VirtualBrokerExecution | object:
        """브로커 타입에 따라 올바른 시그니처로 주문을 실행합니다.

        VirtualBroker는 개별 파라미터를 받고,
        PaperBroker/KISBroker는 PaperOrderRequest 객체를 받습니다.
        """
        if isinstance(broker, VirtualBroker):
            return await broker.execute_order(
                ticker=order.ticker,
                side=order.signal,
                quantity=order.quantity,
                price=order.price,
                name=order.name,
                signal_source=order.signal_source or "VIRTUAL",
                trigger_source=order.trigger_source,
                trigger_snapshot=order.trigger_snapshot,
            )
        return await broker.execute_order(order)

    async def process_signal(
        self,
        signal: PredictionSignal,
        signal_source_override: Optional[str] = None,
        risk_config: Optional[dict] = None,
        account_scope_override: Optional[str] = None,
    ) -> Optional[dict]:
        if signal.signal == "HOLD":
            return None

        signal_source = signal_source_override or signal.strategy
        cfg = risk_config or {}
        account_scope = normalize_account_scope(
            account_scope_override
            or self._primary_account_scope_from_config(cfg)
        )
        name, price = await self._resolve_name_and_price(
            signal.ticker, signal.target_price
        )
        if price <= 0:
            logger.warning(
                "가격 정보 없음으로 주문 스킵: %s", signal.ticker
            )
            return None

        position = await get_position(
            signal.ticker, account_scope=account_scope
        )
        if signal.signal == "BUY":
            order_qty = 1
            max_position_pct = int(cfg.get("max_position_pct", 20))
            is_paper = account_scope == "paper"
            paper_seed_capital_raw = cfg.get("paper_seed_capital")
            if is_paper and paper_seed_capital_raw is None:
                account = await get_trading_account(account_scope)
                paper_seed_capital = (
                    int(
                        account.get("seed_capital")
                        or PAPER_TRADING_INITIAL_CAPITAL
                    )
                    if account
                    else PAPER_TRADING_INITIAL_CAPITAL
                )
            else:
                paper_seed_capital = int(
                    paper_seed_capital_raw
                    or PAPER_TRADING_INITIAL_CAPITAL
                )
            total_value = await portfolio_total_value(
                account_scope=account_scope
            )
            current_value = (
                int(position["quantity"])
                * int(position["current_price"])
                if position
                else 0
            )
            next_value = current_value + (order_qty * price)
            if is_paper:
                denominator = max(
                    total_value, paper_seed_capital, 1
                )
            else:
                denominator = max(
                    total_value + (order_qty * price), 1
                )
            next_weight_pct = (next_value / denominator) * 100
            if next_weight_pct > max_position_pct:
                logger.warning(
                    "BUY 스킵: max_position_pct 초과 "
                    "(ticker=%s, next=%.2f%%, limit=%s%%)",
                    signal.ticker,
                    next_weight_pct,
                    max_position_pct,
                )
                return None

            order = PaperOrderRequest(
                ticker=signal.ticker,
                name=name,
                signal="BUY",
                quantity=order_qty,
                price=price,
                signal_source=signal_source,
                agent_id=self.agent_id,
                account_scope=account_scope,
                trigger_source=signal.trigger_source,
                trigger_snapshot=signal.trigger_snapshot,
            )
            broker = self._broker_for_scope(
                account_scope,
                self.paper_broker,
                self.real_broker,
                self.virtual_broker,
            )
            execution = await self._execute_via_broker(
                broker, order
            )
            if execution.status == "REJECTED":
                logger.warning(
                    "%s 주문 거절: %s (%s)",
                    account_scope,
                    signal.ticker,
                    execution.rejection_reason,
                )
                return None
            return {
                "ticker": order.ticker,
                "side": order.signal,
                "quantity": order.quantity,
                "price": order.price,
                "account_scope": account_scope,
            }

        # SELL
        if not position or int(position["quantity"]) <= 0:
            return None

        sell_qty = int(position["quantity"])

        order = PaperOrderRequest(
            ticker=signal.ticker,
            name=name,
            signal="SELL",
            quantity=sell_qty,
            price=price,
            signal_source=signal_source,
            agent_id=self.agent_id,
            account_scope=account_scope,
            trigger_source=signal.trigger_source,
            trigger_snapshot=signal.trigger_snapshot,
        )
        broker = self._broker_for_scope(
            account_scope,
            self.paper_broker,
            self.real_broker,
            self.virtual_broker,
        )
        execution = await self._execute_via_broker(broker, order)
        if execution.status == "REJECTED":
            logger.warning(
                "%s 주문 거절: %s (%s)",
                account_scope,
                signal.ticker,
                execution.rejection_reason,
            )
            return None
        return {
            "ticker": order.ticker,
            "side": order.signal,
            "quantity": order.quantity,
            "price": order.price,
            "account_scope": account_scope,
        }

    async def _check_rule_based_exits(
        self,
        tickers: list[str],
        cfg: dict,
        account_scope: str,
    ) -> list[PredictionSignal]:
        """보유 포지션 중 익절/손절 기준에 해당하는 종목을 SELL 시그널로 반환합니다.

        Phase A Layer 1 (개별 -7% 하드 손절) + take profit 통합.
        소비 파라미터 (portfolio_config):
            - individual_stop_loss_pct (default 7, 양수 값 → -7% 임계)
            - take_profit_pct (default 5)

        Exit signal 에 trigger_source ('hard_stop_L1' | 'take_profit') 과
        trigger_snapshot 을 attach — broker_orders 감사 컬럼으로 흐름.
        (docs/plans/SELL_STRATEGY_PHASES.md §3-1 · §3-3)

        NOTE(§8-7): 현재 avg_price (portfolio_positions.avg_price) 사용.
        원칙 4 는 broker_orders.avg_fill_price 요구. 별도 세션에서 통일 예정.
        """
        from src.db.queries import get_positions_for_scope

        take_profit_pct = int(cfg.get("take_profit_pct", 5))
        individual_stop_loss_pct = int(cfg.get("individual_stop_loss_pct", 7))
        stop_loss_threshold = -individual_stop_loss_pct
        exit_signals: list[PredictionSignal] = []

        positions = await get_positions_for_scope(account_scope)
        for pos in positions:
            ticker = str(pos["ticker"])
            qty = int(pos.get("quantity", 0))
            if qty <= 0:
                continue

            avg_price = float(pos.get("avg_price", 0))
            current_price = float(pos.get("current_price", 0))
            if avg_price <= 0 or current_price <= 0:
                continue

            pnl_pct = (current_price - avg_price) / avg_price * 100.0

            reason: str | None = None
            trigger_source: str | None = None
            if pnl_pct >= take_profit_pct:
                reason = f"규칙 익절 ({pnl_pct:+.2f}% >= +{take_profit_pct}%)"
                trigger_source = "take_profit"
            elif pnl_pct <= stop_loss_threshold:
                reason = f"규칙 손절 ({pnl_pct:+.2f}% <= {stop_loss_threshold}%)"
                trigger_source = "hard_stop_L1"

            if reason:
                logger.info("규칙 기반 매도 트리거: %s %s", ticker, reason)
                snapshot = {
                    "layer": 1 if trigger_source == "hard_stop_L1" else None,
                    "avg_price": int(avg_price),
                    "current_price": int(current_price),
                    "pnl_pct": round(pnl_pct, 3),
                    "stop_line_pct": stop_loss_threshold
                    if trigger_source == "hard_stop_L1"
                    else None,
                    "take_profit_line_pct": take_profit_pct
                    if trigger_source == "take_profit"
                    else None,
                    "account_scope": account_scope,
                    "triggered_at": datetime.utcnow().isoformat(),
                }
                exit_signals.append(
                    PredictionSignal(
                        agent_id="rule_based_exit",
                        llm_model="rule",
                        strategy="EXIT",
                        ticker=ticker,
                        signal="SELL",
                        confidence=1.0,
                        reasoning_summary=reason,
                        trading_date=datetime.utcnow().date(),
                        trigger_source=trigger_source,
                        trigger_snapshot=snapshot,
                    )
                )

        return exit_signals

    async def _check_portfolio_drawdown(
        self,
        cfg: dict,
        account_scope: str,
    ) -> list[PredictionSignal]:
        """포트폴리오 drawdown 이 임계 초과 시 최약체 2 종목 SELL 시그널을 반환.

        Phase A Layer 2 (docs/plans/SELL_STRATEGY_PHASES.md §3-1).

        Baseline: 지난 5~10 일 스냅샷 중 가장 이른 total_equity 근사값
        (§8-2 정확한 "전주 종가" 스냅샷 로직은 open question).
        소비 파라미터: portfolio_drawdown_limit_pct (default 8)
        최약체 정의: unrealized pnl (%) 하위 (§8-2 default).
        """
        from src.db.queries import get_positions_for_scope
        from src.utils.db_client import fetchrow

        dd_limit = int(cfg.get("portfolio_drawdown_limit_pct", 8))

        curr = await fetchrow(
            """
            SELECT total_equity
            FROM account_snapshots
            WHERE account_scope = $1
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            account_scope,
        )
        if curr is None or int(curr["total_equity"]) <= 0:
            return []
        current_equity = int(curr["total_equity"])

        baseline_row = await fetchrow(
            """
            SELECT total_equity
            FROM account_snapshots
            WHERE account_scope = $1
              AND snapshot_at <= NOW() - INTERVAL '5 days'
              AND snapshot_at >= NOW() - INTERVAL '10 days'
            ORDER BY snapshot_at ASC
            LIMIT 1
            """,
            account_scope,
        )
        if baseline_row is None or int(baseline_row["total_equity"]) <= 0:
            return []
        baseline_equity = int(baseline_row["total_equity"])

        dd_pct = (current_equity - baseline_equity) / baseline_equity * 100.0
        if dd_pct > -dd_limit:
            return []

        positions = await get_positions_for_scope(account_scope)
        candidates: list[tuple[float, dict]] = []
        for pos in positions:
            qty = int(pos.get("quantity", 0))
            if qty <= 0:
                continue
            avg_price = float(pos.get("avg_price", 0))
            current_price = float(pos.get("current_price", 0))
            if avg_price <= 0 or current_price <= 0:
                continue
            pnl_pct = (current_price - avg_price) / avg_price * 100.0
            candidates.append((pnl_pct, pos))
        if not candidates:
            return []
        candidates.sort(key=lambda x: x[0])
        weakest_two = candidates[:2]

        now_iso = datetime.utcnow().isoformat()
        exit_signals: list[PredictionSignal] = []
        for pnl_pct, pos in weakest_two:
            ticker = str(pos["ticker"])
            avg_price = float(pos.get("avg_price", 0))
            current_price = float(pos.get("current_price", 0))
            reason = (
                f"L2 포트 dd {dd_pct:+.2f}% <= -{dd_limit}%, "
                f"최약체 매도: {ticker} pnl={pnl_pct:+.2f}%"
            )
            logger.info("Layer 2 매도 트리거: %s", reason)
            exit_signals.append(
                PredictionSignal(
                    agent_id="rule_based_exit",
                    llm_model="rule",
                    strategy="EXIT",
                    ticker=ticker,
                    signal="SELL",
                    confidence=1.0,
                    reasoning_summary=reason,
                    trading_date=datetime.utcnow().date(),
                    trigger_source="hard_stop_L2",
                    trigger_snapshot={
                        "layer": 2,
                        "avg_price": int(avg_price),
                        "current_price": int(current_price),
                        "portfolio_dd_pct": round(dd_pct, 3),
                        "portfolio_dd_limit_pct": dd_limit,
                        "current_equity": current_equity,
                        "baseline_equity": baseline_equity,
                        "position_pnl_pct": round(pnl_pct, 3),
                        "account_scope": account_scope,
                        "triggered_at": now_iso,
                    },
                )
            )
        return exit_signals

    async def _hard_stop_scan(self, cfg: dict, account_scope: str) -> list[dict]:
        """Hard stop 잡 entry — L3 → L1 → L2 순 판정 후 매도 발주.

        (docs/plans/SELL_STRATEGY_PHASES.md §3-2)

        Layer 우선순위: L3 lockout → L1 개별 → L2 포트 dd.
        L1 이 이미 매도한 종목은 L2 중복 발주 방지.

        이중 발주 방지:
            - 잡 레벨 lock: unified_scheduler 자동 (scheduler:lock:hard_stop_check)
            - 종목별 lock: hard_stop:{ticker} TTL 25s
            - 주문 중복: broker_orders.client_order_id UNIQUE

        Dry-run 시 (is_hard_stop_dry_run() = True) broker.execute_order 스킵,
        로그와 return 만.
        """
        from src.schedulers.distributed_lock import DistributedLock
        from src.services.trading_mode import is_hard_stop_dry_run

        blocked, pnl_pct = await self._is_daily_loss_blocked(account_scope, cfg)
        if blocked:
            daily_limit = int(cfg.get("daily_loss_limit_pct", 3))
            await self._publish_circuit_breaker(account_scope, pnl_pct, daily_limit)
            logger.info(
                "Hard stop L3 lockout: scope=%s, pnl=%.2f%%, limit=-%d%%",
                account_scope,
                pnl_pct,
                daily_limit,
            )
            return []

        l1_signals = await self._check_rule_based_exits([], cfg, account_scope)
        l2_signals = await self._check_portfolio_drawdown(cfg, account_scope)

        l1_tickers = {s.ticker for s in l1_signals}
        l2_signals = [s for s in l2_signals if s.ticker not in l1_tickers]

        all_signals = l1_signals + l2_signals
        if not all_signals:
            return []

        dry_run = await is_hard_stop_dry_run()
        if dry_run:
            logger.info(
                "Hard stop DRY-RUN — 실 발주 스킵: scope=%s, L1=%d, L2=%d, tickers=%s",
                account_scope,
                len(l1_signals),
                len(l2_signals),
                [s.ticker for s in all_signals],
            )
            return [
                {
                    "ticker": s.ticker,
                    "trigger_source": s.trigger_source,
                    "dry_run": True,
                }
                for s in all_signals
            ]

        redis = await get_redis()
        dispatched: list[dict] = []
        for signal in all_signals:
            async with DistributedLock(
                redis,
                f"hard_stop:{signal.ticker}",
                ttl=25,
                raise_on_fail=False,
            ) as lock:
                if not lock.acquired:
                    logger.debug("Hard stop 종목 lock 스킵: %s", signal.ticker)
                    continue
                order = await self.process_signal(
                    signal,
                    signal_source_override="EXIT",
                    account_scope_override=account_scope,
                )
                if order is not None:
                    dispatched.append(order)
        return dispatched

    async def process_predictions(
        self,
        predictions: list[PredictionSignal],
        signal_source_override: Optional[str] = None,
        account_scope_override: Optional[str] = None,
    ) -> list[dict]:
        cfg = await get_portfolio_config()
        if account_scope_override:
            enabled_scopes = [
                normalize_account_scope(account_scope_override)
            ]
        else:
            enabled_scopes = self._enabled_account_scopes_from_config(cfg)
        daily_loss_limit_pct = int(cfg.get("daily_loss_limit_pct", 3))

        if not enabled_scopes:
            message = "활성화된 주문 계좌가 없어 주문을 건너뜁니다."
            await set_heartbeat(self.agent_id)
            await insert_heartbeat(
                AgentHeartbeatRecord(
                    agent_id=self.agent_id,
                    status="degraded",
                    last_action=message,
                    metrics={"enabled_scopes": 0},
                )
            )
            return []

        market_status = await market_session_status()
        if market_status != "open":
            orders: list[dict] = []
            blocked_scopes: list[dict[str, object]] = []
            last_action = f"장 마감/휴장으로 주문 생략 ({market_status})"
            await self._publish_orders_event(
                orders=orders,
                enabled_scopes=enabled_scopes,
                blocked_scopes=blocked_scopes,
                market_status=market_status,
                skip_reason="market_closed",
            )
            await self._record_processing_heartbeat(
                status="healthy",
                last_action=last_action,
                orders_executed=0,
                enabled_scopes=enabled_scopes,
                blocked_scopes=blocked_scopes,
                market_status=market_status,
                skip_reason="market_closed",
            )
            logger.info("PortfolioManagerAgent 장외 주문 스킵: market_status=%s", market_status)
            return []

        orders: list[dict] = []
        blocked_scopes: list[dict[str, object]] = []
        for account_scope in enabled_scopes:
            blocked, pnl_pct = await self._is_daily_loss_blocked(account_scope, cfg)
            if blocked:
                await self._publish_circuit_breaker(account_scope, pnl_pct, daily_loss_limit_pct)
                blocked_scopes.append({"account_scope": account_scope, "pnl_pct": round(pnl_pct, 3)})
                continue

            # 규칙 기반 익절/손절 시그널 추가
            tickers = [s.ticker for s in predictions]
            exit_signals = await self._check_rule_based_exits(tickers, cfg, account_scope)
            combined = list(exit_signals) + list(predictions)

            for signal in combined:
                order = await self.process_signal(
                    signal,
                    signal_source_override=signal_source_override or signal.strategy,
                    risk_config=cfg,
                    account_scope_override=account_scope,
                )
                if order:
                    orders.append(order)

        hb_status = "healthy" if len(blocked_scopes) < len(enabled_scopes) else "degraded"

        await self._publish_orders_event(
            orders=orders,
            enabled_scopes=enabled_scopes,
            blocked_scopes=blocked_scopes,
            market_status=market_status,
        )

        await self._record_processing_heartbeat(
            status=hb_status,
            last_action=f"주문 처리 완료 ({len(orders)}건)",
            orders_executed=len(orders),
            enabled_scopes=enabled_scopes,
            blocked_scopes=blocked_scopes,
            market_status=market_status,
        )
        logger.info("PortfolioManagerAgent 주문 처리 완료: %d건", len(orders))
        return orders


def _signal_from_json(raw: dict) -> PredictionSignal:
    return PredictionSignal(
        agent_id=raw.get("agent_id", "predictor_1"),
        llm_model=raw.get("llm_model", "manual"),
        strategy=raw.get("strategy", "A"),
        ticker=raw["ticker"],
        signal=raw["signal"],
        confidence=raw.get("confidence"),
        target_price=raw.get("target_price"),
        stop_loss=raw.get("stop_loss"),
        reasoning_summary=raw.get("reasoning_summary"),
        trading_date=datetime.utcnow().date(),
    )


async def _main_async(args: argparse.Namespace) -> None:
    agent = PortfolioManagerAgent()

    if args.signals_json:
        data = json.loads(args.signals_json)
        predictions = [_signal_from_json(item) for item in data]
    else:
        predictions = [
            PredictionSignal(
                agent_id="predictor_1",
                llm_model="manual",
                strategy="A",
                ticker=t.strip(),
                signal="HOLD",
                confidence=0.5,
                trading_date=datetime.utcnow().date(),
            )
            for t in args.tickers.split(",")
            if t.strip()
        ]
    await agent.process_predictions(predictions)


def main() -> None:
    parser = argparse.ArgumentParser(description="PortfolioManagerAgent MVP")
    parser.add_argument("--tickers", default="005930")
    parser.add_argument("--signals-json", default="", help="예측 시그널 JSON 배열")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
