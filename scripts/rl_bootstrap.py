"""
scripts/rl_bootstrap.py — RL 부트스트랩 파이프라인

FDR 720일 과거 데이터 시딩 → 멀티 프로파일 학습 → walk-forward 검증 → 활성 정책 등록
end-to-end CLI 스크립트.

사용 예:
  # 기본 티커(005930,000660,259960)에 대해 720일 데이터로 부트스트랩
  python scripts/rl_bootstrap.py

  # 특정 티커 지정
  python scripts/rl_bootstrap.py --tickers 005930,000660

  # 데이터 시딩만 (학습 없이)
  python scripts/rl_bootstrap.py --seed-only

  # 학습만 (시딩 스킵, DB에 데이터가 이미 있을 때)
  python scripts/rl_bootstrap.py --train-only

  # 강제 승격 (승격 게이트 무시)
  python scripts/rl_bootstrap.py --force-promote

  # dry-run (실제 저장 없이 시뮬레이션)
  python scripts/rl_bootstrap.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.agents.rl_continuous_improver import RLContinuousImprover, RetrainOutcome
from src.agents.rl_policy_store_v2 import RLPolicyStoreV2
from src.agents.rl_trading import RLDatasetBuilder
from src.db.queries import fetch_recent_market_data
from src.utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_TICKERS = ["005930", "000660", "259960"]
DEFAULT_SEED_DAYS = 720
DEFAULT_TRAIN_DAYS = 720
DEFAULT_PROFILES = ["tabular_q_v2_momentum", "tabular_q_v1_baseline"]


# ── 데이터 시딩 ─────────────────────────────────────────────────────────


@dataclass
class SeedResult:
    ticker: str
    success: bool
    rows: int = 0
    source: str = "fdr"
    error: Optional[str] = None


async def seed_fdr_history(
    ticker: str,
    days: int = DEFAULT_SEED_DAYS,
    *,
    force: bool = False,
) -> SeedResult:
    """FDR로 과거 데이터를 수집하여 DB에 저장합니다.

    기존 RLDatasetBuilder의 FDR 폴백 로직을 사전 시딩 용도로 호출합니다.
    DB에 데이터가 이미 충분하면 스킵합니다.
    """
    # DB에 이미 충분한 데이터가 있는지 확인
    if not force:
        try:
            existing = await fetch_recent_market_data(ticker, interval="daily", days=days)
            if len(existing) >= days * 0.6:  # 60% 이상이면 충분
                logger.info(
                    "[시딩] %s: DB에 이미 %d건 존재 (목표 %d일), 스킵",
                    ticker, len(existing), days,
                )
                return SeedResult(ticker=ticker, success=True, rows=len(existing), source="db_existing")
        except Exception:
            pass  # DB 조회 실패 시 FDR 시딩 진행

    # RLDatasetBuilder의 FDR 폴백을 트리거하기 위해 build_dataset 호출
    # min_history_points를 높게 설정하면 DB 데이터 부족 시 FDR 폴백이 자동 실행됨
    builder = RLDatasetBuilder(min_history_points=40)
    try:
        dataset = await builder.build_dataset(ticker, days=days)
        logger.info(
            "[시딩] %s: %d건 데이터 확보 완료 (기간: %s ~ %s)",
            ticker,
            len(dataset.closes),
            dataset.timestamps[0] if dataset.timestamps else "N/A",
            dataset.timestamps[-1] if dataset.timestamps else "N/A",
        )
        return SeedResult(ticker=ticker, success=True, rows=len(dataset.closes))
    except Exception as exc:
        logger.error("[시딩] %s: 실패 — %s", ticker, exc)
        return SeedResult(ticker=ticker, success=False, error=str(exc))


async def seed_all_tickers(
    tickers: list[str],
    days: int = DEFAULT_SEED_DAYS,
    *,
    force: bool = False,
) -> list[SeedResult]:
    """멀티 티커 시딩을 순차 실행합니다."""
    results: list[SeedResult] = []
    for i, ticker in enumerate(tickers, 1):
        logger.info("[시딩] (%d/%d) %s 시작...", i, len(tickers), ticker)
        result = await seed_fdr_history(ticker, days, force=force)
        results.append(result)
        # FDR rate limiting
        if i < len(tickers):
            await asyncio.sleep(1.0)
    return results


# ── 부트스트랩 학습 ─────────────────────────────────────────────────────


@dataclass
class BootstrapResult:
    ticker: str
    seed: Optional[SeedResult] = None
    retrain: Optional[RetrainOutcome] = None


async def bootstrap_ticker(
    ticker: str,
    *,
    seed_days: int = DEFAULT_SEED_DAYS,
    train_days: int = DEFAULT_TRAIN_DAYS,
    profile_ids: list[str] | None = None,
    force_promote: bool = False,
    seed_only: bool = False,
    train_only: bool = False,
    force_seed: bool = False,
) -> BootstrapResult:
    """단일 티커 부트스트랩: 시딩 → 학습 → 활성화."""
    result = BootstrapResult(ticker=ticker)

    # Step 1: 데이터 시딩
    if not train_only:
        result.seed = await seed_fdr_history(ticker, seed_days, force=force_seed)
        if not result.seed.success:
            logger.error("[부트스트랩] %s: 데이터 시딩 실패, 학습 스킵", ticker)
            return result

    if seed_only:
        return result

    # Step 2: 학습 + 검증 + 활성화
    profiles = profile_ids or DEFAULT_PROFILES
    store = RLPolicyStoreV2()
    improver = RLContinuousImprover(policy_store=store)

    try:
        outcome = await improver.retrain_ticker(
            ticker,
            profile_ids=profiles,
            dataset_days=train_days,
        )
        result.retrain = outcome

        # 강제 승격: 승격 게이트를 통과하지 못했지만 best candidate가 있는 경우
        if force_promote and outcome.success and not outcome.deployed and outcome.new_policy_id:
            logger.info(
                "[부트스트랩] %s: 강제 승격 시도 (policy=%s)",
                ticker, outcome.new_policy_id,
            )
            promoted = store.force_activate_policy(ticker, outcome.new_policy_id)
            if promoted:
                outcome.deployed = True
                outcome.active_policy_after = outcome.new_policy_id
                logger.info("[부트스트랩] %s: 강제 승격 완료", ticker)

        _log_retrain_outcome(ticker, outcome)
    except Exception as exc:
        logger.error("[부트스트랩] %s: 학습 실패 — %s", ticker, exc)
        result.retrain = RetrainOutcome(
            ticker=ticker, success=False, error=str(exc),
        )

    return result


def _log_retrain_outcome(ticker: str, outcome: RetrainOutcome) -> None:
    """학습 결과를 로깅합니다."""
    if not outcome.success:
        logger.warning("[부트스트랩] %s: 학습 실패 — %s", ticker, outcome.error)
        return

    status = "활성화 완료" if outcome.deployed else "승격 게이트 미통과"
    logger.info(
        "[부트스트랩] %s: %s\n"
        "  정책 ID: %s\n"
        "  프로파일: %s\n"
        "  초과 수익률: %.2f%%\n"
        "  Walk-forward: %s (일관성: %.2f)\n"
        "  활성 정책: %s → %s",
        ticker,
        status,
        outcome.new_policy_id,
        outcome.profile_id,
        outcome.excess_return or 0.0,
        "통과" if outcome.walk_forward_passed else "실패",
        outcome.walk_forward_consistency or 0.0,
        outcome.active_policy_before or "없음",
        outcome.active_policy_after or "없음",
    )


# ── 메인 실행 ─────────────────────────────────────────────────────────


async def run_bootstrap(args: argparse.Namespace) -> dict:
    """부트스트랩 전체 파이프라인 실행."""
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()] if args.profiles else None

    logger.info(
        "=== RL 부트스트랩 시작 ===\n"
        "  티커: %s\n"
        "  시딩 기간: %d일\n"
        "  학습 기간: %d일\n"
        "  프로파일: %s\n"
        "  강제 승격: %s\n"
        "  모드: %s",
        tickers,
        args.seed_days,
        args.train_days,
        profiles or DEFAULT_PROFILES,
        args.force_promote,
        "시딩만" if args.seed_only else "학습만" if args.train_only else "전체",
    )

    if args.dry_run:
        logger.info("[DRY-RUN] 실제 실행 없이 종료합니다.")
        return {"mode": "dry_run", "tickers": tickers}

    results: list[BootstrapResult] = []
    for i, ticker in enumerate(tickers, 1):
        logger.info("\n{'='*60}\n[%d/%d] %s 부트스트랩 시작\n{'='*60}", i, len(tickers), ticker)
        result = await bootstrap_ticker(
            ticker,
            seed_days=args.seed_days,
            train_days=args.train_days,
            profile_ids=profiles,
            force_promote=args.force_promote,
            seed_only=args.seed_only,
            train_only=args.train_only,
            force_seed=args.force_seed,
        )
        results.append(result)

    # 최종 리포트
    report = _build_report(results)
    _print_report(report)
    return report


def _build_report(results: list[BootstrapResult]) -> dict:
    """최종 리포트 딕셔너리 생성."""
    report: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_tickers": len(results),
        "seed_success": 0,
        "seed_failed": 0,
        "train_success": 0,
        "train_failed": 0,
        "policies_activated": 0,
        "tickers": {},
    }

    for r in results:
        ticker_info: dict = {"ticker": r.ticker}

        if r.seed:
            ticker_info["seed"] = {
                "success": r.seed.success,
                "rows": r.seed.rows,
                "source": r.seed.source,
                "error": r.seed.error,
            }
            if r.seed.success:
                report["seed_success"] += 1
            else:
                report["seed_failed"] += 1

        if r.retrain:
            ticker_info["retrain"] = {
                "success": r.retrain.success,
                "policy_id": r.retrain.new_policy_id,
                "profile_id": r.retrain.profile_id,
                "excess_return": r.retrain.excess_return,
                "walk_forward_passed": r.retrain.walk_forward_passed,
                "deployed": r.retrain.deployed,
                "active_policy_before": r.retrain.active_policy_before,
                "active_policy_after": r.retrain.active_policy_after,
                "error": r.retrain.error,
            }
            if r.retrain.success:
                report["train_success"] += 1
            else:
                report["train_failed"] += 1
            if r.retrain.deployed:
                report["policies_activated"] += 1

        report["tickers"][r.ticker] = ticker_info

    return report


def _print_report(report: dict) -> None:
    """최종 리포트 출력."""
    logger.info(
        "\n=== RL 부트스트랩 완료 ===\n"
        "  전체 티커: %d\n"
        "  시딩 성공: %d / 실패: %d\n"
        "  학습 성공: %d / 실패: %d\n"
        "  활성화된 정책: %d",
        report["total_tickers"],
        report["seed_success"],
        report["seed_failed"],
        report["train_success"],
        report["train_failed"],
        report["policies_activated"],
    )

    for ticker, info in report["tickers"].items():
        retrain = info.get("retrain", {})
        if retrain.get("deployed"):
            logger.info("  [OK] %s → %s", ticker, retrain.get("policy_id"))
        elif retrain.get("success"):
            logger.info("  [--] %s → 학습 완료, 승격 게이트 미통과", ticker)
        elif retrain.get("error"):
            logger.info("  [XX] %s → %s", ticker, retrain.get("error"))

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RL 부트스트랩: FDR 데이터 시딩 → 학습 → 활성 정책 등록",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_TICKERS),
        help=f"쉼표 구분 티커 목록 (기본: {','.join(DEFAULT_TICKERS)})",
    )
    parser.add_argument(
        "--seed-days",
        type=int,
        default=DEFAULT_SEED_DAYS,
        help=f"FDR 데이터 시딩 기간 (기본: {DEFAULT_SEED_DAYS}일)",
    )
    parser.add_argument(
        "--train-days",
        type=int,
        default=DEFAULT_TRAIN_DAYS,
        help=f"RL 학습 데이터 기간 (기본: {DEFAULT_TRAIN_DAYS}일)",
    )
    parser.add_argument(
        "--profiles",
        default="",
        help=f"쉼표 구분 프로파일 목록 (기본: {','.join(DEFAULT_PROFILES)})",
    )
    parser.add_argument(
        "--force-promote",
        action="store_true",
        help="승격 게이트 미통과 시에도 강제 승격",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="데이터 시딩만 실행 (학습 스킵)",
    )
    parser.add_argument(
        "--train-only",
        action="store_true",
        help="학습만 실행 (시딩 스킵, DB에 데이터가 이미 있을 때)",
    )
    parser.add_argument(
        "--force-seed",
        action="store_true",
        help="기존 데이터가 있어도 강제 시딩",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 실행 없이 대상 티커와 설정만 표시",
    )
    args = parser.parse_args()

    if args.seed_only and args.train_only:
        parser.error("--seed-only와 --train-only는 동시에 사용할 수 없습니다.")

    asyncio.run(run_bootstrap(args))


if __name__ == "__main__":
    main()
