"""
scripts/db/migrate_rl_training.py — rl_training_jobs + rl_experiments 테이블 마이그레이션

기존 DB에 RL 학습 작업 관리 테이블을 추가합니다.
이미 존재하면 스킵합니다 (IF NOT EXISTS).

사용법:
    python scripts/db/migrate_rl_training.py
"""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://alpha:alpha@localhost:5432/alpha_db")

MIGRATION_SQL = [
    """
    CREATE TABLE IF NOT EXISTS rl_training_jobs (
        job_id          VARCHAR(40)   PRIMARY KEY,
        instrument_id   VARCHAR(20)   NOT NULL REFERENCES instruments(instrument_id),
        status          VARCHAR(10)   NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
        policy_family   VARCHAR(30)   NOT NULL DEFAULT 'tabular_q_v2',
        dataset_days    INT           NOT NULL DEFAULT 720,
        result_policy_id VARCHAR(80)  REFERENCES rl_policies(policy_id),
        error_message   TEXT,
        created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
        started_at      TIMESTAMPTZ,
        completed_at    TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_training_jobs_instrument ON rl_training_jobs(instrument_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_training_jobs_status ON rl_training_jobs(status)",
    """
    CREATE TABLE IF NOT EXISTS rl_experiments (
        run_id              VARCHAR(60)   PRIMARY KEY,
        job_id              VARCHAR(40)   REFERENCES rl_training_jobs(job_id),
        instrument_id       VARCHAR(20)   NOT NULL REFERENCES instruments(instrument_id),
        policy_id           VARCHAR(80)   REFERENCES rl_policies(policy_id),
        profile_id          VARCHAR(30),
        algorithm           VARCHAR(30),
        return_pct          REAL,
        baseline_return_pct REAL,
        excess_return_pct   REAL,
        max_drawdown_pct    REAL,
        trades              INT,
        win_rate            REAL,
        holdout_steps       INT,
        walk_forward_passed BOOLEAN       DEFAULT false,
        walk_forward_consistency REAL,
        approved            BOOLEAN       DEFAULT false,
        deployed            BOOLEAN       DEFAULT false,
        created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_experiments_instrument ON rl_experiments(instrument_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_experiments_job ON rl_experiments(job_id)",
]


async def main() -> None:
    print(f"Connecting to {DATABASE_URL.split('@')[-1]} ...")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        for sql in MIGRATION_SQL:
            await conn.execute(sql.strip())
            first_line = sql.strip().split("\n")[0][:60]
            print(f"  OK: {first_line}...")
        print("Migration complete: rl_training_jobs + rl_experiments")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
