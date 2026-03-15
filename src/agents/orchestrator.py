"""
src/agents/orchestrator.py — OrchestratorAgent (N-way blend + Registry + RL 독립)

기본 사이클:
Collector -> StrategyRegistry(병렬) -> Blender(A/B만) + RL(독립) -> PortfolioManager -> Notifier

RL은 블렌딩에 참여하지 않고 독립적으로 트레이딩 결정을 내린다.
--strategies A,B,RL 실행 시 A+B는 블렌딩되고, RL은 별도로 PortfolioManager에 전달된다.
기존 단독 모드(--tournament, --consensus, --rl)와 2-way --blend 모두 하위 호환.
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
from src.agents.research_portfolio_manager import ResearchPortfolioManager
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLPolicyStore
from src.agents.predictor import PredictorAgent
from src.agents.rl_trading import RLTradingAgent
from src.agents.blending import BlendInput, BlendResult, NWayBlendResult, blend_signals, blend_strategy_signals
from src.agents.strategy_runner import StrategyRegistry, StrategyRunner
from src.agents.strategy_b_consensus import StrategyBConsensus
from src.agents.strategy_a_tournament import StrategyATournament
from src.db.models import AgentHeartbeatRecord, PredictionSignal
from src.db.queries import insert_heartbeat
from src.utils.config import get_settings
from src.utils.db_client import fetch
from src.utils.logging import get_logger, setup_logging
from src.utils.market_hours import market_session_status
from src.utils.redis_client import TOPIC_ALERTS, publish_message, set_heartbeat

setup_logging()
logger = get_logger(__name__)


# ────────────────────────── StrategyRunner 구현체 ──────────────────────────


class TournamentRunner:
    """Strategy A 토너먼트를 StrategyRunner로 래핑."""

    name: str = "A"

    def __init__(
        self,
        tournament: StrategyATournament,
        *,
        load_winner_predictions: object,
    ) -> None:
        self._tournament = tournament
        self._load_winner_predictions = load_winner_predictions

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        result = await self._tournament.run_daily_tournament(tickers)
        winner = result["winner_agent_id"]
        predictions = await self._load_winner_predictions(winner, tickers)
        return predictions


class ConsensusRunner:
    """Strategy B 합의를 StrategyRunner로 래핑."""

    name: str = "B"

    def __init__(self, consensus: StrategyBConsensus) -> None:
        self._consensus = consensus

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        return await self._consensus.run(tickers)


class RLRunner:
    """RL Trading을 StrategyRunner로 래핑."""

    name: str = "RL"

    def __init__(self, rl_agent: RLTradingAgent) -> None:
        self._rl = rl_agent
        self.last_summaries: list | None = None

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        predictions, summaries = await self._rl.run_cycle(tickers)
        self.last_summaries = summaries
        return predictions


class SearchRunner:
    """Search/Scraping 리서치를 StrategyRunner로 래핑."""

    name: str = "S"

    def __init__(self, rpm: ResearchPortfolioManager) -> None:
        self._rpm = rpm

    async def run(self, tickers: list[str]) -> list[PredictionSignal]:
        return await self._rpm.run_research_cycle(tickers)


# ────────────────────────── Orchestrator ──────────────────────────


class OrchestratorAgent:
    def __init__(
        self,
        agent_id: str = "orchestrator_agent",
        use_tournament: bool = False,
        use_consensus: bool = False,
        use_blend: bool = False,
        use_rl: bool = False,
        use_search: bool = False,
        strategies: list[str] | None = None,
        tournament_rolling_days: int | None = None,
        tournament_min_samples: int | None = None,
        consensus_rounds: int | None = None,
        consensus_threshold: float | None = None,
        rl_tick_collection_seconds: int = 30,
        rl_yahoo_seed_range: str = "10y",
        rl_policy_store: RLPolicyStore | RLPolicyStoreV2 | None = None,
        search_max_concurrent: int | None = None,
        search_categories: str | None = None,
        search_max_sources: int | None = None,
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

        # 기존 단독 플래그
        self.use_tournament = use_tournament
        self.use_consensus = use_consensus
        self.use_blend = use_blend
        self.use_rl = use_rl
        self.use_search = use_search

        # RL 관련
        self.rl_tick_collection_seconds = max(0, rl_tick_collection_seconds)
        self.rl_yahoo_seed_range = rl_yahoo_seed_range
        needs_rl = use_rl or (strategies and "RL" in strategies)
        self.rl_policy_store = rl_policy_store or (RLPolicyStoreV2() if needs_rl else RLPolicyStore())
        self.rl = RLTradingAgent(
            dataset_interval="daily",
            training_window_days=3650,
            policy_store=self.rl_policy_store,
        )
        self.rl_registry_bootstrap: dict[str, object] | None = None
        if needs_rl:
            self.rl_registry_bootstrap = self._bootstrap_rl_policy_store()

        # Search 관련
        needs_search = use_search or (strategies and "S" in strategies)
        self.research = ResearchPortfolioManager(
            agent_id="research_portfolio_manager",
            max_concurrent_searches=search_max_concurrent or int(self.settings.search_max_concurrent),
            search_categories=search_categories or self.settings.search_categories,
            max_sources_per_ticker=search_max_sources or int(self.settings.search_max_sources),
        ) if needs_search else None

        # --strategies 플래그로 N-way 모드 결정
        self._active_strategies = self._resolve_strategies(strategies)

        # StrategyRegistry 구성
        self.registry = StrategyRegistry()
        self._rl_runner: RLRunner | None = None
        self._search_runner: SearchRunner | None = None
        self._setup_registry()

        # 가중치 로드
        self._blend_weights = self._load_blend_weights()

    def _resolve_strategies(self, strategies: list[str] | None) -> list[str]:
        """CLI 플래그를 기반으로 활성 전략 목록을 결정한다.

        우선순위:
        1. --strategies A,B,RL,S (명시적)
        2. --blend → ["A", "B"]
        3. --tournament → ["A"]
        4. --consensus → ["B"]
        5. --rl → ["RL"]
        6. --search → ["S"]
        7. 없으면 → [] (single_predictor 모드)
        """
        if strategies:
            return [s.strip().upper() for s in strategies if s.strip()]
        if self.use_blend:
            return ["A", "B"]
        if self.use_tournament:
            return ["A"]
        if self.use_consensus:
            return ["B"]
        if self.use_rl:
            return ["RL"]
        if self.use_search:
            return ["S"]
        return []

    def _setup_registry(self) -> None:
        """활성 전략에 따라 Runner를 Registry에 등록한다."""
        if "A" in self._active_strategies:
            self.registry.register(TournamentRunner(
                self.tournament,
                load_winner_predictions=self._load_winner_predictions,
            ))
        if "B" in self._active_strategies:
            self.registry.register(ConsensusRunner(self.consensus))
        if "RL" in self._active_strategies:
            self._rl_runner = RLRunner(self.rl)
            self.registry.register(self._rl_runner)
        if "S" in self._active_strategies:
            if self.research:
                self._search_runner = SearchRunner(self.research)
                self.registry.register(self._search_runner)

    def _load_blend_weights(self) -> dict[str, float]:
        """설정에서 전략별 가중치를 로드한다."""
        try:
            weights = json.loads(self.settings.strategy_blend_weights)
            if isinstance(weights, dict):
                return {k.upper(): float(v) for k, v in weights.items()}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("strategy_blend_weights 파싱 실패, 기본값 사용: %s", exc)
        return {"A": 0.30, "B": 0.30, "RL": 0.20, "S": 0.20}

    async def _load_winner_predictions(self, winner_agent_id: str, tickers: list[str]) -> list:
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
        """기존 2-way A/B 블렌딩 (하위 호환)."""
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
                    strategy="A",
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

    def _blend_nway_predictions(
        self,
        all_predictions: dict[str, list[PredictionSignal]],
    ) -> list[PredictionSignal]:
        """N-way 블렌딩: 여러 전략의 예측을 종목별로 병합한다."""
        # 종목별로 모든 전략의 시그널을 수집
        ticker_signals: dict[str, list[tuple[str, PredictionSignal]]] = {}
        for strategy_name, predictions in all_predictions.items():
            for pred in predictions:
                if pred.ticker not in ticker_signals:
                    ticker_signals[pred.ticker] = []
                ticker_signals[pred.ticker].append((strategy_name, pred))

        blended: list[PredictionSignal] = []
        for ticker in sorted(ticker_signals.keys()):
            inputs: list[BlendInput] = []
            for strategy_name, pred in ticker_signals[ticker]:
                weight = self._blend_weights.get(strategy_name, 0.20)
                inputs.append(BlendInput(
                    strategy=strategy_name,
                    signal=pred.signal,
                    confidence=pred.confidence or 0.5,
                    weight=weight,
                ))

            result = blend_signals(inputs)

            # target_price/stop_loss는 가장 높은 가중치 전략에서 가져옴
            best_pred = None
            best_weight = -1.0
            for strategy_name, pred in ticker_signals[ticker]:
                w = self._blend_weights.get(strategy_name, 0.20)
                if w > best_weight:
                    best_weight = w
                    best_pred = pred

            blended.append(PredictionSignal(
                agent_id="blend_agent",
                llm_model="blend_nway",
                strategy="A",  # DB 호환
                ticker=ticker,
                signal=result.signal,
                confidence=result.confidence,
                target_price=best_pred.target_price if best_pred else None,
                stop_loss=best_pred.stop_loss if best_pred else None,
                reasoning_summary=(
                    f"nway_blend: strategies={result.participating_strategies}, "
                    f"score={result.weighted_score:.4f}, conflict={result.conflict}, "
                    f"signals={result.meta.get('signals', {})}"
                ),
                trading_date=date.today(),
            ))

        return blended

    def _build_blend_meta(
        self,
        all_predictions: dict[str, list[PredictionSignal]],
    ) -> dict:
        """주문에 첨부할 blend 메타데이터를 생성한다."""
        return {
            "strategies": list(all_predictions.keys()),
            "weights": {k: round(self._blend_weights.get(k, 0.0), 4) for k in all_predictions.keys()},
            "strategy_count": len(all_predictions),
        }

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
            # ── 데이터 수집 ──
            collected_count = 0
            cycle_tickers: list[str]
            needs_rl_data = "RL" in self._active_strategies
            if needs_rl_data:
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

            # ── 전략 실행 ──
            winner = None
            rl_summaries = None

            # RL은 항상 독립적으로 트레이딩 결정을 내린다.
            # N-way blend에서 RL을 제외하고, RL 시그널은 별도로 PortfolioManager에 전달한다.
            if self.registry.runner_count >= 2:
                # 모든 전략을 병렬 실행
                all_predictions = await self.registry.run_all(cycle_tickers)

                # RL summaries 추출
                if self._rl_runner and self._rl_runner.last_summaries:
                    rl_summaries = self._rl_runner.last_summaries

                # RL 시그널을 분리: RL은 블렌딩에 참여하지 않고 독립 실행
                rl_predictions = all_predictions.pop("RL", [])
                non_rl_predictions = all_predictions  # RL이 제거된 나머지

                orders: list[dict] = []

                # 1) 비-RL 전략: 2개 이상이면 블렌딩, 1개면 단독 실행
                if len(non_rl_predictions) >= 2:
                    blended = self._blend_nway_predictions(non_rl_predictions)
                    blend_meta = self._build_blend_meta(non_rl_predictions)
                    non_rl_orders = await self.portfolio.process_predictions(
                        blended,
                        signal_source_override="BLEND",
                    )
                    orders.extend(non_rl_orders)
                elif len(non_rl_predictions) == 1:
                    strategy_name = list(non_rl_predictions.keys())[0]
                    preds = list(non_rl_predictions.values())[0]
                    non_rl_orders = await self.portfolio.process_predictions(
                        preds,
                        signal_source_override=strategy_name,
                    )
                    orders.extend(non_rl_orders)
                    blend_meta = None
                else:
                    blend_meta = None

                # 2) RL 독립 실행: RL이 스스로 결정한 시그널을 직접 PortfolioManager에 전달
                rl_orders: list[dict] = []
                if rl_predictions:
                    rl_orders = await self.portfolio.process_predictions(
                        rl_predictions,
                        signal_source_override="RL",
                    )
                    orders.extend(rl_orders)
                    logger.info(
                        "RL 독립 실행 완료: predictions=%d, orders=%d",
                        len(rl_predictions),
                        len(rl_orders),
                    )

                # blend_meta에 RL 독립 실행 정보 추가
                if blend_meta is None:
                    blend_meta = {}
                blend_meta["rl_independent"] = True
                blend_meta["rl_predictions"] = len(rl_predictions)
                blend_meta["rl_orders"] = len(rl_orders)

                # 비-RL 예측 결과 (notifier 카운트용)
                if len(non_rl_predictions) >= 2:
                    predictions = blended
                elif non_rl_predictions:
                    predictions = list(non_rl_predictions.values())[0]
                else:
                    predictions = []
                # predictions 카운트에 RL도 포함
                total_predicted = len(predictions) + len(rl_predictions)

                non_rl_names = sorted(non_rl_predictions.keys())
                if non_rl_names:
                    mode_name = f"blend_nway({','.join(non_rl_names)})+rl_independent"
                else:
                    mode_name = "rl_independent"

            elif self.registry.runner_count == 1:
                # 단일 전략 (기존 단독 모드 호환)
                strategy_name = self.registry.active_names[0]
                runner = self.registry.get(strategy_name)
                assert runner is not None

                predictions = await runner.run(cycle_tickers)

                if self._rl_runner and self._rl_runner.last_summaries:
                    rl_summaries = self._rl_runner.last_summaries

                source_override = strategy_name if strategy_name in ("A", "B", "RL", "S") else None
                orders = await self.portfolio.process_predictions(
                    predictions,
                    signal_source_override=source_override,
                )
                mode_name = {"A": "tournament", "B": "consensus", "RL": "rl"}.get(strategy_name, strategy_name)
                blend_meta = None
                total_predicted = len(predictions)

            else:
                # 기본 single predictor
                predictions = await self.predictor.run_once(tickers=cycle_tickers)
                orders = await self.portfolio.process_predictions(predictions)
                mode_name = "single_predictor"
                blend_meta = None
                total_predicted = len(predictions)

            await self.notifier.send_cycle_summary(
                collected=collected_count,
                predicted=total_predicted,
                orders=len(orders),
            )

            result = {
                "collected": collected_count,
                "predicted": total_predicted,
                "orders": len(orders),
                "winner_agent_id": winner,
                "rl_summaries": rl_summaries,
                "mode": mode_name,
                "active_strategies": self.registry.active_names,
                "blend_meta": blend_meta,
                "started_at": started.isoformat() + "Z",
                "finished_at": datetime.utcnow().isoformat() + "Z",
            }
            if "RL" in self._active_strategies:
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
    # --strategies 가 명시되면 그것을 사용, 아니면 기존 플래그에서 유추
    strategies = None
    if args.strategies:
        strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    agent = OrchestratorAgent(
        use_tournament=args.tournament,
        use_consensus=args.consensus,
        use_blend=args.blend,
        use_rl=args.rl,
        use_search=args.search,
        strategies=strategies,
        tournament_rolling_days=args.tournament_rolling_days,
        tournament_min_samples=args.tournament_min_samples,
        consensus_rounds=args.consensus_rounds,
        consensus_threshold=args.consensus_threshold,
        rl_tick_collection_seconds=args.rl_tick_collection_seconds,
        rl_yahoo_seed_range=args.rl_yahoo_seed_range,
        search_max_concurrent=args.search_max_concurrent,
        search_categories=args.search_categories,
        search_max_sources=args.search_max_sources,
    )
    tickers = args.tickers.split(",") if args.tickers else None
    if args.loop:
        await agent.run_loop(interval_seconds=args.interval_seconds, tickers=tickers)
    else:
        await agent.run_cycle(tickers=tickers)


def main() -> None:
    parser = argparse.ArgumentParser(description="OrchestratorAgent (N-way blend)")
    parser.add_argument("--tickers", default="", help="쉼표 구분 티커 목록")
    parser.add_argument("--loop", action="store_true", help="주기 실행 모드")
    parser.add_argument("--tournament", action="store_true", help="Strategy A 토너먼트 단독 모드")
    parser.add_argument("--consensus", action="store_true", help="Strategy B 합의/토론 단독 모드")
    parser.add_argument("--blend", action="store_true", help="Strategy A/B 2-way 블렌딩 (하위 호환)")
    parser.add_argument("--rl", action="store_true", help="RL Trading lane 단독 모드")
    parser.add_argument("--search", action="store_true", help="Search/Scraping 리서치 파이프라인 단독 모드")
    parser.add_argument(
        "--strategies",
        default="",
        help="쉼표 구분 활성 전략 (예: A,B,RL,S). --blend, --tournament 등보다 우선",
    )
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
    parser.add_argument(
        "--search-max-concurrent",
        type=int,
        default=None,
        help="Search 최대 병렬 검색 수 (기본: 설정값)",
    )
    parser.add_argument(
        "--search-categories",
        default=None,
        help="Search 카테고리 (기본: news)",
    )
    parser.add_argument(
        "--search-max-sources",
        type=int,
        default=None,
        help="Search 종목당 최대 소스 수 (기본: 설정값)",
    )
    parser.add_argument("--interval-seconds", type=int, default=600, help="주기 실행 간격(초)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
