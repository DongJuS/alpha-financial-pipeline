"""
src/agents/orchestrator.py — OrchestratorAgent MVP

기본 사이클:
Collector -> Predictor -> PortfolioManager -> Notifier
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.collector import CollectorAgent
from src.agents.notifier import NotifierAgent
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.agents.predictor import PredictorAgent
from src.agents.blending import blend_strategy_signals
from src.agents.strategy_b_consensus import StrategyBConsensus
from src.agents.strategy_a_tournament import StrategyATournament
from src.db.models import AgentHeartbeatRecord
from src.db.queries import insert_heartbeat
from src.utils.config import get_settings
from src.utils.db_client import fetch
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import TOPIC_ALERTS, publish_message, set_heartbeat

setup_logging()
logger = get_logger(__name__)


class OrchestratorAgent:
    def __init__(
        self,
        agent_id: str = "orchestrator_agent",
        use_tournament: bool = False,
        use_consensus: bool = False,
        use_blend: bool = False,
        tournament_rolling_days: int | None = None,
        tournament_min_samples: int | None = None,
        consensus_rounds: int | None = None,
        consensus_threshold: float | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.settings = get_settings()
        self.collector = CollectorAgent()
        self.predictor = PredictorAgent()
        self.tournament = StrategyATournament(
            rolling_days=tournament_rolling_days,
            min_samples=tournament_min_samples,
        )
        self.consensus = StrategyBConsensus(
            max_rounds=consensus_rounds,
            consensus_threshold=consensus_threshold,
        )
        self.portfolio = PortfolioManagerAgent()
        self.notifier = NotifierAgent()
        self.use_tournament = use_tournament
        self.use_consensus = use_consensus
        self.use_blend = use_blend

    async def _load_winner_predictions(self, winner_agent_id: str, tickers: list[str]) -> list:
        from src.db.models import PredictionSignal

        rows = await fetch(
            """
            SELECT agent_id, llm_model, strategy, ticker, signal,
                   confidence::float AS confidence, target_price, stop_loss,
                   reasoning_summary, trading_date
            FROM predictions
            WHERE strategy = 'A'
              AND agent_id = $1
              AND trading_date = $2
              AND ticker = ANY($3::text[])
            """,
            winner_agent_id,
            date.today(),
            tickers,
        )
        return [
            PredictionSignal(
                agent_id=r["agent_id"],
                llm_model=r["llm_model"],
                strategy=r["strategy"],
                ticker=r["ticker"],
                signal=r["signal"],
                confidence=r["confidence"],
                target_price=r["target_price"],
                stop_loss=r["stop_loss"],
                reasoning_summary=r["reasoning_summary"],
                trading_date=r["trading_date"],
            )
            for r in rows
        ]

    @staticmethod
    def _blend_predictions(predictions_a: list, predictions_b: list, ratio: float) -> list:
        from src.db.models import PredictionSignal

        by_ticker_a = {p.ticker: p for p in predictions_a}
        by_ticker_b = {p.ticker: p for p in predictions_b}
        tickers = sorted(set(by_ticker_a.keys()) | set(by_ticker_b.keys()))
        blended_predictions: list[PredictionSignal] = []

        for ticker in tickers:
            pa = by_ticker_a.get(ticker)
            pb = by_ticker_b.get(ticker)
            blended = blend_strategy_signals(
                strategy_a_signal=pa.signal if pa else None,
                strategy_a_confidence=pa.confidence if pa else None,
                strategy_b_signal=pb.signal if pb else None,
                strategy_b_confidence=pb.confidence if pb else None,
                blend_ratio=ratio,
            )

            if pb and ratio >= 0.5:
                target_price = pb.target_price
                stop_loss = pb.stop_loss
            elif pa:
                target_price = pa.target_price
                stop_loss = pa.stop_loss
            else:
                target_price = None
                stop_loss = None

            blended_predictions.append(
                PredictionSignal(
                    agent_id="blend_agent",
                    llm_model="blend",
                    strategy="A",  # DB 제약(A/B) 때문에 A로 저장/전달하고 주문 소스는 BLEND로 분리 전달
                    ticker=ticker,
                    signal=blended.combined_signal,
                    confidence=blended.combined_confidence,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    reasoning_summary=(
                        f"blend_ratio={ratio:.2f}, conflict={blended.conflict}, "
                        f"A={pa.signal if pa else 'HOLD'}, B={pb.signal if pb else 'HOLD'}"
                    ),
                    trading_date=date.today(),
                )
            )
        return blended_predictions

    async def run_cycle(self, tickers: list[str] | None = None) -> dict:
        started = datetime.utcnow()
        try:
            collected_points = await self.collector.collect_daily_bars(tickers=tickers)
            cycle_tickers = list(dict.fromkeys([p.ticker for p in collected_points])) or (tickers or [])

            winner = None
            if self.use_blend:
                tournament_result = await self.tournament.run_daily_tournament(cycle_tickers)
                winner = tournament_result["winner_agent_id"]
                predictions_a = await self._load_winner_predictions(winner, cycle_tickers)
                predictions_b = await self.consensus.run(cycle_tickers)
                ratio = self.settings.strategy_blend_ratio
                predictions = self._blend_predictions(predictions_a, predictions_b, ratio)
                orders = await self.portfolio.process_predictions(
                    predictions,
                    signal_source_override="BLEND",
                )
            elif self.use_consensus:
                predictions = await self.consensus.run(cycle_tickers)
                orders = await self.portfolio.process_predictions(predictions)
            elif self.use_tournament:
                tournament_result = await self.tournament.run_daily_tournament(cycle_tickers)
                winner = tournament_result["winner_agent_id"]
                predictions = await self._load_winner_predictions(winner, cycle_tickers)
                orders = await self.portfolio.process_predictions(predictions)
            else:
                predictions = await self.predictor.run_once(tickers=cycle_tickers)
                orders = await self.portfolio.process_predictions(predictions)
            await self.notifier.send_cycle_summary(
                collected=len(collected_points),
                predicted=len(predictions),
                orders=len(orders),
            )

            result = {
                "collected": len(collected_points),
                "predicted": len(predictions),
                "orders": len(orders),
                "winner_agent_id": winner,
                "mode": (
                    "blend"
                    if self.use_blend
                    else (
                        "consensus"
                        if self.use_consensus
                        else ("tournament" if self.use_tournament else "single_predictor")
                    )
                ),
                "started_at": started.isoformat() + "Z",
                "finished_at": datetime.utcnow().isoformat() + "Z",
            }

            await set_heartbeat(self.agent_id)
            await insert_heartbeat(
                AgentHeartbeatRecord(
                    agent_id=self.agent_id,
                    status="healthy",
                    last_action=f"사이클 완료 (수집 {result['collected']} / 예측 {result['predicted']} / 주문 {result['orders']})",
                    metrics=result,
                )
            )
            logger.info("Orchestrator cycle 완료: %s", result)
            return result
        except Exception as e:
            err_msg = f"Orchestrator cycle 실패: {e}"
            await publish_message(
                TOPIC_ALERTS,
                json.dumps(
                    {
                        "type": "orchestrator_error",
                        "message": err_msg,
                        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                    },
                    ensure_ascii=False,
                ),
            )
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

    async def run_loop(self, interval_seconds: int, tickers: list[str] | None = None) -> None:
        while True:
            await self.run_cycle(tickers=tickers)
            await asyncio.sleep(interval_seconds)


async def _main_async(args: argparse.Namespace) -> None:
    agent = OrchestratorAgent(
        use_tournament=args.tournament,
        use_consensus=args.consensus,
        use_blend=args.blend,
        tournament_rolling_days=args.tournament_rolling_days,
        tournament_min_samples=args.tournament_min_samples,
        consensus_rounds=args.consensus_rounds,
        consensus_threshold=args.consensus_threshold,
    )
    tickers = args.tickers.split(",") if args.tickers else None
    if args.loop:
        await agent.run_loop(interval_seconds=args.interval_seconds, tickers=tickers)
    else:
        await agent.run_cycle(tickers=tickers)


def main() -> None:
    parser = argparse.ArgumentParser(description="OrchestratorAgent MVP")
    parser.add_argument("--tickers", default="", help="쉼표 구분 티커 목록")
    parser.add_argument("--loop", action="store_true", help="주기 실행 모드")
    parser.add_argument("--tournament", action="store_true", help="Strategy A 5개 인스턴스 토너먼트 모드")
    parser.add_argument("--consensus", action="store_true", help="Strategy B 합의/토론 모드")
    parser.add_argument("--blend", action="store_true", help="Strategy A/B 블렌딩 실행 모드")
    parser.add_argument(
        "--tournament-rolling-days",
        type=int,
        default=None,
        help="Strategy A 롤링 점수 계산 일수 (기본: 설정값)",
    )
    parser.add_argument(
        "--tournament-min-samples",
        type=int,
        default=None,
        help="Strategy A 우승자 선정 최소 샘플 수 (기본: 설정값)",
    )
    parser.add_argument(
        "--consensus-rounds",
        type=int,
        default=None,
        help="Strategy B 최대 토론 라운드 수 (기본: 설정값)",
    )
    parser.add_argument(
        "--consensus-threshold",
        type=float,
        default=None,
        help="Strategy B 합의 confidence 임계치 0.0~1.0 (기본: 설정값)",
    )
    parser.add_argument("--interval-seconds", type=int, default=600, help="주기 실행 간격(초)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
