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

    # 6. 모델/페르소나 역할 설정
    """
    CREATE TABLE IF NOT EXISTS model_role_configs (
        id              BIGSERIAL PRIMARY KEY,
        config_key      VARCHAR(60) NOT NULL UNIQUE,
        strategy_code   CHAR(1) NOT NULL CHECK (strategy_code IN ('A', 'B')),
        role            VARCHAR(30) NOT NULL,
        role_label      TEXT NOT NULL,
        agent_id        VARCHAR(50) NOT NULL,
        llm_model       VARCHAR(80) NOT NULL,
        persona         TEXT NOT NULL,
        execution_order INTEGER NOT NULL DEFAULT 1 CHECK (execution_order >= 1),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS config_key VARCHAR(60);
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS strategy_code CHAR(1);
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS role VARCHAR(30);
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS role_label TEXT;
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS agent_id VARCHAR(50);
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS llm_model VARCHAR(80);
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS persona TEXT;
    ALTER TABLE model_role_configs
        ADD COLUMN IF NOT EXISTS execution_order INTEGER DEFAULT 1;
    ALTER TABLE model_role_configs
        DROP CONSTRAINT IF EXISTS model_role_configs_strategy_code_check;
    ALTER TABLE model_role_configs
        ADD CONSTRAINT model_role_configs_strategy_code_check
        CHECK (strategy_code IN ('A', 'B'));
    CREATE INDEX IF NOT EXISTS idx_model_role_configs_strategy_order
        ON model_role_configs (strategy_code, execution_order, updated_at DESC);
    INSERT INTO model_role_configs (
        config_key, strategy_code, role, role_label, agent_id,
        llm_model, persona, execution_order
    ) VALUES
        ('strategy_a_predictor_1', 'A', 'predictor', 'Predictor 1', 'predictor_1', 'claude-3-5-sonnet-latest', '가치 투자형', 1),
        ('strategy_a_predictor_2', 'A', 'predictor', 'Predictor 2', 'predictor_2', 'claude-3-5-sonnet-latest', '기술적 분석형', 2),
        ('strategy_a_predictor_3', 'A', 'predictor', 'Predictor 3', 'predictor_3', 'gpt-4o-mini', '모멘텀형', 3),
        ('strategy_a_predictor_4', 'A', 'predictor', 'Predictor 4', 'predictor_4', 'gpt-4o-mini', '역추세형', 4),
        ('strategy_a_predictor_5', 'A', 'predictor', 'Predictor 5', 'predictor_5', 'gemini-1.5-pro', '거시경제형', 5),
        ('strategy_b_proposer', 'B', 'proposer', 'Proposer', 'consensus_proposer', 'claude-3-5-sonnet-latest', '핵심 매매 가설을 세우는 수석 분석가', 1),
        ('strategy_b_challenger_1', 'B', 'challenger', 'Challenger 1', 'consensus_challenger_1', 'gpt-4o-mini', '가설의 약점을 빠르게 파고드는 반론가', 2),
        ('strategy_b_challenger_2', 'B', 'challenger', 'Challenger 2', 'consensus_challenger_2', 'gemini-1.5-pro', '거시 변수와 대안을 점검하는 반론가', 3),
        ('strategy_b_synthesizer', 'B', 'synthesizer', 'Synthesizer', 'consensus_synthesizer', 'claude-3-5-sonnet-latest', '토론을 종합해 최종 결론을 내리는 조정자', 4)
    ON CONFLICT (config_key) DO NOTHING;
    """,

    # 7. 포트폴리오 설정
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
        enable_paper_trading    BOOLEAN NOT NULL DEFAULT TRUE,
        enable_real_trading     BOOLEAN NOT NULL DEFAULT FALSE,
        primary_account_scope   VARCHAR(10) NOT NULL DEFAULT 'paper',
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE portfolio_config
        ADD COLUMN IF NOT EXISTS enable_paper_trading BOOLEAN;
    ALTER TABLE portfolio_config
        ADD COLUMN IF NOT EXISTS enable_real_trading BOOLEAN;
    ALTER TABLE portfolio_config
        ADD COLUMN IF NOT EXISTS primary_account_scope VARCHAR(10);
    UPDATE portfolio_config
       SET enable_paper_trading = COALESCE(enable_paper_trading, is_paper_trading, TRUE),
           enable_real_trading = COALESCE(enable_real_trading, NOT COALESCE(is_paper_trading, TRUE)),
           primary_account_scope = COALESCE(
               primary_account_scope,
               CASE WHEN COALESCE(is_paper_trading, TRUE) THEN 'paper' ELSE 'real' END
           );
    ALTER TABLE portfolio_config
        ALTER COLUMN enable_paper_trading SET DEFAULT TRUE;
    ALTER TABLE portfolio_config
        ALTER COLUMN enable_real_trading SET DEFAULT FALSE;
    ALTER TABLE portfolio_config
        ALTER COLUMN primary_account_scope SET DEFAULT 'paper';
    ALTER TABLE portfolio_config
        ALTER COLUMN enable_paper_trading SET NOT NULL;
    ALTER TABLE portfolio_config
        ALTER COLUMN enable_real_trading SET NOT NULL;
    ALTER TABLE portfolio_config
        ALTER COLUMN primary_account_scope SET NOT NULL;
    ALTER TABLE portfolio_config
        DROP CONSTRAINT IF EXISTS portfolio_config_primary_account_scope_check;
    ALTER TABLE portfolio_config
        ADD CONSTRAINT portfolio_config_primary_account_scope_check
        CHECK (primary_account_scope IN ('paper', 'real'));
    -- 단일 행 보장용 초기값 삽입 (이미 있으면 무시)
    INSERT INTO portfolio_config
        (
            strategy_blend_ratio, max_position_pct, daily_loss_limit_pct,
            is_paper_trading, enable_paper_trading, enable_real_trading, primary_account_scope
        )
    VALUES (0.50, 20, 3, TRUE, TRUE, FALSE, 'paper')
    ON CONFLICT DO NOTHING;
    """,

    # 8. 계좌 상태 (paper/real 공통 메타데이터)
    """
    CREATE TABLE IF NOT EXISTS trading_accounts (
        account_scope   VARCHAR(10) PRIMARY KEY,
        broker_name     TEXT NOT NULL,
        account_label   TEXT NOT NULL,
        base_currency   VARCHAR(10) NOT NULL DEFAULT 'KRW',
        seed_capital    BIGINT NOT NULL DEFAULT 10000000 CHECK (seed_capital >= 0),
        cash_balance    BIGINT NOT NULL DEFAULT 10000000 CHECK (cash_balance >= 0),
        buying_power    BIGINT NOT NULL DEFAULT 10000000 CHECK (buying_power >= 0),
        total_equity    BIGINT NOT NULL DEFAULT 10000000 CHECK (total_equity >= 0),
        is_active       BOOLEAN NOT NULL DEFAULT FALSE,
        last_synced_at  TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE trading_accounts
        DROP CONSTRAINT IF EXISTS trading_accounts_account_scope_check;
    ALTER TABLE trading_accounts
        ADD CONSTRAINT trading_accounts_account_scope_check
        CHECK (account_scope IN ('paper', 'real'));
    INSERT INTO trading_accounts (
        account_scope, broker_name, account_label, base_currency,
        seed_capital, cash_balance, buying_power, total_equity, is_active
    )
    VALUES
        ('paper', '한국투자증권 KIS', 'KIS 모의투자 계좌', 'KRW', 10000000, 10000000, 10000000, 10000000, TRUE),
        ('real', '한국투자증권 KIS', 'KIS 실거래 계좌', 'KRW', 0, 0, 0, 0, FALSE)
    ON CONFLICT (account_scope) DO NOTHING;
    """,

    # 9. 포트폴리오 포지션 (현재 보유)
    """
    CREATE TABLE IF NOT EXISTS portfolio_positions (
        id              BIGSERIAL PRIMARY KEY,
        ticker          VARCHAR(10) NOT NULL,
        name            TEXT NOT NULL,
        quantity        INTEGER NOT NULL CHECK (quantity >= 0),
        avg_price       INTEGER NOT NULL,
        current_price   INTEGER NOT NULL DEFAULT 0,
        is_paper        BOOLEAN NOT NULL DEFAULT TRUE,
        account_scope   VARCHAR(10) NOT NULL DEFAULT 'paper',
        opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE portfolio_positions
        ADD COLUMN IF NOT EXISTS account_scope VARCHAR(10);
    UPDATE portfolio_positions
       SET account_scope = CASE WHEN is_paper THEN 'paper' ELSE 'real' END
     WHERE account_scope IS NULL;
    ALTER TABLE portfolio_positions
        ALTER COLUMN account_scope SET DEFAULT 'paper';
    ALTER TABLE portfolio_positions
        DROP CONSTRAINT IF EXISTS portfolio_positions_account_scope_check;
    ALTER TABLE portfolio_positions
        ADD CONSTRAINT portfolio_positions_account_scope_check
        CHECK (account_scope IN ('paper', 'real'));
    ALTER TABLE portfolio_positions
        ALTER COLUMN account_scope SET NOT NULL;
    ALTER TABLE portfolio_positions
        DROP CONSTRAINT IF EXISTS portfolio_positions_ticker_key;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_ticker_scope
        ON portfolio_positions (ticker, account_scope);
    CREATE INDEX IF NOT EXISTS idx_positions_scope
        ON portfolio_positions (account_scope, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_positions_ticker
        ON portfolio_positions (ticker);
    """,

    # 9. 거래 이력
    """
    CREATE TABLE IF NOT EXISTS trade_history (
        id              BIGSERIAL PRIMARY KEY,
        ticker          VARCHAR(10) NOT NULL,
        name            TEXT NOT NULL,
        side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity        INTEGER NOT NULL CHECK (quantity > 0),
        price           INTEGER NOT NULL,
        amount          BIGINT NOT NULL,          -- price * quantity
        signal_source   VARCHAR(10) CHECK (signal_source IN ('A', 'B', 'BLEND', 'RL')),
        agent_id        VARCHAR(30),
        kis_order_id    TEXT,
        is_paper        BOOLEAN NOT NULL DEFAULT TRUE,
        account_scope   VARCHAR(10) NOT NULL DEFAULT 'paper',
        circuit_breaker BOOLEAN NOT NULL DEFAULT FALSE,  -- 서킷브레이커 강제 청산 여부
        executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE trade_history
        ADD COLUMN IF NOT EXISTS account_scope VARCHAR(10);
    UPDATE trade_history
       SET account_scope = CASE WHEN is_paper THEN 'paper' ELSE 'real' END
     WHERE account_scope IS NULL;
    ALTER TABLE trade_history
        ALTER COLUMN account_scope SET DEFAULT 'paper';
    ALTER TABLE trade_history
        DROP CONSTRAINT IF EXISTS trade_history_account_scope_check;
    ALTER TABLE trade_history
        ADD CONSTRAINT trade_history_account_scope_check
        CHECK (account_scope IN ('paper', 'real'));
    ALTER TABLE trade_history
        DROP CONSTRAINT IF EXISTS trade_history_signal_source_check;
    ALTER TABLE trade_history
        ADD CONSTRAINT trade_history_signal_source_check
        CHECK (signal_source IN ('A', 'B', 'BLEND', 'RL'));
    ALTER TABLE trade_history
        ALTER COLUMN account_scope SET NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_trade_history_ticker_date
        ON trade_history (ticker, executed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_trade_history_date
        ON trade_history (executed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_trade_history_scope_date
        ON trade_history (account_scope, executed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_trade_history_scope_ticker_date
        ON trade_history (account_scope, ticker, executed_at DESC);
    """,

    # 10. 브로커 주문 이력 (internal paper / KIS mock 공용)
    """
    CREATE TABLE IF NOT EXISTS broker_orders (
        id                  BIGSERIAL PRIMARY KEY,
        client_order_id     TEXT NOT NULL UNIQUE,
        account_scope       VARCHAR(10) NOT NULL DEFAULT 'paper',
        broker_name         TEXT NOT NULL,
        ticker              VARCHAR(10) NOT NULL,
        name                TEXT NOT NULL,
        side                VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        order_type          VARCHAR(10) NOT NULL DEFAULT 'MARKET' CHECK (order_type IN ('MARKET', 'LIMIT')),
        requested_quantity  INTEGER NOT NULL CHECK (requested_quantity > 0),
        requested_price     INTEGER NOT NULL CHECK (requested_price >= 0),
        filled_quantity     INTEGER NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
        avg_fill_price      INTEGER,
        status              VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                                CHECK (status IN ('PENDING', 'FILLED', 'REJECTED', 'CANCELLED')),
        signal_source       VARCHAR(10) CHECK (signal_source IN ('A', 'B', 'BLEND', 'RL')),
        agent_id            VARCHAR(30),
        broker_order_id     TEXT,
        rejection_reason    TEXT,
        requested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        filled_at           TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE broker_orders
        DROP CONSTRAINT IF EXISTS broker_orders_account_scope_check;
    ALTER TABLE broker_orders
        ADD CONSTRAINT broker_orders_account_scope_check
        CHECK (account_scope IN ('paper', 'real'));
    ALTER TABLE broker_orders
        DROP CONSTRAINT IF EXISTS broker_orders_signal_source_check;
    ALTER TABLE broker_orders
        ADD CONSTRAINT broker_orders_signal_source_check
        CHECK (signal_source IN ('A', 'B', 'BLEND', 'RL'));
    CREATE INDEX IF NOT EXISTS idx_broker_orders_scope_ts
        ON broker_orders (account_scope, requested_at DESC);
    CREATE INDEX IF NOT EXISTS idx_broker_orders_scope_status_ts
        ON broker_orders (account_scope, status, requested_at DESC);
    """,

    # 11. 계좌 스냅샷
    """
    CREATE TABLE IF NOT EXISTS account_snapshots (
        id                      BIGSERIAL PRIMARY KEY,
        account_scope           VARCHAR(10) NOT NULL DEFAULT 'paper',
        cash_balance            BIGINT NOT NULL DEFAULT 0,
        buying_power            BIGINT NOT NULL DEFAULT 0,
        position_market_value   BIGINT NOT NULL DEFAULT 0,
        total_equity            BIGINT NOT NULL DEFAULT 0,
        realized_pnl            BIGINT NOT NULL DEFAULT 0,
        unrealized_pnl          BIGINT NOT NULL DEFAULT 0,
        position_count          INTEGER NOT NULL DEFAULT 0,
        snapshot_source         VARCHAR(20) NOT NULL DEFAULT 'broker',
        snapshot_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE account_snapshots
        DROP CONSTRAINT IF EXISTS account_snapshots_account_scope_check;
    ALTER TABLE account_snapshots
        ADD CONSTRAINT account_snapshots_account_scope_check
        CHECK (account_scope IN ('paper', 'real'));
    CREATE INDEX IF NOT EXISTS idx_account_snapshots_scope_ts
        ON account_snapshots (account_scope, snapshot_at DESC);
    """,

    # 12. 에이전트 헬스비트 (7일 롤링)
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

    # 13. 수집 오류 로그
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

    # 14. 알림 발송 이력
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

    # 15. 실거래 전환 감사 로그
    """
    CREATE TABLE IF NOT EXISTS real_trading_audit (
        id                      BIGSERIAL PRIMARY KEY,
        requested_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        requested_by_email      TEXT,
        requested_by_user_id    TEXT,
        requested_mode_is_paper BOOLEAN NOT NULL,
        requested_paper_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        requested_real_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
        requested_primary_account_scope VARCHAR(10) NOT NULL DEFAULT 'paper',
        confirmation_code_ok    BOOLEAN NOT NULL,
        readiness_passed        BOOLEAN NOT NULL,
        readiness_summary       JSONB,
        applied                 BOOLEAN NOT NULL DEFAULT FALSE,
        message                 TEXT
    );
    ALTER TABLE real_trading_audit
        ADD COLUMN IF NOT EXISTS requested_paper_enabled BOOLEAN;
    ALTER TABLE real_trading_audit
        ADD COLUMN IF NOT EXISTS requested_real_enabled BOOLEAN;
    ALTER TABLE real_trading_audit
        ADD COLUMN IF NOT EXISTS requested_primary_account_scope VARCHAR(10);
    UPDATE real_trading_audit
       SET requested_paper_enabled = COALESCE(requested_paper_enabled, requested_mode_is_paper),
           requested_real_enabled = COALESCE(requested_real_enabled, NOT requested_mode_is_paper),
           requested_primary_account_scope = COALESCE(
               requested_primary_account_scope,
               CASE WHEN requested_mode_is_paper THEN 'paper' ELSE 'real' END
           );
    ALTER TABLE real_trading_audit
        ALTER COLUMN requested_paper_enabled SET DEFAULT TRUE;
    ALTER TABLE real_trading_audit
        ALTER COLUMN requested_real_enabled SET DEFAULT FALSE;
    ALTER TABLE real_trading_audit
        ALTER COLUMN requested_primary_account_scope SET DEFAULT 'paper';
    ALTER TABLE real_trading_audit
        ALTER COLUMN requested_paper_enabled SET NOT NULL;
    ALTER TABLE real_trading_audit
        ALTER COLUMN requested_real_enabled SET NOT NULL;
    ALTER TABLE real_trading_audit
        ALTER COLUMN requested_primary_account_scope SET NOT NULL;
    ALTER TABLE real_trading_audit
        DROP CONSTRAINT IF EXISTS real_trading_audit_primary_scope_check;
    ALTER TABLE real_trading_audit
        ADD CONSTRAINT real_trading_audit_primary_scope_check
        CHECK (requested_primary_account_scope IN ('paper', 'real'));
    CREATE INDEX IF NOT EXISTS idx_real_trading_audit_ts
        ON real_trading_audit (requested_at DESC);
    """,

    # 16. 운영 감사 로그 (보안/리스크 규칙 검증)
    """
    CREATE TABLE IF NOT EXISTS operational_audits (
        id          BIGSERIAL PRIMARY KEY,
        audit_type  VARCHAR(30) NOT NULL CHECK (audit_type IN ('security', 'risk_rules', 'paper_reconciliation')),
        passed      BOOLEAN NOT NULL,
        summary     TEXT NOT NULL,
        details     JSONB,
        executed_by TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE operational_audits
        DROP CONSTRAINT IF EXISTS operational_audits_audit_type_check;
    ALTER TABLE operational_audits
        ADD CONSTRAINT operational_audits_audit_type_check
        CHECK (audit_type IN ('security', 'risk_rules', 'paper_reconciliation', 'real_reconciliation'));
    CREATE INDEX IF NOT EXISTS idx_operational_audits_type_ts
        ON operational_audits (audit_type, created_at DESC);
    """,

    # 17. 페이퍼 트레이딩 장기 검증 이력
    """
    CREATE TABLE IF NOT EXISTS paper_trading_runs (
        id                      BIGSERIAL PRIMARY KEY,
        scenario                VARCHAR(30) NOT NULL, -- baseline, high_volatility, load
        simulated_days          INTEGER NOT NULL,
        start_date              DATE NOT NULL,
        end_date                DATE NOT NULL,
        trade_count             INTEGER NOT NULL DEFAULT 0,
        return_pct              NUMERIC(7, 3) NOT NULL DEFAULT 0,
        benchmark_return_pct    NUMERIC(7, 3),
        max_drawdown_pct        NUMERIC(7, 3),
        sharpe_ratio            NUMERIC(10, 4),
        passed                  BOOLEAN NOT NULL DEFAULT FALSE,
        summary                 TEXT NOT NULL,
        report                  JSONB,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_paper_trading_runs_ts
        ON paper_trading_runs (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_paper_trading_runs_scenario
        ON paper_trading_runs (scenario, created_at DESC);
    """,
]

DROP_TABLES_SQL = """
DROP TABLE IF EXISTS
    paper_trading_runs,
    operational_audits,
    real_trading_audit,
    notification_history,
    collector_errors,
    agent_heartbeats,
    account_snapshots,
    broker_orders,
    trade_history,
    portfolio_positions,
    trading_accounts,
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
