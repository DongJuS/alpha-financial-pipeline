"""
src/services/rl_retrain_pipeline.py — RL 재학습 파이프라인

S3 Data Lake에서 historical daily_bars Parquet를 읽어
RL 모델을 주기적으로 재학습하는 파이프라인입니다.

핵심 흐름:
    1. datalake_reader로 지정 기간의 daily_bars 로드
    2. RLDataset 형태로 변환
    3. TabularQTrainerV2로 학습
    4. walk-forward 검증
    5. 기존 정책 대비 성과 비교 (승격 게이트)
    6. 합격 시 RLPolicyStoreV2에 저장

사용 예:
    result = await retrain_from_datalake("005930", days=180)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetrainResult:
    """재학습 결과 요약."""
    ticker: str
    status: Literal["success", "skipped", "failed"]
    reason: str = ""
    data_points: int = 0
    train_return_pct: float = 0.0
    holdout_return_pct: float = 0.0
    baseline_return_pct: float = 0.0
    excess_return_pct: float = 0.0
    prev_policy_return_pct: float | None = None
    improvement_pct: float | None = None
    walk_forward_passed: bool = False
    deployed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def _load_closes_from_datalake(
    ticker: str,
    start: date,
    end: date,
) -> tuple[list[float], list[str]]:
    """S3에서 daily_bars를 읽어 closes/timestamps 리스트로 변환합니다."""
    from src.services.datalake_reader import load_records
    from src.services.datalake import DataType

    records = await load_records(DataType.DAILY_BARS, start, end, ticker=ticker)

    if not records:
        return [], []

    # 날짜순 정렬
    sorted_recs = sorted(records, key=lambda r: str(r.get("date", "")))

    closes: list[float] = []
    timestamps: list[str] = []
    for rec in sorted_recs:
        close = rec.get("close")
        dt = rec.get("date")
        if close is not None and dt is not None:
            closes.append(float(close))
            timestamps.append(str(dt))

    return closes, timestamps


async def retrain_from_datalake(
    ticker: str,
    days: int = 180,
    min_data_points: int = 60,
    train_ratio: float = 0.7,
    compare_existing: bool = True,
    auto_deploy: bool = False,
) -> RetrainResult:
    """S3 Data Lake의 히스토리컬 데이터로 RL 모델을 재학습합니다.

    Args:
        ticker: 종목 코드
        days: 학습 데이터 기간 (일)
        min_data_points: 최소 데이터 포인트 수
        train_ratio: 학습/검증 비율
        compare_existing: 기존 정책과 성과 비교 여부
        auto_deploy: 합격 시 자동 배포 여부

    Returns:
        RetrainResult
    """
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)

    # 1. S3에서 데이터 로드
    try:
        closes, timestamps = await _load_closes_from_datalake(ticker, start, end)
    except Exception as e:
        return RetrainResult(
            ticker=ticker, status="failed",
            reason=f"데이터 로드 실패: {e}",
        )

    if len(closes) < min_data_points:
        return RetrainResult(
            ticker=ticker, status="skipped",
            reason=f"데이터 부족: {len(closes)}/{min_data_points}",
            data_points=len(closes),
        )

    # 2. RLDataset 구성 + 학습
    try:
        from src.agents.rl_trading import RLDataset
        from src.agents.rl_trading_v2 import TabularQTrainerV2

        dataset = RLDataset(ticker=ticker, closes=closes, timestamps=timestamps)
        trainer = TabularQTrainerV2()
        artifact = trainer.train(dataset, train_ratio=train_ratio)
    except Exception as e:
        return RetrainResult(
            ticker=ticker, status="failed",
            reason=f"학습 실패: {e}",
            data_points=len(closes),
        )

    # 3. Walk-forward 검증
    walk_forward_passed = False
    try:
        from src.agents.rl_walk_forward import WalkForwardEvaluator

        evaluator = WalkForwardEvaluator()
        wf_result = evaluator.evaluate(dataset, n_folds=3)
        walk_forward_passed = wf_result.get("passed", False)
    except Exception as e:
        logger.warning("Walk-forward 검증 실패: %s", e)

    # 4. 기존 정책 대비 비교
    prev_return: float | None = None
    improvement: float | None = None
    if compare_existing:
        try:
            from src.agents.rl_policy_store_v2 import RLPolicyStoreV2

            store = RLPolicyStoreV2()
            existing = store.load_policy(ticker, algorithm="tabular")
            if existing and existing.evaluation:
                prev_return = existing.evaluation.get("total_return_pct")
                if prev_return is not None and artifact.evaluation:
                    new_return = artifact.evaluation.get("total_return_pct", 0)
                    improvement = new_return - prev_return
        except Exception:
            logger.debug("기존 정책 비교 건너뜀")

    # 5. 배포 판단
    holdout_return = artifact.evaluation.get("total_return_pct", 0) if artifact.evaluation else 0
    baseline_return = artifact.evaluation.get("baseline_return_pct", 0) if artifact.evaluation else 0
    excess = holdout_return - baseline_return

    deployed = False
    if auto_deploy and walk_forward_passed and excess > 0:
        # 기존 대비 개선되었거나 기존이 없는 경우 배포
        should_deploy = (
            improvement is None  # 기존 정책 없음
            or (improvement is not None and improvement > 0)  # 기존보다 나음
        )
        if should_deploy:
            try:
                from src.agents.rl_policy_store_v2 import RLPolicyStoreV2

                store = RLPolicyStoreV2()
                store.save_policy(artifact)
                deployed = True
                logger.info(
                    "RL 정책 자동 배포: %s (수익률 %.2f%%, 초과수익 %.2f%%)",
                    ticker, holdout_return, excess,
                )
            except Exception as e:
                logger.warning("정책 저장 실패: %s", e)

    return RetrainResult(
        ticker=ticker,
        status="success",
        data_points=len(closes),
        train_return_pct=round(holdout_return, 2),
        holdout_return_pct=round(holdout_return, 2),
        baseline_return_pct=round(baseline_return, 2),
        excess_return_pct=round(excess, 2),
        prev_policy_return_pct=round(prev_return, 2) if prev_return is not None else None,
        improvement_pct=round(improvement, 2) if improvement is not None else None,
        walk_forward_passed=walk_forward_passed,
        deployed=deployed,
    )


async def retrain_all_tickers(
    tickers: list[str] | None = None,
    days: int = 180,
    auto_deploy: bool = False,
) -> list[RetrainResult]:
    """여러 종목의 RL 모델을 일괄 재학습합니다.

    tickers가 None이면 S3에 daily_bars가 있는 종목을 자동 탐색합니다.
    """
    from src.services.datalake_reader import list_keys
    from src.services.datalake import DataType

    if tickers is None:
        # S3에서 최근 7일간 daily_bars 키를 조회하여 티커 추출
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=7)
        keys = await list_keys(DataType.DAILY_BARS, start, end)

        ticker_set: set[str] = set()
        for key in keys:
            # key: daily_bars/year=.../month=.../day=.../005930.parquet
            parts = key.rsplit("/", 1)
            if len(parts) == 2 and parts[1].endswith(".parquet"):
                ticker_set.add(parts[1].replace(".parquet", ""))
        tickers = sorted(ticker_set)

    logger.info("RL 일괄 재학습 시작: %d 종목, %d일 데이터", len(tickers), days)

    results: list[RetrainResult] = []
    for ticker in tickers:
        result = await retrain_from_datalake(
            ticker=ticker,
            days=days,
            auto_deploy=auto_deploy,
        )
        results.append(result)
        logger.info(
            "  %s: %s (데이터 %d, 초과수익 %.2f%%)",
            ticker, result.status, result.data_points, result.excess_return_pct,
        )

    success = sum(1 for r in results if r.status == "success")
    deployed = sum(1 for r in results if r.deployed)
    logger.info(
        "RL 일괄 재학습 완료: %d/%d 성공, %d 배포",
        success, len(results), deployed,
    )
    return results
