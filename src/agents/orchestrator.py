"""
src/agents/orchestrator.py — OrchestratorAgent with independent portfolio mode

기본 사이클:
Collector -> StrategyRegistry(병렬) -> Blender/Independent -> PortfolioManager -> Notifier

--independent-portfolio 플래그로 per-strategy PM 인스턴스 지원.
src/agents/orchestrator.py — OrchestratorAgent

여러 StrategyRunner로부터 PredictionSignal을 수집하고,
N-way 되른 블렌딩 남 최종 신호를 돌처 차단기를 적용하여
PortfolioManagerAgent로 전달합니다.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING


from src.brokers import build_virtual_broker
from src.brokers.virtual_broker import VirtualBroker
from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import (
    get_predictor_performance,
    insert_heartbeat,
    insert_prediction,
)
from src.utils.aggregate_risk import AggregateRiskMonitor
from src.utils.config import get_settings
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import set_heartbeat
from src.utils.strategy_promotion import StrategyPromoter

if TYPE_CHECKING:
    from src.agents.orchestrator import StrategyRunner
    from src.agents.portfolio_manager import PortfolioManagerAgent
    from src.agents.notifier import NotifierAgent

setup_logging()
logger = get_logger(__name__)

# N-way 블렌딩 가중치
# A: 토너먼트 (30%), B: 토론 (30%), S: 검색 (20%), RL: 강화학습 (20%)
STRATEGY_BLEND_WEIGHTS = {
    "A": 0.30,
    "B": 0.30,
    "S": 0.20,
    "RL": 0.20,
}


class StrategyRunnerRegistry:
    """전략 러너 (StrategyRunner) 등록 및 관리"""

    def __init__(self):
        self._runners: dict[str, StrategyRunner] = {}

    def register(self, runner: StrategyRunner) -> None:
        """전략 러너를 등록합니다."""
        self._runners[runner.name] = runner
        logger.info(f"Registered strategy runner: {runner.name}")

    def get(self, name: str) -> StrategyRunner | None:
        """전략 러너를 조회합니다."""
        return self._runners.get(name)

    def list_runners(self) -> list[str]:
        """등록된 모든 러너를 목록으로 반환합니다."""
from src.utils.logging import get_logger
from src.utils.redis_client import set_heartbeat

if TYPE_CHECKING:
    from src.agents.orchestrator import StrategyRunner

logger = get_logger(__name__)

# N-way 블렌딩 가중캘
# A: 토너먼트 (30%), B: 토론 (30%), S: 검색 (20%), RL: 강화학습 (20%)
STRATEGY_BLEND_WEIGHTS = {
    "A": 0.30,
    "B": 0.30,
    "S": 0.20,
    "RL": 0.20,
}


class StrategyRunnerRegistry:
    """전략 러너 (StrategyRunner) 등록 및 관리"""

    def __init__(self):
        self._runners: dict[str, StrategyRunner] = {}

    def register(self, runner: StrategyRunner) -> None:
        """전략 러너를 등록합니다."""
        self._runners[runner.name] = runner
        logger.info(f"Registered strategy runner: {runner.name}")

    def get(self, name: str) -> StrategyRunner | None:
        """전략 러너를 달는 단담닝닙다."""
        return self._runners.get(name)

    def list_runners(self) -> list[str]:
        """등록된 모든 러너를 닜연즈 처리로 반환합니다."""
        return list(self._runners.keys())


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
    N-way 블렌딩을 적용한 다 돌을 적용하여
    최종 매매 신호를 채잰다.

    단순 예샤:
    1. 모든 러너 동시 ì°¸ 남
    2. 등록된 단담닝닙다가 강도를 남 남그른닱단당 메커니즘는닱닱드
    3. 최촣 강도 당닉다 + 돍아뀘비낅닉다매 처리 남 최종 매다무 신호 남
    4. PortfolioManagerAgent로 남 남
    """

    def __init__(
        self,
        agent_id: str = "orchestrator",
        strategy_blend_weights: dict[str, float] | None = None,
        independent_portfolio: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.strategy_blend_weights = strategy_blend_weights or STRATEGY_BLEND_WEIGHTS
        self.registry = StrategyRunnerRegistry()
        self.independent_portfolio = independent_portfolio

        # 독립 포트폴리오 모드용 per-strategy PM 인스턴스
        self._strategy_portfolios: dict[str, PortfolioManagerAgent] = {}
        self._strategy_virtual_brokers: dict[str, VirtualBroker] = {}

    def register_strategy(self, runner: StrategyRunner) -> None:
        """전략 러너를 등록합니다."""
        self.registry.register(runner)

    def _get_portfolio_for_strategy(
        self,
        strategy_id: str,
    ) -> PortfolioManagerAgent:
        """전략별 PM 인스턴스를 지연 생성합니다."""
        if strategy_id not in self._strategy_portfolios:
            # 동적으로 임포트하여 순환 임포트 방지
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

    async def run_strategies(
        self,
        tickers: list[str],
    ) -> dict[str, list[PredictionSignal]]:
        """모든 등록된 러너를 병렬 실행합니다.
    async def run_strategies(
        self,
        tickers: list[str],
    ) -> dict[str, list[PredictionSignal]]:
        """모든 등록된 러너를 병렬 동단답다.

        Returns:
            {
                "A": [signal1, signal2, ...],
                "B": [signal1, signal2, ...],
                "S": [signal1, signal2, ...],
                ...
            }
        """
        tasks = []
        runner_names = []
        for runner_name in self.registry.list_runners():
            runner = self.registry.get(runner_name)
            if runner:
                tasks.append(runner.run(tickers))
                runner_names.append(runner_name)

        signals_by_runner = await asyncio.gather(*tasks, return_exceptions=True)

        result = {}
        for runner_name, signals in zip(runner_names, signals_by_runner):
            if isinstance(signals, Exception):
                logger.error(f"Strategy {runner_name} failed: {signals}")
                result[runner_name] = []
            else:
                result[runner_name] = signals

        return result

    async def run_cycle(self, tickers: list[str]) -> dict:
        """한 사이클 실행: 수집 -> 전략 실행 -> 블렌딩/독립 처리 -> 주문 실행.

        Args:
            tickers: 분석할 티커 목록

        Returns:
            {
                "collected": int,
                "predicted": int,
                "orders": int,
                "mode": str,
                "started_at": str,
                "finished_at": str,
                "active_strategies": list[str],
                "blend_meta": dict | None,
                "risk_violations": list | None,
                "promotion_alerts": list | None,
            }
        """
        started = datetime.utcnow()
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
                    "started_at": started.isoformat() + "Z",
                    "finished_at": datetime.utcnow().isoformat() + "Z",
                    "active_strategies": [],
                }

            # 기본 정보
            collected_count = sum(
                len(preds) for preds in all_predictions.values()
            )
            predicted_count = collected_count

            all_orders = []
            promotion_alerts = []
            risk_violations = []

            if self.independent_portfolio:
                # ── 독립 포트폴리오 모드 ──
                logger.info(
                    "Running in independent portfolio mode with %d strategies",
                    len(all_predictions),
                )

                # 집계 위험 모니터 확인
                risk_monitor = AggregateRiskMonitor()
                risk_summary = await risk_monitor.get_risk_summary()

                if risk_summary.get("violations"):
                    risk_violations = risk_summary.get("violations", [])
                    logger.warning(
                        "Aggregate risk violations detected: %s",
                        risk_violations,
                    )

                # 전략별 처리
                for strategy_name, predictions in all_predictions.items():
                    logger.info(
                        "Processing %d predictions for strategy %s",
                        len(predictions),
                        strategy_name,
                    )

                    if not predictions:
                        continue

                    # 전략별 PM으로 라우팅
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
                                strategy_name
                            )
                        )
                        if readiness and readiness.is_ready:
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
                        logger.warning(
                            "Promotion check failed for %s: %s",
                            strategy_name,
                            e,
                        )

                # 위험 스냅샷 기록
                try:
                    await risk_monitor.record_risk_snapshot()
                except Exception as e:
                    logger.warning("Risk snapshot recording failed: %s", e)

                mode_name = (
                    f"independent_portfolio({len(all_predictions)} strategies)"
                )
                blend_meta = None

            else:
                # ── 기본 블렌딩 모드 (향후 확장) ──
                logger.info(
                    "Running in blend mode with %d strategies",
                    len(all_predictions),
                )
                # 이 부분은 향후 _blend_nway_predictions 로직 추가 예정
                mode_name = "blend_mode"
                blend_meta = {
                    "strategies": list(all_predictions.keys()),
                    "weights": {
                        k: round(self.strategy_blend_weights.get(k, 0.0), 4)
                        for k in all_predictions.keys()
                    },
                }
                all_orders = []

            # 기록
            await set_heartbeat(self.agent_id)
            result = {
                "collected": collected_count,
                "predicted": predicted_count,
                "orders": len(all_orders),
                "mode": mode_name,
                "started_at": started.isoformat() + "Z",
                "finished_at": datetime.utcnow().isoformat() + "Z",
                "active_strategies": list(all_predictions.keys()),
                "blend_meta": blend_meta,
                "risk_violations": risk_violations if risk_violations else None,
                "promotion_alerts": (
                    promotion_alerts if promotion_alerts else None
                ),
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

    def _create_notifier(self) -> NotifierAgent:
        """NotifierAgent 인스턴스를 생성합니다."""
        from src.agents.notifier import NotifierAgent

        return NotifierAgent(agent_id="notifier_for_orchestrator")


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

            else:
                result[runner_name] = signals

        return result
