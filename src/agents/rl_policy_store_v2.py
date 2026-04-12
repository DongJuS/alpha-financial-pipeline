"""
src/agents/rl_policy_store_v2.py — RLPolicyStoreV2 (DB 기반)

Q-table 파일은 파일시스템에 유지, 정책 메타데이터만 PostgreSQL DB에 저장한다.
registry.json 파일 I/O 를 완전히 제거하고 DB 쿼리로 대체.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agents.rl_policy_registry import (
    CLEANUP_MAX_APPROVED_PER_TICKER,
    CLEANUP_UNAPPROVED_DAYS,
    DEFAULT_MAX_DRAWDOWN_LIMIT_PCT,
    PolicyEntry,
    algorithm_dir_name,
    build_relative_path,
)
from src.agents.rl_trading import RLPolicyArtifact
from src.utils.db_client import execute, fetch, fetchrow, get_pool
from src.utils.logging import get_logger
from src.utils.ticker import normalize

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = ROOT / "artifacts" / "rl" / "models"


class RLPolicyStoreV2:
    """V2 정책 저장소 -- DB 기반.

    Q-table 파일은 파일시스템에 유지, 정책 메타데이터만 DB에 저장한다.
    """

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = Path(models_dir or DEFAULT_MODELS_DIR)

    # ──────────────────────────── Policy CRUD ────────────────────────────

    async def save_policy(self, artifact: RLPolicyArtifact) -> RLPolicyArtifact:
        """정책 아티팩트를 파일로 저장하고 DB에 메타데이터를 INSERT/UPSERT 한다."""
        artifact.ticker = normalize(artifact.ticker)

        # 디렉토리 생성 + 파일 저장
        algo_dir = algorithm_dir_name(artifact.algorithm)
        ticker_dir = self.models_dir / algo_dir / artifact.ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        file_path = ticker_dir / f"{artifact.policy_id}.json"
        payload = artifact.to_dict()
        payload["artifact_path"] = str(file_path)
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifact.artifact_path = str(file_path)

        # DB UPSERT
        relative_path = build_relative_path(
            artifact.algorithm, artifact.ticker, artifact.policy_id
        )
        hyperparams = json.dumps({
            "lookback": artifact.lookback,
            "episodes": artifact.episodes,
            "learning_rate": artifact.learning_rate,
            "discount_factor": artifact.discount_factor,
            "epsilon": artifact.epsilon,
            "trade_penalty_bps": artifact.trade_penalty_bps,
        })

        try:
            await execute(
                """
                INSERT INTO rl_policies (
                    policy_id, instrument_id, algorithm, state_version,
                    return_pct, baseline_return_pct, excess_return_pct,
                    max_drawdown_pct, trades, win_rate, holdout_steps,
                    approved, is_active, file_path, hyperparams, created_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7,
                    $8, $9, $10, $11,
                    $12, $13, $14, $15::jsonb, $16
                )
                ON CONFLICT (policy_id) DO UPDATE SET
                    return_pct       = EXCLUDED.return_pct,
                    baseline_return_pct = EXCLUDED.baseline_return_pct,
                    excess_return_pct = EXCLUDED.excess_return_pct,
                    max_drawdown_pct = EXCLUDED.max_drawdown_pct,
                    trades           = EXCLUDED.trades,
                    win_rate         = EXCLUDED.win_rate,
                    holdout_steps    = EXCLUDED.holdout_steps,
                    approved         = EXCLUDED.approved,
                    file_path        = EXCLUDED.file_path,
                    hyperparams      = EXCLUDED.hyperparams
                """,
                artifact.policy_id,
                artifact.ticker,
                artifact.algorithm,
                artifact.state_version,
                artifact.evaluation.total_return_pct,
                artifact.evaluation.baseline_return_pct,
                artifact.evaluation.excess_return_pct,
                artifact.evaluation.max_drawdown_pct,
                artifact.evaluation.trades,
                artifact.evaluation.win_rate,
                artifact.evaluation.holdout_steps,
                artifact.evaluation.approved,
                False,  # is_active: 저장 시에는 비활성
                relative_path,
                hyperparams,
                datetime.fromisoformat(artifact.created_at),
            )
        except Exception as exc:
            if "foreign" in str(exc).lower() or "ForeignKeyViolation" in type(exc).__name__:
                logger.error(
                    "정책 저장 실패 — instruments 테이블에 ticker 없음: %s (policy_id=%s)",
                    artifact.ticker,
                    artifact.policy_id,
                )
            raise

        logger.info("정책 저장 완료: %s -> %s", artifact.policy_id, relative_path)
        return artifact

    async def load_policy(
        self, policy_id: str, ticker: str | None = None
    ) -> Optional[RLPolicyArtifact]:
        """policy_id 로 DB에서 메타데이터를 조회하고 파일에서 Q-table을 로드한다."""
        if ticker:
            ticker = normalize(ticker)
            row = await fetchrow(
                "SELECT * FROM rl_policies WHERE policy_id = $1 AND instrument_id = $2",
                policy_id,
                ticker,
            )
        else:
            row = await fetchrow(
                "SELECT * FROM rl_policies WHERE policy_id = $1",
                policy_id,
            )

        if not row:
            return None

        entry = PolicyEntry.from_db_row(row)
        return self._load_artifact_from_entry(entry)

    async def load_active_policy(self, ticker: str) -> Optional[RLPolicyArtifact]:
        """종목의 활성 정책을 DB에서 조회하고 Q-table을 로드한다."""
        ticker = normalize(ticker)
        row = await fetchrow(
            "SELECT * FROM rl_policies WHERE instrument_id = $1 AND is_active = true",
            ticker,
        )
        if not row:
            return None

        entry = PolicyEntry.from_db_row(row)
        return self._load_artifact_from_entry(entry)

    async def activate_policy(self, artifact: RLPolicyArtifact) -> bool:
        """정책을 활성 상태로 승격한다. 승격 게이트 검증 포함.

        승격 조건:
        - approved == True
        - max_drawdown_pct >= DEFAULT_MAX_DRAWDOWN_LIMIT_PCT
        - return_pct > 현재 활성 정책의 return_pct (또는 활성 정책 없음)

        DB 트랜잭션: 기존 활성 정책 is_active=false + 새 정책 is_active=true.
        """
        ticker = normalize(artifact.ticker)
        policy_id = artifact.policy_id

        # DB에서 후보 정책 조회
        candidate_row = await fetchrow(
            "SELECT * FROM rl_policies WHERE policy_id = $1",
            policy_id,
        )
        if not candidate_row:
            logger.warning("승격 대상 정책이 DB에 없음: %s", policy_id)
            return False

        candidate = PolicyEntry.from_db_row(candidate_row)

        # 승격 게이트 검증
        if not candidate.approved:
            logger.info("정책 승격 실패 (미승인): %s", policy_id)
            return False

        if candidate.max_drawdown_pct < DEFAULT_MAX_DRAWDOWN_LIMIT_PCT:
            logger.info(
                "정책 승격 실패 (drawdown %.2f%% < %.2f%%): %s",
                candidate.max_drawdown_pct,
                DEFAULT_MAX_DRAWDOWN_LIMIT_PCT,
                policy_id,
            )
            return False

        # 기존 활성 정책과 수익률 비교
        current_active_row = await fetchrow(
            "SELECT * FROM rl_policies WHERE instrument_id = $1 AND is_active = true",
            ticker,
        )
        if current_active_row:
            current_return = float(current_active_row["return_pct"])
            if candidate.return_pct <= current_return:
                logger.info(
                    "정책 승격 실패 (수익률 %.2f%% <= 현재 활성 %.2f%%): %s",
                    candidate.return_pct,
                    current_return,
                    policy_id,
                )
                return False

        # 트랜잭션으로 활성 정책 교체
        await self._swap_active(ticker, policy_id)

        logger.info(
            "정책 승격 완료: %s (ticker=%s, return=%.2f%%)",
            policy_id,
            ticker,
            artifact.evaluation.total_return_pct,
        )
        return True

    async def force_activate_policy(self, ticker: str, policy_id: str) -> bool:
        """강제 승격 (수동 승인용). 게이트 조건 무시."""
        ticker = normalize(ticker)

        # 정책 존재 확인
        exists = await fetchrow(
            "SELECT 1 FROM rl_policies WHERE policy_id = $1",
            policy_id,
        )
        if not exists:
            logger.warning("강제 승격 실패 - 정책 없음: %s", policy_id)
            return False

        await self._swap_active(ticker, policy_id)
        logger.info("정책 강제 승격: %s (ticker=%s)", policy_id, ticker)
        return True

    async def list_active_policies(self) -> dict[str, Optional[str]]:
        """모든 종목의 활성 정책 ID를 반환한다."""
        rows = await fetch(
            "SELECT instrument_id, policy_id FROM rl_policies WHERE is_active = true"
        )
        return {row["instrument_id"]: row["policy_id"] for row in rows}

    async def list_policies(self, ticker: str) -> list[PolicyEntry]:
        """종목의 모든 정책 엔트리를 반환한다."""
        ticker = normalize(ticker)
        rows = await fetch(
            "SELECT * FROM rl_policies WHERE instrument_id = $1 ORDER BY created_at DESC",
            ticker,
        )
        return [PolicyEntry.from_db_row(r) for r in rows]

    async def list_all_tickers(self) -> list[str]:
        """등록된 모든 종목(instrument_id)을 반환한다."""
        rows = await fetch(
            "SELECT DISTINCT instrument_id FROM rl_policies ORDER BY instrument_id"
        )
        return [row["instrument_id"] for row in rows]

    # ──────────────────────────── Cleanup ────────────────────────────

    async def cleanup(
        self,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> list[str]:
        """자동 정리를 실행한다.

        정리 규칙:
        - 미승인 정책: CLEANUP_UNAPPROVED_DAYS 경과 시 삭제
        - 승인 정책: 종목당 CLEANUP_MAX_APPROVED_PER_TICKER 개 초과 시 오래된 것부터 삭제
        - 활성 정책: 삭제 불가

        Returns:
            삭제된 policy_id 목록
        """
        current_time = now or datetime.now(timezone.utc)
        removed: list[str] = []

        # 1. 미승인 + 비활성 + 30일 경과 정책 삭제
        cutoff = current_time.timestamp() - CLEANUP_UNAPPROVED_DAYS * 86400
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)

        unapproved_rows = await fetch(
            """
            SELECT policy_id, file_path
            FROM rl_policies
            WHERE approved = false
              AND is_active = false
              AND created_at < $1
            ORDER BY created_at ASC
            """,
            cutoff_dt,
        )

        for row in unapproved_rows:
            pid = row["policy_id"]
            if not dry_run:
                self._delete_policy_file_by_path(row["file_path"])
                await execute("DELETE FROM rl_policies WHERE policy_id = $1", pid)
            removed.append(pid)
            logger.info("정리 대상 (미승인 30일 초과): %s", pid)

        # 2. 승인 정책: 종목당 MAX_APPROVED_PER_TICKER 초과분 삭제
        tickers_with_excess = await fetch(
            """
            SELECT instrument_id, count(*) as cnt
            FROM rl_policies
            WHERE approved = true AND is_active = false
            GROUP BY instrument_id
            HAVING count(*) > $1
            """,
            CLEANUP_MAX_APPROVED_PER_TICKER,
        )

        for ticker_row in tickers_with_excess:
            tid = ticker_row["instrument_id"]
            # 오래된 것부터 삭제 대상 선정 (최신 N개 보존)
            excess_rows = await fetch(
                """
                SELECT policy_id, file_path
                FROM rl_policies
                WHERE instrument_id = $1
                  AND approved = true
                  AND is_active = false
                ORDER BY created_at DESC
                OFFSET $2
                """,
                tid,
                CLEANUP_MAX_APPROVED_PER_TICKER,
            )
            for row in excess_rows:
                pid = row["policy_id"]
                if not dry_run:
                    self._delete_policy_file_by_path(row["file_path"])
                    await execute("DELETE FROM rl_policies WHERE policy_id = $1", pid)
                removed.append(pid)
                logger.info("정리 대상 (승인 초과): %s", pid)

        return removed

    # ──────────────────────────── Internal helpers ────────────────────────────

    async def _swap_active(self, ticker: str, policy_id: str) -> None:
        """트랜잭션으로 활성 정책을 교체한다."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE rl_policies SET is_active = false "
                    "WHERE instrument_id = $1 AND is_active = true",
                    ticker,
                )
                await conn.execute(
                    "UPDATE rl_policies SET is_active = true WHERE policy_id = $1",
                    policy_id,
                )

    def _load_artifact_from_entry(
        self, entry: PolicyEntry
    ) -> Optional[RLPolicyArtifact]:
        """PolicyEntry 의 file_path 에서 아티팩트를 로드한다."""
        file_path = self.models_dir / entry.file_path
        if not file_path.exists():
            logger.warning("정책 파일 없음: %s", file_path)
            return None
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            return RLPolicyArtifact.from_dict(payload)
        except Exception as exc:
            logger.error("정책 로드 실패 [%s]: %s", entry.policy_id, exc)
            return None

    def _delete_policy_file_by_path(self, relative_path: str) -> None:
        """상대 경로로 정책 파일을 삭제한다."""
        file_path = self.models_dir / relative_path
        if file_path.exists():
            file_path.unlink()
            logger.info("정책 파일 삭제: %s", file_path)
