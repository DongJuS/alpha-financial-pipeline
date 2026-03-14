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
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLPolicyStore
from src.agents.predictor import PredictorAgent
from src.agents.rl_trading import RLTradingAgent
from src.agents.blending import blend_strategy_signals
from src.agents.strategy_b_consensus import StrategyBConsensus
from src.agents.strategy_a_tournament import StrategyATournament
from src.db.models import AgentHeartbeatRecord
from src.db.queries import insert_heartbeat
from src.utils.config import get_settings
from src.utils.db_client import fetch
from src.utils.logging import get_logger, setup_logging
from src.utils.market_hours import market_session_status
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
        use_rl: bool = False,
        tournament_rolling_days: int | None = None,
        tournament_min_samples: int | None = None,
        consensus_rounds: int | None = None,
        consensus_threshold: float | None = None,
        rl_tick_collection_seconds: int = 30,
        rl_yahoo_seed_range: str = "10y",
        rl_policy_store: RLPolicyStore | RLPolicyStoreV2 | None = None,
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
        self.use_rl = use_rl
        self.rl_tick_collection_seconds = max(0, rl_tick_collection_seconds)
        self.rl_yahoo_seed_range = rl_yahoo_seed_range
        self.rl_policy_store = rl_policy_store or (RLPolicyStoreV2() if use_rl else RLPolicyStore())
        self.rl = RLTradingAgent(
            dataset_interval="daily",
            training_window_days=3650,
            policy_store=self.rl_policy_store,
        )
        self.rl_registry_bootstrap: dict[str, object] | None = None
        if self.use_rl:
            self.rl_registry_bootstrap = self._bootstrap_rl_policy_store()

    async def _load_winner_predictions(self, winner_agent_id: str, tickers: list[str]) -> list:
        from src.db.models import PredictionSignal

        rows = await fetch(
            """
            SELECT DISTINCT ON (ticker)
                   agent_id, llm_model, strategy, ticker, signal,
                   confidence::float AS confidence, target_price, stop_loss,
                   reasoning_summary, trading_date
            FROM predictions
            WHERE strategy = 'A'
              AND agent_id = $1
              AND trading_date = $2
              AND ticker = ANY($3::text[])
            ORDER BY ticker, timestamp_utc DESC, id DESC
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

    def _bootstrap_rl_policy_store(self) -> dict[str, object]:
        """RL 런타임이 사용할 정책 저장소 상태를 부팅 시점에 로드합니다."""
        snapshot = self._snapshot_rl_policy_store()
        if snapshot.get("registry_enabled"):
            logger.info(
                "Orchestrator RL registry bootstrap: path=%s exists=%s tickers=%s policies=%s active=%s",
                snapshot.get("registry_path"),
                snapshot.get("registry_exists"),
                snapshot.get("ticker_count"),
                snapshot.get("policy_count"),
                snapshot.get("active_policies"),
            )
        else:
            logger.info(
                "Orchestrator RL policy bootstrap: backend=%s source=%s",
                snapshot.get("backend"),
                snapshot.get("active_policy_source"),
            )
        return snapshot

    def _snapshot_rl_policy_store(self) -> dict[str, object]:
        """현재 RL 정책 저장소 상태를 요약합니다."""
        store = getattr(self.rl, "policy_store", None)
        if store is None:
            return {
                "backend": "unconfigured",
                "registry_enabled": False,
            }

        if not hasattr(store, "load_registry"):
            return {
                "backend": "legacy_active_policies",
                "registry_enabled": False,
                "active_policy_source": "active_policies.json",
            }

        try:
            registry = store.load_registry()
        except Exception as exc:
            logger.warning("Orchestrator RL registry 로드 실패: %s", exc)
            return {
                "backend": "policy_registry_v2",
                "registry_enabled": True,
                "load_error": str(exc),
            }

        registry_path = getattr(store, "registry_path", None)
        active_policies = registry.list_active_policies()
        return {
            "backend": "policy_registry_v2",
            "registry_enabled": True,
            "registry_path": str(registry_path) if registry_path is not None else None,
            "registry_exists": bool(registry_path and Path(registry_path).exists()),
            "ticker_count": len(registry.tickers),
            "policy_count": registry.total_policy_count(),
            "active_policy_count": sum(1 for policy_id in active_policies.values() if policy_id),
            "active_policies": active_policies,
            "last_updated": registry.last_updated.isoformat(),
        }

    async def run_cycle(self, tickers: list[str] | None = None) -> dict:
        started = datetime.utcnow()
        try:
            collected_count = 0
            cycle_tickers: list[str]
            if self.use_rl:
                yahoo_points = await self.collector.collect_yahoo_daily_bars(
                    tickers=tickers,
                    range_=self.rl_yahoo_seed_range,
                    interval="1d",
                )
                collected_count += len(yahoo_points)
                cycle_tickers = list(dict.fromkeys([p.ticker for p in yahoo_points])) or (tickers or [])
                if not cycle_tickers:
                    raise ValueError("RL mode는 명시적인 tickers 인자 또는 Yahoo seed 결과가 필요합니다.")

                market_status = await market_session_status()
                if market_status == "open" and self.rl_tick_collection_seconds > 0:
                    try:
                        collected_count += await self.collector.collect_realtime_ticks(
                            cycle_tickers,
                            duration_seconds=self.rl_tick_collection_seconds,
                            fallback_on_error=False,
                        )
                    except Exception as exc:
                        logger.warning("RL tick 수집 실패, Yahoo history 기반으로 계속 진행합니다: %s", exc)
                else:
                    logger.info(
                        "RL KIS tick 실시간 수집 생략: market_status=%s, duration=%ss",
                        market_status,
                        self.rl_tick_collection_seconds,
                    )
            else:
                collected_points = await self.collector.collect_daily_bars(tickers=tickers)
                collected_count = len(collected_points)
                cycle_tickers = list(dict.fromkeys([p.ticker for p in collected_points])) or (tickers or [])

            winner = None
            rl_summaries = None
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
            elif self.use_rl:
                predictions, rl_summaries = await self.rl.run_cycle(cycle_tickers)
                orders = await self.portfolio.process_predictions(
                    predictions,
                    signal_source_override="RL",
                )
            else:
                predictions = await self.predictor.run_once(tickers=cycle_tickers)
                orders = await self.portfolio.process_predictions(predictions)
            await self.notifier.send_cycle_summary(
                collected=collected_count,
                predicted=len(predictions),
                orders=len(orders),
            )

            result = {
                "collected": collected_count,
                "predicted": len(predictions),
                "orders": len(orders),
                "winner_agent_id": winner,
                "rl_summaries": rl_summaries,
                "mode": (
                    "blend"
                    if self.use_blend
                    else (
                        "consensus"
                        if self.use_consensus
                        else ("tournament" if self.use_tournament else ("rl" if self.use_rl else "single_predictor"))
                    )
                ),
                "started_at": started.isoformat() + "Z",
                "finished_at": datetime.utcnow().isoformat() + "Z",
            }
            if self.use_rl:
                result["rl_registry_state"] = self._snapshot_rl_policy_store()

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
        use_rl=args.rl,
        tournament_rolling_days=args.tournament_rolling_days,
        tournament_min_samples=args.tournament_min_samples,
        consensus_rounds=args.consensus_rounds,
        consensus_threshold=args.consensus_threshold,
        rl_tick_collection_seconds=args.rl_tick_collection_seconds,
        rl_yahoo_seed_range=args.rl_yahoo_seed_range,
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
    parser.add_argument("--rl", action="store_true", help="RL Trading lane 실행 모드")
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
    parser.add_argument(
        "--rl-tick-collection-seconds",
        type=int,
        default=30,
        help="RL tick 모드에서 KIS 실시간 틱을 선수집할 시간(초)",
    )
    parser.add_argument(
        "--rl-yahoo-seed-range",
        default="10y",
        help="RL mode에서 Yahoo history seed에 사용할 range",
    )
    parser.add_argument("--interval-seconds", type=int, default=600, help="주기 실행 간격(초)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
