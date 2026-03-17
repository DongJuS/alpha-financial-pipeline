"""
src/agents/orchestrator.py — OrchestratorAgent with independent portfolio mode

기본 사이클:
Collector -> StrategyRegistry(병렬) -> Blender/Independent -> PortfolioManager -> Notifier

여러 StrategyRunner로부터 PredictionSignal을 수집하고,
N-way 블렌딩을 적용하거나 독립 포트폴리오 모드로 처리하여
최종 신호를 생성하고 PortfolioManagerAgent로 전달합니다.

--independent-portfolio 플래그로 per-strategy PM 인스턴스 지원.
"""
from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.brokers import build_virtual_broker
from src.brokers.virtual_broker import VirtualBroker
from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import (
    insert_heartbeat,
)
from src.agents.strategy_runner import StrategyRegistry, StrategyRunner
from src.services.datalake import store_blend_results, store_orders
from src.utils.aggregate_risk import AggregateRiskMonitor
from src.utils.config import get_settings
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import set_heartbeat
from src.utils.strategy_promotion import StrategyPromoter

if TYPE_CHECKING:
    from src.agents.portfolio_manager import PortfolioManagerAgent
    from src.agents.notifier import NotifierAgent

setup_logging()
logger = get_logger(__name__)

# N-way 블렌딩 가중치
# A: 토너먼트 (30%), B: 토론 (30%), S: 검색 (20%), RL: 강화학습 (20%)
DEFAULT_BLEND_WEIGHTS: dict[str, float] = {
    "A": 0.30,
    "B": 0.30,
    "S": 0.20,
    "RL": 0.20,
}


class OrchestratorAgent:
    """
    여러 StrategyRunner로부터 예측 신호를 수집하고,
    N-way 블렌딩 또는 독립 포트폴리오 모드를 적용하여
    최종 매매 신호를 생성합니다.

    기본 사이클:
    1. 모든 러너 동시 실행
    2. --independent-portfolio 플래그에 따라:
       - False (기본): N-way 블렌딩 모드
       - True: 전략별 독립 PM 인스턴스로 라우팅 + 집계 위험 모니터링
    3. 최종 주문 + 위험 모니터링 + 승격 준비 확인
    4. PortfolioManagerAgent로 전달
    """

    def __init__(
        self,
        agent_id: str = "orchestrator_agent",
        strategy_blend_weights: dict[str, float] | None = None,
        independent_portfolio: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.strategy_blend_weights = strategy_blend_weights or DEFAULT_BLEND_WEIGHTS
        self.registry = StrategyRegistry()
        self.independent_portfolio = independent_portfolio

        # 독립 포트폴리오 모드용 per-strategy PM 인스턴스
        self._strategy_portfolios: dict[str, PortfolioManagerAgent] = {}
        self._strategy_virtual_brokers: dict[str, VirtualBroker] = {}

    # ── Strategy Registration ──────────────────────────────────────────────

    def register_strategy(self, runner: StrategyRunner) -> None:
        """전략 러너를 등록합니다."""
        self.registry.register(runner)

    def register_strategies(self, *runners: StrategyRunner) -> None:
        """여러 전략 러너를 한 번에 등록합니다."""
        for runner in runners:
            self.registry.register(runner)

    # ── Per-strategy Portfolio Management ──────────────────────────────────

    def _get_portfolio_for_strategy(
        self,
        strategy_id: str,
    ) -> PortfolioManagerAgent:
        """전략별 PM 인스턴스를 지연 생성합니다."""
        if strategy_id not in self._strategy_portfolios:
            from src.agents.portfolio_manager import PortfolioManagerAgent

            pm = PortfolioManagerAgent(
                agent_id=f"portfolio_manager_{strategy_id}"
            )
            self._strategy_portfolios[strategy_id] = pm
            logger.info(
                "Created per-strategy PM for %s: %s",
                strategy_id,
                pm.agent_id,
            )
        return self._strategy_portfolios[strategy_id]

    def _get_virtual_broker_for_strategy(
        self,
        strategy_id: str,
        initial_capital: int | None = None,
    ) -> VirtualBroker:
        """전략별 VirtualBroker 인스턴스를 지연 생성합니다."""
        if strategy_id not in self._strategy_virtual_brokers:
            broker = build_virtual_broker(
                strategy_id=strategy_id,
                initial_capital=initial_capital,
            )
            self._strategy_virtual_brokers[strategy_id] = broker
            logger.info(
                "Created virtual broker for %s: initial_capital=%s",
                strategy_id,
                initial_capital,
            )
        return self._strategy_virtual_brokers[strategy_id]

    # ── Core Cycle ─────────────────────────────────────────────────────────

    async def run_strategies(
        self,
        tickers: list[str],
    ) -> dict[str, list[PredictionSignal]]:
        """등록된 모든 러너를 병렬 실행합니다 (StrategyRegistry.run_all 위임)."""
        if self.registry.runner_count == 0:
            logger.warning("전략 러너가 등록되지 않았습니다. registry가 비어 있습니다.")
            return {}
        return await self.registry.run_all(tickers)

    async def run_cycle(self, tickers: list[str]) -> dict:
        """한 사이클 실행: 수집 -> 전략 실행 -> 블렌딩/독립 처리 -> 주문 실행.

        Args:
            tickers: 분석할 티커 목록

        Returns:
            사이클 실행 결과 dict
        """
        started = datetime.now(timezone.utc)
        try:
            # ── 전략 병렬 실행 ──
            all_predictions = await self.run_strategies(tickers)

            if not all_predictions:
                logger.warning("No predictions returned from strategies")
                return {
                    "collected": 0,
                    "predicted": 0,
                    "orders": 0,
                    "mode": "no_predictions",
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "active_strategies": [],
                }

            collected_count = sum(
                len(preds) for preds in all_predictions.values()
            )
            predicted_count = collected_count

            all_orders: list = []
            promotion_alerts: list[str] = []
            risk_violations: list = []

            if self.independent_portfolio:
                # ── 독립 포트폴리오 모드 ──
                logger.info(
                    "Running in independent portfolio mode with %d strategies",
                    len(all_predictions),
                )

                risk_monitor = AggregateRiskMonitor()
                risk_summary = await risk_monitor.get_risk_summary()

                if risk_summary.warnings:
                    risk_violations = risk_summary.warnings
                    logger.warning(
                        "Aggregate risk violations detected: %s",
                        risk_violations,
                    )

                for strategy_name, predictions in all_predictions.items():
                    logger.info(
                        "Processing %d predictions for strategy %s",
                        len(predictions),
                        strategy_name,
                    )

                    if not predictions:
                        continue

                    portfolio_mgr = self._get_portfolio_for_strategy(
                        strategy_name
                    )
                    signal_source = (
                        strategy_name
                        if strategy_name in ("A", "B", "RL", "S", "L")
                        else "VIRTUAL"
                    )
                    orders = await portfolio_mgr.process_predictions(
                        predictions,
                        signal_source_override=signal_source,
                    )
                    all_orders.extend(orders)
                    logger.info(
                        "Strategy %s generated %d orders",
                        strategy_name,
                        len(orders),
                    )

                # 승격 준비 확인
                promoter = StrategyPromoter()
                notifier = self._create_notifier()
                for strategy_name in all_predictions.keys():
                    try:
                        readiness = (
                            await promoter.evaluate_promotion_readiness(
                                strategy_name,
                                from_mode="virtual",
                                to_mode="paper",
                            )
                        )
                        if readiness and readiness.ready:
                            alert_msg = (
                                f"전략 {strategy_name} 승격 준비 완료: "
                                f"{readiness.from_mode} → "
                                f"{readiness.to_mode}"
                            )
                            promotion_alerts.append(alert_msg)
                            await notifier.send_promotion_alert(
                                strategy_id=strategy_name,
                                from_mode=readiness.from_mode,
                                to_mode=readiness.to_mode,
                                metrics=getattr(
                                    readiness, "metrics", None
                                ),
                            )
                            logger.info(
                                "Promotion alert sent for %s",
                                strategy_name,
                            )
                    except Exception as e:
                        logger.error(
                            "Promotion check failed for %s: %s",
                            strategy_name,
                            e,
                            exc_info=True,
                        )

                try:
                    await risk_monitor.record_risk_snapshot()
                except Exception as e:
                    logger.error("Risk snapshot recording failed: %s", e, exc_info=True)

                mode_name = (
                    f"independent_portfolio({len(all_predictions)} strategies)"
                )
                blend_meta = None

            else:
                # ── 기본 블렌딩 모드 ──
                logger.info(
                    "Running in blend mode with %d strategies",
                    len(all_predictions),
                )
                blended = self._blend_nway_predictions(all_predictions)
                if not blended and collected_count > 0:
                    logger.warning(
                        "Strategies produced %d predictions but blending yielded 0 signals — "
                        "check ticker coverage across strategies.",
                        collected_count,
                    )
                elif not blended:
                    logger.error(
                        "All %d strategies ran but produced 0 predictions total — "
                        "LLM providers may be misconfigured. Check /models/debug-providers.",
                        len(all_predictions),
                    )
                all_orders = await self._execute_blended_signals(blended)
                mode_name = "blend_mode"
                blend_meta = {
                    "strategies": list(all_predictions.keys()),
                    "weights": {
                        k: round(self.strategy_blend_weights.get(k, 0.0), 4)
                        for k in all_predictions.keys()
                    },
                    "blended_signals": len(blended),
                }

            # S3 Data Lake에 블렌딩 결과 + 주문 기록 저장
            try:
                if blended:
                    blend_records = [
                        {
                            "ticker": s.ticker,
                            "blended_signal": s.signal,
                            "blended_confidence": s.confidence,
                            "strategy_weights": json.dumps(
                                self.strategy_blend_weights, ensure_ascii=False
                            ),
                            "created_at": datetime.now(timezone.utc),
                        }
                        for s in blended
                    ]
                    await store_blend_results(blend_records)
                if all_orders:
                    order_records = [
                        {
                            "ticker": o.get("ticker", ""),
                            "name": o.get("name", ""),
                            "signal": o.get("signal", ""),
                            "quantity": o.get("quantity", 0),
                            "price": o.get("price", 0),
                            "signal_source": o.get("signal_source", "BLEND"),
                            "agent_id": o.get("agent_id", self.agent_id),
                            "account_scope": o.get("account_scope", "paper"),
                            "strategy_id": o.get("strategy_id", ""),
                            "created_at": datetime.now(timezone.utc),
                        }
                        for o in all_orders
                        if isinstance(o, dict)
                    ]
                    await store_orders(order_records)
            except Exception as e:
                logger.warning("S3 블렌딩/주문 저장 스킵: %s", e)

            # 기록
            await set_heartbeat(self.agent_id)
            result = {
                "collected": collected_count,
                "predicted": predicted_count,
                "orders": len(all_orders),
                "mode": mode_name,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "active_strategies": list(all_predictions.keys()),
                "blend_meta": blend_meta if not self.independent_portfolio else None,
                "risk_violations": risk_violations or None,
                "promotion_alerts": promotion_alerts or None,
            }

            await insert_heartbeat(
                AgentHeartbeatRecord(
                    agent_id=self.agent_id,
                    status="healthy",
                    last_action=(
                        f"사이클 완료 (예측 {result['predicted']} / "
                        f"주문 {result['orders']})"
                    ),
                    metrics=result,
                )
            )
            logger.info("Orchestrator cycle 완료: %s", result)
            return result

        except Exception as e:
            err_msg = f"Orchestrator cycle 실패: {e}"
            await insert_heartbeat(
                AgentHeartbeatRecord(
                    agent_id=self.agent_id,
                    status="error",
                    last_action=err_msg,
                    metrics={"error": str(e)},
                )
            )
            logger.exception(err_msg)
            raise

    # ── N-way Blending ─────────────────────────────────────────────────────

    def _blend_nway_predictions(
        self,
        all_predictions: dict[str, list[PredictionSignal]],
    ) -> list[PredictionSignal]:
        """N-way 가중 블렌딩으로 티커별 최종 신호를 생성합니다.

        각 전략의 confidence에 가중치를 곱한 뒤, 티커별로 BUY/SELL/HOLD 스코어를
        합산하여 가장 높은 스코어의 signal을 최종 신호로 채택합니다.
        """
        # 티커별로 (signal, weighted_confidence) 누적
        ticker_scores: dict[str, dict[str, float]] = {}
        ticker_best_signal: dict[str, PredictionSignal] = {}

        for strategy_name, predictions in all_predictions.items():
            weight = self.strategy_blend_weights.get(strategy_name, 0.0)
            if weight <= 0.0:
                continue

            for pred in predictions:
                if pred.ticker not in ticker_scores:
                    ticker_scores[pred.ticker] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
                    ticker_best_signal[pred.ticker] = pred

                signal_key = pred.signal.upper()
                if signal_key in ticker_scores[pred.ticker]:
                    ticker_scores[pred.ticker][signal_key] += pred.confidence * weight

        blended: list[PredictionSignal] = []
        for ticker, scores in ticker_scores.items():
            # 가장 높은 스코어의 시그널 선택
            best_signal = max(scores, key=scores.get)  # type: ignore[arg-type]
            total_weight = sum(scores.values())
            blended_confidence = scores[best_signal] / total_weight if total_weight > 0 else 0.5

            # 기존 PredictionSignal을 기반으로 블렌딩된 신호 생성
            base = ticker_best_signal[ticker]
            blended.append(
                PredictionSignal(
                    agent_id="orchestrator_blend",
                    llm_model="blend",
                    strategy="BLEND",
                    ticker=ticker,
                    signal=best_signal,
                    confidence=round(min(1.0, blended_confidence), 4),
                    target_price=base.target_price,
                    stop_loss=base.stop_loss,
                    reasoning_summary=(
                        f"N-way blend: {', '.join(f'{k}={v:.3f}' for k, v in scores.items())}"
                    ),
                    trading_date=base.trading_date,
                )
            )
            logger.debug(
                "Blended %s: %s (conf=%.4f) scores=%s",
                ticker,
                best_signal,
                blended_confidence,
                scores,
            )

        if blended:
            logger.info(
                "N-way blending produced %d signals from %d strategies",
                len(blended),
                len(all_predictions),
            )
        return blended

    async def _execute_blended_signals(
        self,
        blended_signals: list[PredictionSignal],
    ) -> list:
        """블렌딩된 신호를 포트폴리오 매니저로 전달하여 주문을 실행합니다."""
        if not blended_signals:
            return []

        from src.agents.portfolio_manager import PortfolioManagerAgent

        pm = PortfolioManagerAgent(agent_id="portfolio_manager_agent")
        try:
            orders = await pm.process_predictions(
                blended_signals,
                signal_source_override="BLEND",
            )
            logger.info("Blend mode: %d orders executed", len(orders))
            return orders
        except Exception as e:
            logger.error("Blend mode order execution failed: %s", e)
            return []

    # ── Notifier ───────────────────────────────────────────────────────────

    def _create_notifier(self) -> NotifierAgent:
        """NotifierAgent 인스턴스를 생성합니다."""
        from src.agents.notifier import NotifierAgent

        return NotifierAgent(agent_id="notifier_agent")


async def _main_async(args: argparse.Namespace) -> None:
    """CLI 엔트리포인트."""
    orchestrator = OrchestratorAgent(
        independent_portfolio=args.independent_portfolio,
    )
    tickers = (
        [t.strip() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else ["005930", "000660"]  # 기본값: 삼성전자, SK하이닉스
    )

    result = await orchestrator.run_cycle(tickers)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OrchestratorAgent with independent portfolio mode"
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="쉼표 구분 티커 목록 (기본: 005930,000660)",
    )
    parser.add_argument(
        "--independent-portfolio",
        action="store_true",
        help="독립 포트폴리오 모드 활성화 (per-strategy PM + 집계 위험 모니터링)",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
