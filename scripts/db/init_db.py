"""
scripts/db/init_db.py — PostgreSQL 전체 스키마 생성 스크립트

사용법:
    python scripts/db/init_db.py           # 테이블 생성 (없으면 생성)
    python scripts/db/init_db.py --drop    # 기존 테이블 삭제 후 재생성 (주의!)
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
import os

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

# ─────────────────────────────────────────────────────────────────────────────
# DDL 정의 (생성 순서가 중요 — 외래키 의존성 반영)
# ─────────────────────────────────────────────────────────────────────────────

CREATE_TABLES: list[str] = [

    # 1. 사용자 (대시보드 로그인)
    """
    CREATE TABLE IF NOT EXISTS users (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email       TEXT UNIQUE NOT NULL,
        name        TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,

    # 2. 시장 데이터 (OHLCV 일봉 + 틱)
    """
    CREATE TABLE IF NOT EXISTS market_data (
        id              BIGSERIAL PRIMARY KEY,
        ticker          VARCHAR(10) NOT NULL,
        name            TEXT NOT NULL,
        market          VARCHAR(10) NOT NULL CHECK (market IN ('KOSPI', 'KOSDAQ')),
        timestamp_kst   TIMESTAMPTZ NOT NULL,
        interval        VARCHAR(10) NOT NULL DEFAULT 'daily' CHECK (interval IN ('daily', 'tick')),
        open            INTEGER NOT NULL,
        high            INTEGER NOT NULL,
        low             INTEGER NOT NULL,
        close           INTEGER NOT NULL,
        volume          BIGINT NOT NULL,
        change_pct      NUMERIC(6, 3),
        market_cap      BIGINT,
        foreigner_ratio NUMERIC(5, 2),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (ticker, timestamp_kst, interval)
    );
    CREATE INDEX IF NOT EXISTS idx_market_data_ticker_ts
        ON market_data (ticker, timestamp_kst DESC);
    CREATE INDEX IF NOT EXISTS idx_market_data_ts
        ON market_data (timestamp_kst DESC);
    """,

    # 3. 예측 시그널 (PredictorAgent 출력)
    """
    CREATE TABLE IF NOT EXISTS predictions (
        id                      BIGSERIAL PRIMARY KEY,
        agent_id                VARCHAR(30) NOT NULL,
        llm_model               VARCHAR(50) NOT NULL,
        strategy                CHAR(1) NOT NULL CHECK (strategy IN ('A', 'B')),
        ticker                  VARCHAR(10) NOT NULL,
        signal                  VARCHAR(10) NOT NULL CHECK (signal IN ('BUY', 'SELL', 'HOLD')),
        confidence              NUMERIC(4, 3) CHECK (confidence BETWEEN 0 AND 1),
        target_price            INTEGER,
        stop_loss               INTEGER,
        reasoning_summary       TEXT,
        debate_transcript_id    BIGINT,
        actual_close            INTEGER,
        was_correct             BOOLEAN,
        timestamp_utc           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        trading_date            DATE NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_predictions_trading_date
        ON predictions (trading_date DESC, strategy, agent_id);
    CREATE INDEX IF NOT EXISTS idx_predictions_ticker_date
        ON predictions (ticker, trading_date DESC);
    """,

    # 4. Strategy A 토너먼트 점수
    """
    CREATE TABLE IF NOT EXISTS predictor_tournament_scores (
        id              BIGSERIAL PRIMARY KEY,
        agent_id        VARCHAR(30) NOT NULL,
        llm_model       VARCHAR(50) NOT NULL,
        persona         TEXT NOT NULL,
        trading_date    DATE NOT NULL,
        correct         INTEGER NOT NULL DEFAULT 0,
        total           INTEGER NOT NULL DEFAULT 0,
        rolling_accuracy NUMERIC(5, 4),
        is_current_winner BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (agent_id, trading_date)
    );
    -- 과거 스키마 호환: is_current_winner 컬럼이 없으면 추가
    ALTER TABLE predictor_tournament_scores
        ADD COLUMN IF NOT EXISTS is_current_winner BOOLEAN NOT NULL DEFAULT FALSE;
    CREATE INDEX IF NOT EXISTS idx_tournament_date
        ON predictor_tournament_scores (trading_date DESC, rolling_accuracy DESC);
    """,

    # 5. Strategy B 토론 전문
    """
    CREATE TABLE IF NOT EXISTS debate_transcripts (
        id                  BIGSERIAL PRIMARY KEY,
        trading_date        DATE NOT NULL,
        ticker              VARCHAR(10) NOT NULL,
        rounds              INTEGER NOT NULL DEFAULT 1,
        consensus_reached   BOOLEAN NOT NULL DEFAULT FALSE,
        final_signal        VARCHAR(10) CHECK (final_signal IN ('BUY', 'SELL', 'HOLD')),
        confidence          NUMERIC(4, 3),
        proposer_content    TEXT,
        challenger1_content TEXT,
        challenger2_content TEXT,
        synthesizer_content TEXT,
        no_consensus_reason TEXT,
        duration_seconds    INTEGER,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_debate_date_ticker
        ON debate_transcripts (trading_date DESC, ticker);
    """,

    # 6. 포트폴리오 설정
    """
    CREATE TABLE IF NOT EXISTS portfolio_config (
        id                      SERIAL PRIMARY KEY,
        strategy_blend_ratio    NUMERIC(3, 2) NOT NULL DEFAULT 0.50
                                    CHECK (strategy_blend_ratio BETWEEN 0 AND 1),
        max_position_pct        INTEGER NOT NULL DEFAULT 20
                                    CHECK (max_position_pct BETWEEN 1 AND 100),
        daily_loss_limit_pct    INTEGER NOT NULL DEFAULT 3
                                    CHECK (daily_loss_limit_pct BETWEEN 1 AND 100),
        is_paper_trading        BOOLEAN NOT NULL DEFAULT TRUE,
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    -- 단일 행 보장용 초기값 삽입 (이미 있으면 무시)
    INSERT INTO portfolio_config
        (strategy_blend_ratio, max_position_pct, daily_loss_limit_pct, is_paper_trading)
    VALUES (0.50, 20, 3, TRUE)
    ON CONFLICT DO NOTHING;
    """,

    # 7. 포트폴리오 포지션 (현재 보유)
    """
    CREATE TABLE IF NOT EXISTS portfolio_positions (
        id              BIGSERIAL PRIMARY KEY,
        ticker          VARCHAR(10) NOT NULL UNIQUE,
        name            TEXT NOT NULL,
        quantity        INTEGER NOT NULL CHECK (quantity >= 0),
        avg_price       INTEGER NOT NULL,
        current_price   INTEGER NOT NULL DEFAULT 0,
        is_paper        BOOLEAN NOT NULL DEFAULT TRUE,
        opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_positions_ticker ON portfolio_positions (ticker);
    """,

    # 8. 거래 이력
    """
    CREATE TABLE IF NOT EXISTS trade_history (
        id              BIGSERIAL PRIMARY KEY,
        ticker          VARCHAR(10) NOT NULL,
        name            TEXT NOT NULL,
        side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity        INTEGER NOT NULL CHECK (quantity > 0),
        price           INTEGER NOT NULL,
        amount          BIGINT NOT NULL,          -- price * quantity
        signal_source   VARCHAR(10) CHECK (signal_source IN ('A', 'B', 'BLEND')),
        agent_id        VARCHAR(30),
        kis_order_id    TEXT,
        is_paper        BOOLEAN NOT NULL DEFAULT TRUE,
        circuit_breaker BOOLEAN NOT NULL DEFAULT FALSE,  -- 서킷브레이커 강제 청산 여부
        executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_trade_history_ticker_date
        ON trade_history (ticker, executed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_trade_history_date
        ON trade_history (executed_at DESC);
    """,

    # 9. 에이전트 헬스비트 (7일 롤링)
    """
    CREATE TABLE IF NOT EXISTS agent_heartbeats (
        id          BIGSERIAL PRIMARY KEY,
        agent_id    VARCHAR(30) NOT NULL,
        status      VARCHAR(10) NOT NULL CHECK (status IN ('healthy', 'degraded', 'error', 'dead')),
        last_action TEXT,
        metrics     JSONB,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    -- status 체크 제약을 최신 값(healthy/degraded/error/dead)으로 재적용
    ALTER TABLE agent_heartbeats
        DROP CONSTRAINT IF EXISTS agent_heartbeats_status_check;
    ALTER TABLE agent_heartbeats
        ADD CONSTRAINT agent_heartbeats_status_check
        CHECK (status IN ('healthy', 'degraded', 'error', 'dead'));
    CREATE INDEX IF NOT EXISTS idx_heartbeat_agent_ts
        ON agent_heartbeats (agent_id, recorded_at DESC);
    -- 7일 이상 오래된 헬스비트 자동 정리를 위한 파티셔닝 힌트 (수동 vacuum 가능)
    """,

    # 10. 수집 오류 로그
    """
    CREATE TABLE IF NOT EXISTS collector_errors (
        id          BIGSERIAL PRIMARY KEY,
        source      VARCHAR(30) NOT NULL,  -- 'fdr', 'kis_ws', 'krx'
        ticker      VARCHAR(10),
        error_type  TEXT NOT NULL,
        message     TEXT NOT NULL,
        resolved    BOOLEAN NOT NULL DEFAULT FALSE,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_collector_errors_ts
        ON collector_errors (occurred_at DESC);
    """,

    # 11. 알림 발송 이력
    """
    CREATE TABLE IF NOT EXISTS notification_history (
        id          BIGSERIAL PRIMARY KEY,
        event_type  VARCHAR(30) NOT NULL,
        message     TEXT NOT NULL,
        sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        success     BOOLEAN NOT NULL DEFAULT TRUE,
        error_msg   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_notification_ts
        ON notification_history (sent_at DESC);
    """,
]

DROP_TABLES_SQL = """
DROP TABLE IF EXISTS
    notification_history,
    collector_errors,
    agent_heartbeats,
    trade_history,
    portfolio_positions,
    portfolio_config,
    debate_transcripts,
    predictor_tournament_scores,
    predictions,
    market_data,
    users
CASCADE;
"""


async def create_schema(drop_first: bool = False) -> None:
    """PostgreSQL 스키마를 생성합니다."""
    logger.info("DB 연결 중: %s", DATABASE_URL.split("@")[-1])
    conn: asyncpg.Connection = await asyncpg.connect(DATABASE_URL)

    try:
        if drop_first:
            logger.warning("⚠️  기존 테이블 전체 삭제 중...")
            await conn.execute(DROP_TABLES_SQL)
            logger.info("테이블 삭제 완료")

        # users.id 기본값 gen_random_uuid()를 위해 pgcrypto 확장을 보장합니다.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

        logger.info("테이블 생성 시작...")
        for ddl in CREATE_TABLES:
            # 여러 SQL 문이 하나의 문자열에 있을 수 있으므로 ;로 분리 실행
            statements = [s.strip() for s in ddl.split(";") if s.strip()]
            for stmt in statements:
                # 주석만 있는 조각은 건너뜁니다.
                cleaned_lines = [ln for ln in stmt.splitlines() if not ln.strip().startswith("--")]
                cleaned_stmt = "\n".join(cleaned_lines).strip()
                if not cleaned_stmt:
                    continue
                await conn.execute(cleaned_stmt)

        # 생성된 테이블 목록 확인
        rows = await conn.fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        table_names = [r["tablename"] for r in rows]
        logger.info("✅ 생성된 테이블 (%d개): %s", len(table_names), ", ".join(table_names))

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="PostgreSQL 스키마 초기화 스크립트")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="기존 테이블 삭제 후 재생성 (데이터 전부 삭제됨!)",
    )
    args = parser.parse_args()

    if args.drop:
        confirm = input("⚠️  모든 테이블과 데이터가 삭제됩니다. 계속하시겠습니까? (yes/no): ")
        if confirm.lower() != "yes":
            print("취소되었습니다.")
            sys.exit(0)

    asyncio.run(create_schema(drop_first=args.drop))
    logger.info("🎉 스키마 초기화 완료!")


if __name__ == "__main__":
    main()
