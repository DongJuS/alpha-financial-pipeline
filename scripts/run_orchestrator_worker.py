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


# ── Environment Helpers ──────────────────────────────────────────────────────


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

    # Orchestrator 생성
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

    if run_once:
        result = await agent.run_cycle(tickers=tickers or ["005930", "000660"])
        if enable_daily_report:
            notifier = agent._create_notifier()
            await notifier.send_paper_daily_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    report_time = time(
        hour=max(0, min(report_hour, 23)),
        minute=max(0, min(report_minute, 59)),
    )
    kst = ZoneInfo("Asia/Seoul")
    last_report_date = None

    while True:
        try:
            await agent.run_cycle(tickers=tickers or ["005930", "000660"])
        except Exception as e:
            logger.error("사이클 실행 실패 (계속 진행): %s", e, exc_info=True)

        if enable_daily_report:
            now_kst = datetime.now(kst)
            today = now_kst.date()
            if now_kst.time() >= report_time and last_report_date != today:
                try:
                    notifier = agent._create_notifier()
                    ok = await notifier.send_paper_daily_report(report_date=today)
                    if ok:
                        last_report_date = today
                except Exception as e:
                    logger.warning("일일 리포트 발송 실패: %s", e)

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
