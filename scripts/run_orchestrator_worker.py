"""
scripts/run_orchestrator_worker.py — Docker/운영용 Orchestrator 루프 실행기

환경변수:
  ORCH_MODE=single|tournament|consensus|blend|rl (기본: blend)
  ORCH_TICKERS=005930,000660 (기본: 비어있음 = Collector 기본 종목 사용)
  ORCH_INTERVAL_SECONDS=600 (기본: 600)
  ORCH_RUN_ONCE=false (true면 1회 사이클만 실행)
  ORCH_ENABLE_DAILY_REPORT=false (true면 일일 리포트 자동 발송)
  ORCH_DAILY_REPORT_HOUR=17 (기본: 17, KST 기준)
  ORCH_DAILY_REPORT_MINUTE=10 (기본: 10, KST 기준)
  ORCH_TOURNAMENT_ROLLING_DAYS=5 (선택)
  ORCH_TOURNAMENT_MIN_SAMPLES=3 (선택)
  ORCH_CONSENSUS_ROUNDS=2 (선택)
  ORCH_CONSENSUS_THRESHOLD=0.67 (선택)
  ORCH_RL_TICK_COLLECTION_SECONDS=30 (선택, RL tick 선수집 시간)
  ORCH_RL_YAHOO_SEED_RANGE=10y (선택, RL Yahoo history seed range)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.orchestrator import OrchestratorAgent
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_tickers(raw: str) -> list[str] | None:
    tickers = [t.strip() for t in raw.split(",") if t.strip()]
    return tickers or None


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


def _build_runners(mode: str) -> list:
    """모드에 따라 필요한 StrategyRunner 인스턴스들을 생성합니다."""
    runners = []

    tournament_rolling_days = _optional_int("ORCH_TOURNAMENT_ROLLING_DAYS")
    tournament_min_samples = _optional_int("ORCH_TOURNAMENT_MIN_SAMPLES")
    consensus_rounds = _optional_int("ORCH_CONSENSUS_ROUNDS")
    consensus_threshold = _optional_float("ORCH_CONSENSUS_THRESHOLD")

    if mode in {"tournament", "blend"}:
        try:
            from src.agents.strategy_a_runner import StrategyARunner

            kwargs = {}
            if tournament_rolling_days is not None:
                kwargs["rolling_days"] = tournament_rolling_days
            if tournament_min_samples is not None:
                kwargs["min_samples"] = tournament_min_samples
            runners.append(StrategyARunner(**kwargs))
            logger.info("Strategy A (Tournament) runner 등록")
        except Exception as e:
            logger.error("Strategy A runner 생성 실패: %s", e, exc_info=True)

    if mode in {"consensus", "blend"}:
        try:
            from src.agents.strategy_b_runner import StrategyBRunner

            kwargs = {}
            if consensus_rounds is not None:
                kwargs["max_rounds"] = consensus_rounds
            if consensus_threshold is not None:
                kwargs["consensus_threshold"] = consensus_threshold
            runners.append(StrategyBRunner(**kwargs))
            logger.info("Strategy B (Consensus) runner 등록")
        except Exception as e:
            logger.error("Strategy B runner 생성 실패: %s", e, exc_info=True)

    if mode in {"blend"}:
        try:
            from src.agents.search_runner import SearchRunner
            from src.agents.research_portfolio_manager import ResearchPortfolioManager

            rpm = ResearchPortfolioManager()
            runners.append(SearchRunner(research_portfolio_manager=rpm))
            logger.info("Strategy S (Search) runner 등록")
        except Exception as e:
            logger.error("Strategy S runner 생성 실패: %s", e, exc_info=True)

    if mode in {"rl", "blend"}:
        try:
            from src.agents.rl_runner import RLRunner

            runners.append(RLRunner())
            logger.info("Strategy RL runner 등록")
        except Exception as e:
            logger.error("Strategy RL runner 생성 실패: %s", e, exc_info=True)

    return runners


async def main_async() -> int:
    mode = os.getenv("ORCH_MODE", "blend").strip().lower()
    interval_seconds = int(os.getenv("ORCH_INTERVAL_SECONDS", "600"))
    run_once = _env_bool("ORCH_RUN_ONCE", default=False)
    enable_daily_report = _env_bool("ORCH_ENABLE_DAILY_REPORT", default=False)
    report_hour = int(os.getenv("ORCH_DAILY_REPORT_HOUR", "17"))
    report_minute = int(os.getenv("ORCH_DAILY_REPORT_MINUTE", "10"))
    tickers = _parse_tickers(os.getenv("ORCH_TICKERS", ""))

    if mode not in {"single", "tournament", "consensus", "blend", "rl"}:
        logger.warning("지원하지 않는 ORCH_MODE=%s, blend로 대체합니다.", mode)
        mode = "blend"

    # OrchestratorAgent 생성 (새로운 registry 기반 시그니처)
    agent = OrchestratorAgent()

    # 모드에 따라 StrategyRunner들을 생성하고 등록
    runners = _build_runners(mode)
    for runner in runners:
        agent.register_strategy(runner)

    logger.info(
        "Orchestrator worker 시작: mode=%s, interval=%ss, run_once=%s, "
        "daily_report=%s(%02d:%02d KST), tickers=%s, registered_runners=%s",
        mode,
        interval_seconds,
        run_once,
        enable_daily_report,
        report_hour,
        report_minute,
        tickers,
        agent.registry.list_runners(),
    )

    if not runners:
        logger.error("등록된 StrategyRunner가 없습니다. 종료합니다.")
        return 1

    # tickers가 None이면 collector 기본 종목 사용
    run_tickers = tickers or []

    if run_once:
        result = await agent.run_cycle(tickers=run_tickers)
        if enable_daily_report and hasattr(agent, "notifier"):
            await agent.notifier.send_paper_daily_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    report_time = time(hour=max(0, min(report_hour, 23)), minute=max(0, min(report_minute, 59)))
    kst = ZoneInfo("Asia/Seoul")
    last_report_date = None

    while True:
        try:
            await agent.run_cycle(tickers=run_tickers)
        except Exception as e:
            logger.error("Orchestrator 사이클 실패: %s", e, exc_info=True)

        if enable_daily_report and hasattr(agent, "notifier"):
            now_kst = datetime.now(kst)
            today = now_kst.date()
            if now_kst.time() >= report_time and last_report_date != today:
                ok = await agent.notifier.send_paper_daily_report(report_date=today)
                if ok:
                    last_report_date = today

        await asyncio.sleep(interval_seconds)
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        logger.info("Orchestrator worker 종료 신호 수신")
        sys.exit(0)


if __name__ == "__main__":
    main()
