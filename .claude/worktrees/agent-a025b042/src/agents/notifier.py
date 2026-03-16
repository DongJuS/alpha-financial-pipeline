"""
src/agents/notifier.py — NotifierAgent MVP (Telegram 기본 알림)
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.db.models import AgentHeartbeatRecord, NotificationRecord
from src.db.queries import (
    fetch_trade_rows,
    fetch_trade_rows_for_date,
    insert_heartbeat,
    insert_notification,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger, setup_logging
from src.utils.performance import compute_trade_performance
from src.utils.redis_client import TOPIC_ALERTS, set_heartbeat, get_redis
from src.utils.secret_validation import is_placeholder_secret

setup_logging()
logger = get_logger(__name__)


class NotifierAgent:
    def __init__(self, agent_id: str = "notifier_agent") -> None:
        self.agent_id = agent_id
        self.settings = get_settings()

    async def send(self, event_type: str, message: str) -> bool:
        success = False
        error_msg = None
        delivery_mode = "telegram"

        token = self.settings.telegram_bot_token
        chat_id = self.settings.telegram_chat_id
        if (
            is_placeholder_secret(token)
            or is_placeholder_secret(chat_id)
        ):
            # Telegram 비활성화 운영에서는 DB 기록만으로도 정상 처리로 간주
            success = True
            delivery_mode = "db_only"
            error_msg = "telegram_placeholder_or_not_configured_db_only"
            logger.info("Telegram placeholder/미설정: DB 기록 전용 모드로 처리합니다.")
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        url,
                        json={
                            "chat_id": chat_id,
                            "text": message,
                        },
                    )
                    resp.raise_for_status()
                    success = True
            except Exception as e:
                error_msg = str(e)

        await insert_notification(
            NotificationRecord(
                event_type=event_type,
                message=message,
                success=success,
                error_msg=error_msg,
            )
        )

        await set_heartbeat(self.agent_id)
        await insert_heartbeat(
            AgentHeartbeatRecord(
                agent_id=self.agent_id,
                status="healthy" if success else "degraded",
                last_action=f"알림 처리: {event_type}",
                metrics={"success": success, "error": error_msg, "delivery_mode": delivery_mode},
            )
        )
        return success

    async def send_cycle_summary(self, collected: int, predicted: int, orders: int) -> bool:
        text = (
            "📊 Alpha 사이클 완료\n"
            f"- 수집: {collected}건\n"
            f"- 예측: {predicted}건\n"
            f"- 주문: {orders}건\n"
            f"- 시각(UTC): {datetime.utcnow().isoformat()}Z"
        )
        return await self.send(event_type="cycle_summary", message=text)

    async def send_promotion_alert(
        self,
        strategy_id: str,
        from_mode: str,
        to_mode: str,
        metrics: dict | None = None,
    ) -> bool:
        """전략 승격 준비 완료 알림을 발송합니다.

        Args:
            strategy_id: 전략 ID (예: 'A', 'B', 'RL', 'S')
            from_mode: 현재 모드 (예: 'virtual', 'paper')
            to_mode: 승격 대상 모드 (예: 'paper', 'real')
            metrics: 선택적 성능 지표 dict

        Returns:
            bool: 발송 성공 여부
        """
        metrics_text = ""
        if metrics:
            metrics_text = "\n".join(f"  - {k}: {v}" for k, v in metrics.items())

        text = (
            f"🎯 전략 승격 준비 완료\n"
            f"- 전략: {strategy_id}\n"
            f"- 전환: {from_mode} → {to_mode}\n"
            f"- 시각(UTC): {datetime.utcnow().isoformat()}Z"
        )
        if metrics_text:
            text += f"\n- 지표:\n{metrics_text}"

        return await self.send(event_type="promotion_ready", message=text)

    async def send_paper_daily_report(
        self,
        report_date: date | None = None,
        reconciliation: dict | None = None,
    ) -> bool:
        target_date = report_date or date.today()
        rows_today = await fetch_trade_rows_for_date(target_date, is_paper=True)
        rows_30d = await fetch_trade_rows(days=30, is_paper=True)
        metrics_today = compute_trade_performance(rows_today)
        metrics_30d = compute_trade_performance(rows_30d)

        text = (
            f"🧾 Alpha 페이퍼 일일 리포트 ({target_date.isoformat()})\n"
            f"- 오늘 거래: {metrics_today['total_trades']}건 (SELL {metrics_today['sell_count']}건)\n"
            f"- 오늘 실현손익: {metrics_today['realized_pnl']:,}원\n"
            f"- 오늘 수익률: {metrics_today['return_pct']:.2f}%\n"
            f"- 30일 실현손익: {metrics_30d['realized_pnl']:,}원\n"
            f"- 30일 수익률: {metrics_30d['return_pct']:.2f}%\n"
            f"- 30일 승률: {metrics_30d['win_rate']:.2f}\n"
            f"- 30일 MDD: {metrics_30d['max_drawdown_pct']:.2f}%\n"
            f"- 30일 Sharpe: {metrics_30d['sharpe_ratio'] if metrics_30d['sharpe_ratio'] is not None else '-'}"
        )
        if reconciliation:
            text += (
                f"\n- 동기화 결과: {reconciliation.get('summary', '-')}"
                f"\n- 신규 KIS 체결 반영: {reconciliation.get('new_trades', 0)}건"
            )
        return await self.send(event_type="paper_daily_report", message=text)

    async def listen_alerts(self) -> None:
        """Redis alerts 채널을 구독해 Telegram으로 릴레이합니다."""
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(TOPIC_ALERTS)
        logger.info("NotifierAgent alerts 리스너 시작: %s", TOPIC_ALERTS)

        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            raw = message.get("data")
            payload = raw if isinstance(raw, str) else str(raw)
            try:
                data = json.loads(payload)
                event_type = data.get("type", "alert")
                text = data.get("message") or json.dumps(data, ensure_ascii=False)
            except Exception:
                event_type = "alert"
                text = payload

            await self.send(event_type=event_type, message=f"🚨 {text}")


async def _main_async(args: argparse.Namespace) -> None:
    agent = NotifierAgent()
    if args.listen:
        await agent.listen_alerts()
    else:
        await agent.send(event_type="manual", message=args.message)


def main() -> None:
    parser = argparse.ArgumentParser(description="NotifierAgent MVP")
    parser.add_argument("--message", default="NotifierAgent 테스트 메시지")
    parser.add_argument("--listen", action="store_true", help="Redis alerts 채널 구독 모드")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
