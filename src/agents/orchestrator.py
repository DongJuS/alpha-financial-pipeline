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
# A: 토너먼트 (33%), B: 토론 (33%), RL: 강화학습 (34%)
DEFAULT_BLEND_WEIGHTS: dict[str, float] = {
    "A": 0.33,
    "B": 0.33,
    "RL": 0.34,
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
                await self._maybe_update_dynamic_weights(list(all_predictions.keys()))
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

                # 블렌딩 메타 정보 (활성 전략 기준 가중치 포함)
                active_strats = {
                    name for name, preds in all_predictions.items() if preds
                }
                effective_weights = self._normalize_active_weights(active_strats)
                excluded_strats = set(all_predictions.keys()) - active_strats
                mode_name = "blend_mode"
                blend_meta = {
                    "strategies": list(all_predictions.keys()),
                    "active_strategies": sorted(active_strats),
                    "excluded_strategies": sorted(excluded_strats),
                    "original_weights": {
                        k: round(self.strategy_blend_weights.get(k, 0.0), 4)
                        for k in all_predictions.keys()
                    },
                    "effective_weights": {
                        k: round(v, 4) for k, v in effective_weights.items()
                    },
                    "blended_signals": len(blended),
                    "fallback": bool(excluded_strats),
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
                                effective_weights if not self.independent_portfolio else self.strategy_blend_weights,
                                ensure_ascii=False,
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

            # KIS PENDING 주문 체결 동기화
            try:
                from src.brokers.kis import KISPaperBroker
                kis_broker = KISPaperBroker()
                if kis_broker.client.is_configured():
                    synced = await kis_broker.sync_pending_orders()
                    if synced:
                        logger.info("KIS 체결 동기화: %d건 FILLED", synced)
            except Exception as e:
                logger.debug("KIS 체결 동기화 스킵: %s", e)

            # DB 이벤트 로그
            try:
                from src.utils.db_logger import log_event
                await log_event("cycle_complete", result)
            except Exception:
                pass

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

    # ── Dynamic Weight Optimization ────────────────────────────────────────

    async def _maybe_update_dynamic_weights(self, active_strategies: list[str]) -> None:
        """DYNAMIC_BLEND_WEIGHTS_ENABLED=true 일 때 성과 기반 가중치로 갱신한다."""
        settings = get_settings()
        if not settings.dynamic_blend_weights_enabled:
            return

        from src.utils.blend_weight_optimizer import BlendWeightOptimizer

        # 활성 전략만 대상으로 최적화 (등록되지 않은 전략은 base_weight 유지)
        base_for_active = {
            k: v for k, v in self.strategy_blend_weights.items() if k in active_strategies
        }
        if not base_for_active:
            return

        active_optimizer = BlendWeightOptimizer(
            base_weights=base_for_active,
            lookback_days=settings.dynamic_blend_lookback_days,
            min_weight=settings.dynamic_blend_min_weight,
        )
        new_weights = await active_optimizer.optimize()
        # 비활성 전략 가중치는 0으로, 활성 전략만 동적 가중치 적용
        updated = {k: new_weights.get(k, 0.0) for k in self.strategy_blend_weights}
        logger.info(
            "동적 블렌딩 가중치 적용: %s → %s",
            self.strategy_blend_weights,
            updated,
        )
        self.strategy_blend_weights = updated

    # ── Weight Normalization ────────────────────────────────────────────────

    def _normalize_active_weights(
        self,
        active_strategies: set[str],
    ) -> dict[str, float]:
        """활성 전략만으로 가중치를 재정규화합니다.

        빈 시그널을 반환한 전략을 제외하고, 나머지 전략의 가중치 합이 1.0이 되도록
        비례 재분배합니다.

        예: A=0.30, B=0.30, RL=0.20 에서 RL 제외 시 → A=0.50, B=0.50
        """
        raw = {
            k: v
            for k, v in self.strategy_blend_weights.items()
            if k in active_strategies and v > 0.0
        }
        total = sum(raw.values())
        if total <= 0:
            # 모든 가중치가 0이면 동일 분배
            if not active_strategies:
                return {}
            equal = 1.0 / len(active_strategies)
            return {k: equal for k in active_strategies}
        return {k: v / total for k, v in raw.items()}

    # ── N-way Blending ─────────────────────────────────────────────────────

    def _blend_nway_predictions(
        self,
        all_predictions: dict[str, list[PredictionSignal]],
    ) -> list[PredictionSignal]:
        """N-way 가중 블렌딩으로 티커별 최종 신호를 생성합니다.

        각 전략의 confidence에 가중치를 곱한 뒤, 티커별로 BUY/SELL/HOLD 스코어를
        합산하여 가장 높은 스코어의 signal을 최종 신호로 채택합니다.

        빈 시그널을 반환한 전략은 제외하고 나머지 전략의 가중치를 재정규화합니다.
        예: RL이 빈 시그널이면 A(0.30)+B(0.30) → A(0.50)+B(0.50)으로 자동 전환.
        """
        # ── 빈 시그널 전략 제외 + 가중치 재정규화 ──
        active_predictions = {
            name: preds
            for name, preds in all_predictions.items()
            if preds  # 빈 리스트 제외
        }
        excluded = set(all_predictions.keys()) - set(active_predictions.keys())
        if excluded:
            logger.info(
                "블렌딩 fallback: %s 전략이 빈 시그널 → %d전략 블렌딩으로 전환",
                sorted(excluded),
                len(active_predictions),
            )

        # 활성 전략만으로 가중치 재정규화
        effective_weights = self._normalize_active_weights(
            set(active_predictions.keys())
        )

        # 티커별로 (signal, weighted_confidence) 누적
        ticker_scores: dict[str, dict[str, float]] = {}
        ticker_best_signal: dict[str, PredictionSignal] = {}

        for strategy_name, predictions in active_predictions.items():
            weight = effective_weights.get(strategy_name, 0.0)
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

    # ── Strategy Runner 등록 ──────────────────────────────────────────────
    # 활성화할 전략을 결정합니다. --strategies 미지정 시 A/B/RL 3전략 등록.
    active = set(s.strip().upper() for s in args.strategies.split(",") if s.strip()) if args.strategies else {"A", "B", "RL"}

    if "A" in active:
        try:
            from src.agents.strategy_a_runner import StrategyARunner
            orchestrator.register_strategy(StrategyARunner())
            logger.info("Strategy A (Tournament) 등록 완료")
        except Exception as e:
            logger.error("Strategy A 등록 실패: %s", e)

    if "B" in active:
        try:
            from src.agents.strategy_b_runner import StrategyBRunner
            orchestrator.register_strategy(StrategyBRunner())
            logger.info("Strategy B (Consensus) 등록 완료")
        except Exception as e:
            logger.error("Strategy B 등록 실패: %s", e)

    if "S" in active:
        try:
            from src.agents.search_runner import SearchRunner
            orchestrator.register_strategy(SearchRunner())
            logger.info("Strategy S (Search) 등록 완료")
        except Exception as e:
            logger.error("Strategy S 등록 실패: %s", e)

    if "RL" in active:
        try:
            from src.agents.rl_runner import RLRunner
            orchestrator.register_strategy(RLRunner())
            logger.info("Strategy RL (Reinforcement Learning) 등록 완료")
        except Exception as e:
            logger.error("Strategy RL 등록 실패: %s", e)

    registered = orchestrator.registry.runner_count
    logger.info("총 %d개 Runner 등록 완료 (요청: %s)", registered, active)
    if registered == 0:
        logger.error(
            "등록된 Runner가 없습니다. "
            "LLM 프로바이더 설정(ANTHROPIC_API_KEY 등)을 확인하거나 "
            "--strategies 옵션으로 전략을 지정하세요."
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
    parser.add_argument(
        "--strategies",
        default="",
        help="활성화할 전략 목록 쉼표 구분 (예: A,B,RL). 미지정 시 A,B,S,RL 모두 등록",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
