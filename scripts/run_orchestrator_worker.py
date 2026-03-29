"""
scripts/run_orchestrator_worker.py — Docker/운영용 Orchestrator 루프 실행기

환경변수:
  ORCH_TICKERS=005930,000660 (기본: 비어있음 = 기본 종목 사용)
  ORCH_INTERVAL_SECONDS=600 (기본: 600)
  ORCH_RUN_ONCE=false (true면 1회 사이클만 실행)
  ORCH_INDEPENDENT_PORTFOLIO=false (true면 독립 포트폴리오 모드)
  ORCH_ENABLE_DAILY_REPORT=false (true면 일일 리포트 자동 발송)
  ORCH_DAILY_REPORT_HOUR=17 (기본: 17, KST 기준)
  ORCH_DAILY_REPORT_MINUTE=10 (기본: 10, KST 기준)
  ORCH_ENABLE_STRATEGY_A=true (Strategy A 토너먼트 활성화)
  ORCH_ENABLE_STRATEGY_B=true (Strategy B 토론 활성화)
  ORCH_ENABLE_STRATEGY_RL=true (Strategy RL 활성화)
  ORCH_ENABLE_STRATEGY_S=false (Strategy S 검색 활성화)
  ORCH_TOURNAMENT_ROLLING_DAYS=5 (선택)
  ORCH_TOURNAMENT_MIN_SAMPLES=3 (선택)
  ORCH_CONSENSUS_ROUNDS=2 (선택)
  ORCH_CONSENSUS_THRESHOLD=0.67 (선택)
  ORCH_ENABLE_RL_AUTO_RETRAIN=false (true면 장 마감 후 RL 자동 재학습)
  ORCH_RL_RETRAIN_HOUR=16 (기본: 16, KST 기준)
  ORCH_RL_RETRAIN_MINUTE=40 (기본: 40, KST 기준)
  ORCH_RL_RETRAIN_TICKERS=005930,000660 (기본: 비어있음 = RL registry/worker tickers 사용)
  ORCH_RL_RETRAIN_PROFILES=tabular_q_v2_momentum,tabular_q_v1_baseline
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.config import get_settings
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import set_heartbeat

if TYPE_CHECKING:
    from src.agents.orchestrator import OrchestratorAgent

setup_logging()
logger = get_logger(__name__)

# ── Heartbeat Keepalive ─────────────────────────────────────────────────────

# worker 프로세스가 살아있는 동안 heartbeat를 갱신할 에이전트 목록
_WORKER_AGENT_IDS = [
    "orchestrator_agent",
    "collector_agent",
    "predictor_1",
    "predictor_2",
    "predictor_3",
    "predictor_4",
    "predictor_5",
    "portfolio_manager_agent",
    "notifier_agent",
]

_KEEPALIVE_INTERVAL = 30  # 초 — TTL_HEARTBEAT(90s)보다 충분히 짧게
_DEFAULT_TICKERS = ["005930", "000660", "259960"]
_KST = ZoneInfo("Asia/Seoul")


async def _heartbeat_keepalive(stop_event: asyncio.Event) -> None:
    """백그라운드에서 주기적으로 모든 에이전트의 Redis heartbeat를 갱신합니다.

    이렇게 하면 사이클 간 대기 시간(ORCH_INTERVAL_SECONDS)이 TTL(90s)보다
    길어도 에이전트가 "연결됨" 상태를 유지합니다.
    """
    while not stop_event.is_set():
        try:
            for agent_id in _WORKER_AGENT_IDS:
                await set_heartbeat(agent_id)
        except Exception as e:
            logger.warning("Heartbeat keepalive 실패 (계속 진행): %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_KEEPALIVE_INTERVAL)
            break  # stop_event가 설정되면 종료
        except asyncio.TimeoutError:
            pass  # 타임아웃 → 다시 루프


# ── Environment Helpers ──────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_tickers(raw: str) -> list[str] | None:
    tickers = [t.strip() for t in raw.split(",") if t.strip()]
    return tickers or None


def _parse_csv(raw: str) -> list[str] | None:
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return values or None


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s 파싱 실패(%s), 무시합니다.", name, raw)
        return None


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s 파싱 실패(%s), 무시합니다.", name, raw)
        return None


def _is_weekend_kst(now: datetime | None = None) -> bool:
    """KST 기준으로 현재가 주말인지 반환합니다."""
    current = now or datetime.now(_KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_KST)
    else:
        current = current.astimezone(_KST)
    return current.weekday() > 4


async def _run_cycle_if_weekday(
    agent: OrchestratorAgent,
    tickers: list[str] | None,
    *,
    now_kst: datetime | None = None,
) -> dict | None:
    """주말에는 Orchestrator 사이클을 건너뜁니다. gen 모드(GEN_API_URL 설정 시)는 예외."""
    current = now_kst or datetime.now(_KST)
    if _is_weekend_kst(current) and not get_settings().gen_api_url:
        logger.info("주말(%s)에는 Orchestrator 사이클을 건너뜁니다.", current.date().isoformat())
        return None
    return await agent.run_cycle(tickers=tickers or _DEFAULT_TICKERS)


# ── Strategy Registration ────────────────────────────────────────────────────


def _build_strategy_runners() -> list:
    """환경변수에 따라 활성 전략 러너들을 생성합니다."""
    runners = []

    # Strategy A — Tournament
    if _env_bool("ORCH_ENABLE_STRATEGY_A", default=True):
        from src.agents.strategy_a_runner import StrategyARunner

        rolling_days = _optional_int("ORCH_TOURNAMENT_ROLLING_DAYS")
        min_samples = _optional_int("ORCH_TOURNAMENT_MIN_SAMPLES")
        runners.append(
            StrategyARunner(
                rolling_days=rolling_days,
                min_samples=min_samples,
            )
        )
        logger.info(
            "Strategy A (Tournament) 활성화: rolling_days=%s, min_samples=%s",
            rolling_days,
            min_samples,
        )

    # Strategy B — Consensus/Debate
    if _env_bool("ORCH_ENABLE_STRATEGY_B", default=True):
        from src.agents.strategy_b_runner import StrategyBRunner

        consensus_rounds = _optional_int("ORCH_CONSENSUS_ROUNDS")
        consensus_threshold = _optional_float("ORCH_CONSENSUS_THRESHOLD")
        runners.append(
            StrategyBRunner(
                max_rounds=consensus_rounds,
                consensus_threshold=consensus_threshold,
            )
        )
        logger.info(
            "Strategy B (Consensus) 활성화: max_rounds=%s, threshold=%s",
            consensus_rounds,
            consensus_threshold,
        )

    # Strategy RL — Reinforcement Learning
    if _env_bool("ORCH_ENABLE_STRATEGY_RL", default=True):
        from src.agents.rl_runner import RLRunner

        runners.append(RLRunner())
        logger.info("Strategy RL (Q-Learning) 활성화")

    # Strategy S — Search/Scraping
    if _env_bool("ORCH_ENABLE_STRATEGY_S", default=False):
        try:
            from src.agents.search_runner import SearchRunner
            from src.agents.research_portfolio_manager import ResearchPortfolioManager

            rpm = ResearchPortfolioManager()
            runners.append(SearchRunner(research_portfolio_manager=rpm))
            logger.info("Strategy S (Search) 활성화")
        except Exception as e:
            logger.warning("Strategy S 초기화 실패 (건너뜀): %s", e)

    if not runners:
        logger.warning("활성화된 전략이 없습니다. 사이클이 비어있게 됩니다.")

    return runners


# ── Main ─────────────────────────────────────────────────────────────────────


async def main_async() -> int:
    interval_seconds = int(os.getenv("ORCH_INTERVAL_SECONDS", "600"))
    run_once = _env_bool("ORCH_RUN_ONCE", default=False)
    independent_portfolio = _env_bool("ORCH_INDEPENDENT_PORTFOLIO", default=False)
    enable_daily_report = _env_bool("ORCH_ENABLE_DAILY_REPORT", default=False)
    report_hour = int(os.getenv("ORCH_DAILY_REPORT_HOUR", "17"))
    report_minute = int(os.getenv("ORCH_DAILY_REPORT_MINUTE", "10"))
    tickers = _parse_tickers(os.getenv("ORCH_TICKERS", ""))
    enable_rl_auto_retrain = _env_bool("ORCH_ENABLE_RL_AUTO_RETRAIN", default=False)
    rl_retrain_hour = int(os.getenv("ORCH_RL_RETRAIN_HOUR", "16"))
    rl_retrain_minute = int(os.getenv("ORCH_RL_RETRAIN_MINUTE", "40"))
    rl_retrain_tickers = _parse_tickers(os.getenv("ORCH_RL_RETRAIN_TICKERS", ""))
    rl_retrain_profiles = _parse_csv(os.getenv("ORCH_RL_RETRAIN_PROFILES", ""))

    # Orchestrator 생성
    from src.agents.orchestrator import OrchestratorAgent

    agent = OrchestratorAgent(
        independent_portfolio=independent_portfolio,
    )

    # 전략 러너 등록
    runners = _build_strategy_runners()
    agent.register_strategies(*runners)

    logger.info(
        "Orchestrator worker 시작: strategies=%s, interval=%ss, run_once=%s, "
        "independent_portfolio=%s, daily_report=%s(%02d:%02d KST), tickers=%s",
        [r.name for r in runners],
        interval_seconds,
        run_once,
        independent_portfolio,
        enable_daily_report,
        report_hour,
        report_minute,
        tickers,
    )
    logger.info(
        "RL auto retrain: enabled=%s, schedule=%02d:%02d KST, tickers=%s, profiles=%s",
        enable_rl_auto_retrain,
        rl_retrain_hour,
        rl_retrain_minute,
        rl_retrain_tickers,
        rl_retrain_profiles,
    )

    if run_once:
        result = await _run_cycle_if_weekday(agent, tickers)
        if enable_daily_report:
            notifier = agent._create_notifier()
            await notifier.send_paper_daily_report()
        print(json.dumps(result or {"skipped": True, "reason": "weekend"}, ensure_ascii=False, indent=2))
        return 0

    # ── 백그라운드 heartbeat keepalive 시작 ──────────────────────────────
    stop_event = asyncio.Event()
    keepalive_task = asyncio.create_task(_heartbeat_keepalive(stop_event))
    logger.info(
        "Heartbeat keepalive 시작: agents=%s, interval=%ss",
        _WORKER_AGENT_IDS,
        _KEEPALIVE_INTERVAL,
    )

    report_time = time(
        hour=max(0, min(report_hour, 23)),
        minute=max(0, min(report_minute, 59)),
    )
    last_report_date = None
    retrain_time = time(
        hour=max(0, min(rl_retrain_hour, 23)),
        minute=max(0, min(rl_retrain_minute, 59)),
    )
    last_rl_retrain_date = None

    try:
        while True:
            try:
                await _run_cycle_if_weekday(agent, tickers)
            except Exception as e:
                logger.error("사이클 실행 실패 (계속 진행): %s", e, exc_info=True)

            if enable_daily_report:
                now_kst = datetime.now(_KST)
                today = now_kst.date()
                if now_kst.time() >= report_time and last_report_date != today:
                    try:
                        notifier = agent._create_notifier()
                        ok = await notifier.send_paper_daily_report(report_date=today)
                        if ok:
                            last_report_date = today
                    except Exception as e:
                        logger.warning("일일 리포트 발송 실패: %s", e)

            if enable_rl_auto_retrain:
                now_kst = datetime.now(_KST)
                today = now_kst.date()
                if (
                    (not _is_weekend_kst(now_kst) or get_settings().gen_api_url)
                    and now_kst.time() >= retrain_time
                    and last_rl_retrain_date != today
                ):
                    try:
                        from src.agents.rl_continuous_improver import RLContinuousImprover

                        improver = RLContinuousImprover()
                        outcomes = await improver.retrain_all(
                            tickers=rl_retrain_tickers or tickers,
                            profile_ids=rl_retrain_profiles,
                        )
                        logger.info(
                            "RL auto retrain 완료: total=%d, success=%d, deployed=%d",
                            len(outcomes),
                            sum(1 for item in outcomes if item.success),
                            sum(1 for item in outcomes if item.deployed),
                        )
                        last_rl_retrain_date = today
                    except Exception as e:
                        logger.warning("RL auto retrain 실패: %s", e, exc_info=True)

            await asyncio.sleep(interval_seconds)
    finally:
        stop_event.set()
        await keepalive_task

    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        logger.info("Orchestrator worker 종료 신호 수신")
        sys.exit(0)


if __name__ == "__main__":
    main()
