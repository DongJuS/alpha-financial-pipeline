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

from src.db.models import AgentHeartbeatRecord, PaperOrderRequest, PredictionSignal
from src.db.queries import (
    fetch_recent_ohlcv,
    get_portfolio_config,
    get_position,
    insert_heartbeat,
    insert_trade,
    portfolio_total_value,
    save_position,
    today_trade_totals,
)
from src.utils.account_scope import normalize_account_scope
from src.utils.logging import get_logger, setup_logging
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
    def __init__(self, agent_id: str = "portfolio_manager_agent") -> None:
        self.agent_id = agent_id

    @staticmethod
    def _account_scope_from_config(cfg: dict) -> str:
        return normalize_account_scope("paper" if bool(cfg.get("is_paper_trading", True)) else "real")

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

    async def process_signal(
        self,
        signal: PredictionSignal,
        signal_source_override: Optional[str] = None,
        risk_config: Optional[dict] = None,
    ) -> Optional[dict]:
        if signal.signal == "HOLD":
            return None

        signal_source = signal_source_override or signal.strategy
        cfg = risk_config or {}
        account_scope = self._account_scope_from_config(cfg)
        name, price = await self._resolve_name_and_price(signal.ticker, signal.target_price)
        if price <= 0:
            logger.warning("가격 정보 없음으로 주문 스킵: %s", signal.ticker)
            return None

        position = await get_position(signal.ticker, account_scope=account_scope)
        if signal.signal == "BUY":
            order_qty = 1
            max_position_pct = int(cfg.get("max_position_pct", 20))
            paper_seed_capital = int(cfg.get("paper_seed_capital", 10_000_000))
            is_paper = account_scope == "paper"
            total_value = await portfolio_total_value(account_scope=account_scope)
            current_value = (
                int(position["quantity"]) * int(position["current_price"]) if position else 0
            )
            next_value = current_value + (order_qty * price)
            if is_paper:
                denominator = max(total_value, paper_seed_capital, 1)
            else:
                denominator = max(total_value + (order_qty * price), 1)
            next_weight_pct = (next_value / denominator) * 100
            if next_weight_pct > max_position_pct:
                logger.warning(
                    "BUY 스킵: max_position_pct 초과 (ticker=%s, next=%.2f%%, limit=%s%%)",
                    signal.ticker,
                    next_weight_pct,
                    max_position_pct,
                )
                return None

            prev_qty = int(position["quantity"]) if position else 0
            prev_avg = int(position["avg_price"]) if position else 0
            new_qty = prev_qty + order_qty
            new_avg = int(((prev_qty * prev_avg) + (order_qty * price)) / new_qty)

            await save_position(
                ticker=signal.ticker,
                name=name,
                quantity=new_qty,
                avg_price=new_avg,
                current_price=price,
                is_paper=is_paper,
                account_scope=account_scope,
            )

            order = PaperOrderRequest(
                ticker=signal.ticker,
                name=name,
                signal="BUY",
                quantity=order_qty,
                price=price,
                signal_source=signal_source,
                agent_id=self.agent_id,
                account_scope=account_scope,
            )
            await insert_trade(order)
            return {
                "ticker": order.ticker,
                "side": order.signal,
                "quantity": order.quantity,
                "price": order.price,
            }

        # SELL
        if not position or int(position["quantity"]) <= 0:
            return None

        sell_qty = int(position["quantity"])
        await save_position(
            ticker=signal.ticker,
            name=name,
            quantity=0,
            avg_price=0,
            current_price=price,
            is_paper=account_scope == "paper",
            account_scope=account_scope,
        )

        order = PaperOrderRequest(
            ticker=signal.ticker,
            name=name,
            signal="SELL",
            quantity=sell_qty,
            price=price,
            signal_source=signal_source,
            agent_id=self.agent_id,
            account_scope=account_scope,
        )
        await insert_trade(order)
        return {
            "ticker": order.ticker,
            "side": order.signal,
            "quantity": order.quantity,
            "price": order.price,
        }

    async def process_predictions(
        self,
        predictions: list[PredictionSignal],
        signal_source_override: Optional[str] = None,
    ) -> list[dict]:
        cfg = await get_portfolio_config()
        account_scope = self._account_scope_from_config(cfg)
        totals = await today_trade_totals(account_scope=account_scope)
        buy_total = totals["buy_total"]
        sell_total = totals["sell_total"]
        pnl_pct = ((sell_total - buy_total) / buy_total * 100) if buy_total > 0 else 0.0
        daily_loss_limit_pct = int(cfg.get("daily_loss_limit_pct", 3))

        if buy_total > 0 and pnl_pct <= -daily_loss_limit_pct:
            message = (
                f"일일 손실 한도 도달로 주문 중단 (pnl={pnl_pct:.2f}%, "
                f"limit=-{daily_loss_limit_pct}%)"
            )
            logger.warning(message)
            await publish_message(
                TOPIC_ALERTS,
                json.dumps(
                    {
                        "type": "circuit_breaker",
                        "message": message,
                    },
                    ensure_ascii=False,
                ),
            )
            await set_heartbeat(self.agent_id)
            await insert_heartbeat(
                AgentHeartbeatRecord(
                    agent_id=self.agent_id,
                    status="degraded",
                    last_action=message,
                    metrics={"pnl_pct": round(pnl_pct, 3)},
                )
            )
            return []

        orders: list[dict] = []
        for signal in predictions:
            order = await self.process_signal(
                signal,
                signal_source_override=signal_source_override,
                risk_config=cfg,
            )
            if order:
                orders.append(order)

        await publish_message(
            TOPIC_ORDERS,
            json.dumps(
                {
                    "type": "orders_executed",
                    "agent_id": self.agent_id,
                    "count": len(orders),
                    "orders": orders,
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                },
                ensure_ascii=False,
            ),
        )

        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status="healthy",
                last_action=f"주문 처리 완료 ({len(orders)}건)",
                metrics={"orders_executed": len(orders)},
            )
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
