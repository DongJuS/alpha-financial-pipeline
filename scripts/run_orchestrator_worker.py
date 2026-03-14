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


async def main_async() -> int:
    mode = os.getenv("ORCH_MODE", "blend").strip().lower()
    interval_seconds = int(os.getenv("ORCH_INTERVAL_SECONDS", "600"))
    run_once = _env_bool("ORCH_RUN_ONCE", default=False)
    enable_daily_report = _env_bool("ORCH_ENABLE_DAILY_REPORT", default=False)
    report_hour = int(os.getenv("ORCH_DAILY_REPORT_HOUR", "17"))
    report_minute = int(os.getenv("ORCH_DAILY_REPORT_MINUTE", "10"))
    tickers = _parse_tickers(os.getenv("ORCH_TICKERS", ""))
    tournament_rolling_days = _optional_int("ORCH_TOURNAMENT_ROLLING_DAYS")
    tournament_min_samples = _optional_int("ORCH_TOURNAMENT_MIN_SAMPLES")
    consensus_rounds = _optional_int("ORCH_CONSENSUS_ROUNDS")
    consensus_threshold = _optional_float("ORCH_CONSENSUS_THRESHOLD")
    rl_tick_collection_seconds = _optional_int("ORCH_RL_TICK_COLLECTION_SECONDS")
    rl_yahoo_seed_range = os.getenv("ORCH_RL_YAHOO_SEED_RANGE", "10y").strip() or "10y"

    if mode not in {"single", "tournament", "consensus", "blend", "rl"}:
        logger.warning("지원하지 않는 ORCH_MODE=%s, blend로 대체합니다.", mode)
        mode = "blend"

    agent = OrchestratorAgent(
        use_tournament=mode == "tournament",
        use_consensus=mode == "consensus",
        use_blend=mode == "blend",
        use_rl=mode == "rl",
        tournament_rolling_days=tournament_rolling_days,
        tournament_min_samples=tournament_min_samples,
        consensus_rounds=consensus_rounds,
        consensus_threshold=consensus_threshold,
        rl_tick_collection_seconds=(
            rl_tick_collection_seconds if rl_tick_collection_seconds is not None else 30
        ),
        rl_yahoo_seed_range=rl_yahoo_seed_range,
    )

    logger.info(
        "Orchestrator worker 시작: mode=%s, interval=%ss, run_once=%s, daily_report=%s(%02d:%02d KST), tickers=%s, tournament_rolling_days=%s, tournament_min_samples=%s, consensus_rounds=%s, consensus_threshold=%s, rl_tick_collection_seconds=%s, rl_yahoo_seed_range=%s",
        mode,
        interval_seconds,
        run_once,
        enable_daily_report,
        report_hour,
        report_minute,
        tickers,
        tournament_rolling_days,
        tournament_min_samples,
        consensus_rounds,
        consensus_threshold,
        rl_tick_collection_seconds,
        rl_yahoo_seed_range,
    )

    if run_once:
        result = await agent.run_cycle(tickers=tickers)
        if enable_daily_report:
            await agent.notifier.send_paper_daily_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    report_time = time(hour=max(0, min(report_hour, 23)), minute=max(0, min(report_minute, 59)))
    kst = ZoneInfo("Asia/Seoul")
    last_report_date = None

    while True:
        await agent.run_cycle(tickers=tickers)
        if enable_daily_report:
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
