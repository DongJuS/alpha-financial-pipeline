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
from typing import Optional, Tuple

import asyncpg
from dotenv import load_dotenv
import os

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.utils.auth import hash_password

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

    # 2-b. markets (신규 시장 메타 테이블)
    """
    CREATE TABLE IF NOT EXISTS markets (
        market_id      VARCHAR(10) PRIMARY KEY,
        name           TEXT        NOT NULL,
        country        VARCHAR(3)  NOT NULL,
        timezone       VARCHAR(30) NOT NULL,
        currency       VARCHAR(5)  NOT NULL,
        open_time      TIME,
        close_time     TIME,
        data_source    VARCHAR(20) NOT NULL,
        is_active      BOOLEAN DEFAULT true,
        created_at     TIMESTAMPTZ DEFAULT now()
    );
    INSERT INTO markets (market_id, name, country, timezone, currency, open_time, close_time, data_source)
    VALUES
        ('KOSPI',  '코스피',           'KR', 'Asia/Seoul',       'KRW', '09:00', '15:30', 'fdr'),
        ('KOSDAQ', '코스닥',           'KR', 'Asia/Seoul',       'KRW', '09:00', '15:30', 'fdr'),
        ('NYSE',   '뉴욕증권거래소',    'US', 'America/New_York', 'USD', '09:30', '16:00', 'fdr'),
        ('NASDAQ', '나스닥',           'US', 'America/New_York', 'USD', '09:30', '16:00', 'fdr')
    ON CONFLICT (market_id) DO NOTHING;
    """,

    # 2-c. instruments (신규 종목 마스터 테이블)
    """
    CREATE TABLE IF NOT EXISTS instruments (
        instrument_id  VARCHAR(20)  PRIMARY KEY,
        raw_code       VARCHAR(15)  NOT NULL,
        name           TEXT         NOT NULL,
        name_en        TEXT,
        market_id      VARCHAR(10)  NOT NULL REFERENCES markets(market_id),
        sector         TEXT,
        industry       TEXT,
        asset_type     VARCHAR(10)  NOT NULL DEFAULT 'stock',
        isin           VARCHAR(15),
        listed_at      DATE,
        delisted_at    DATE,
        market_cap     BIGINT,
        total_shares   BIGINT,
        is_active      BOOLEAN      NOT NULL DEFAULT true,
        created_at     TIMESTAMPTZ  DEFAULT now(),
        updated_at     TIMESTAMPTZ  DEFAULT now(),

        CONSTRAINT uq_instruments_market_code UNIQUE (market_id, raw_code)
    );
    CREATE INDEX IF NOT EXISTS idx_instruments_market    ON instruments(market_id, is_active);
    CREATE INDEX IF NOT EXISTS idx_instruments_sector    ON instruments(market_id, sector) WHERE is_active = true;
    CREATE INDEX IF NOT EXISTS idx_instruments_asset     ON instruments(asset_type, is_active);
    CREATE INDEX IF NOT EXISTS idx_instruments_raw_code  ON instruments(raw_code);
    """,

    # 2-d. ohlcv_daily (신규 일봉 파티셔닝 테이블)
    """
    CREATE TABLE IF NOT EXISTS ohlcv_daily (
        instrument_id  VARCHAR(20)   NOT NULL,
        traded_at      DATE          NOT NULL,
        open           NUMERIC(15,4) NOT NULL,
        high           NUMERIC(15,4) NOT NULL,
        low            NUMERIC(15,4) NOT NULL,
        close          NUMERIC(15,4) NOT NULL,
        volume         BIGINT        NOT NULL,
        amount         BIGINT,
        change_pct     NUMERIC(8,4),
        market_cap     BIGINT,
        turnover_ratio NUMERIC(8,4),
        foreign_ratio  NUMERIC(5,2),
        adj_close      NUMERIC(15,4),

        PRIMARY KEY (instrument_id, traded_at)
    ) PARTITION BY RANGE (traded_at);
    CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_instrument
        ON ohlcv_daily (instrument_id, traded_at DESC);
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
    -- N-way 블렌딩 확장: strategy CHECK에 'R'(RL), 'S', 'L' 추가
    ALTER TABLE predictions
        DROP CONSTRAINT IF EXISTS predictions_strategy_check;
    ALTER TABLE predictions
        ADD CONSTRAINT predictions_strategy_check
        CHECK (strategy IN ('A', 'B', 'R', 'S', 'L'));
    -- shadow gate: 미승인 전략은 shadow 로깅만
    ALTER TABLE predictions
        ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN DEFAULT FALSE;
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
        CHECK (primary_account_scope IN ('paper', 'real', 'virtual'));
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
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    ALTER TABLE trading_accounts
        ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
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
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    ALTER TABLE portfolio_positions
        ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE portfolio_positions
        ALTER COLUMN account_scope SET NOT NULL;
    ALTER TABLE portfolio_positions
        DROP CONSTRAINT IF EXISTS portfolio_positions_ticker_key;
    DROP INDEX IF EXISTS idx_positions_ticker_scope;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_ticker_scope_strategy
        ON portfolio_positions (ticker, account_scope, COALESCE(strategy_id, ''));
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
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    ALTER TABLE trade_history
        ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE trade_history
        DROP CONSTRAINT IF EXISTS trade_history_signal_source_check;
    ALTER TABLE trade_history
        ADD CONSTRAINT trade_history_signal_source_check
        CHECK (signal_source IN ('A', 'B', 'BLEND', 'RL', 'S', 'L', 'EXIT', 'VIRTUAL'));
    -- N-way 블렌딩 메타데이터 (참여 전략/가중치 기록)
    ALTER TABLE trade_history
        ADD COLUMN IF NOT EXISTS blend_meta JSONB;
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
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    ALTER TABLE broker_orders
        ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE broker_orders
        DROP CONSTRAINT IF EXISTS broker_orders_signal_source_check;
    ALTER TABLE broker_orders
        ADD CONSTRAINT broker_orders_signal_source_check
        CHECK (signal_source IN ('A', 'B', 'BLEND', 'RL', 'S', 'L', 'EXIT', 'VIRTUAL'));
    -- N-way 블렌딩 메타데이터
    ALTER TABLE broker_orders
        ADD COLUMN IF NOT EXISTS blend_meta JSONB;
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
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    ALTER TABLE account_snapshots
        ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    CREATE INDEX IF NOT EXISTS idx_account_snapshots_scope_ts
        ON account_snapshots (account_scope, snapshot_at DESC);
    """,

    # 11-b. 에이전트 레지스트리 (중앙 관리)
    """
    CREATE TABLE IF NOT EXISTS agent_registry (
        agent_id        VARCHAR(30) PRIMARY KEY,
        display_name    TEXT NOT NULL,
        agent_type      VARCHAR(20) NOT NULL CHECK (agent_type IN (
            'orchestrator', 'predictor', 'collector', 'portfolio_manager',
            'notifier', 'execution', 'rl', 'research', 'gen'
        )),
        description     TEXT,
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        is_on_demand    BOOLEAN NOT NULL DEFAULT FALSE,
        default_config  JSONB DEFAULT '{}',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_agent_registry_type
        ON agent_registry (agent_type, is_active);

    -- 기본 에이전트 시드 데이터
    INSERT INTO agent_registry (agent_id, display_name, agent_type, description, is_on_demand)
    VALUES
        ('collector_agent',           '데이터 수집기',       'collector',          '일봉/틱 OHLCV 수집',                    FALSE),
        ('predictor_1',               '예측기 #1',          'predictor',          'LLM 기반 단기 예측 (temp=0.3)',            FALSE),
        ('predictor_2',               '예측기 #2',          'predictor',          'LLM 기반 단기 예측 (temp=0.5)',            FALSE),
        ('predictor_3',               '예측기 #3',          'predictor',          'LLM 기반 단기 예측 (temp=0.7)',            FALSE),
        ('predictor_4',               '예측기 #4',          'predictor',          'LLM 기반 단기 예측 (temp=0.6)',            FALSE),
        ('predictor_5',               '예측기 #5',          'predictor',          'LLM 기반 단기 예측 (temp=0.4)',            FALSE),
        ('portfolio_manager_agent',   '포트폴리오 매니저',   'portfolio_manager',  '블렌딩 신호 기반 매매 실행',                FALSE),
        ('notifier_agent',            '알림 에이전트',       'notifier',           '사이클 결과 알림 및 일일 리포트',            FALSE),
        ('orchestrator_agent',        '오케스트레이터',      'orchestrator',       '전략 병렬 실행 → 블렌딩 → 주문 사이클',      FALSE),
        ('fast_flow_agent',           '빠른 실행 에이전트',  'execution',          '빠른 흐름 설계 (on-demand)',               TRUE),
        ('slow_meticulous_agent',     '꼼꼼한 검증 에이전트','execution',          '상세 검증 계획 (on-demand)',               TRUE)
    ON CONFLICT (agent_id) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        agent_type   = EXCLUDED.agent_type,
        description  = EXCLUDED.description,
        is_on_demand = EXCLUDED.is_on_demand,
        updated_at   = NOW();
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

    # 18. 검색 쿼리 (SearXNG pipeline)
    """
    CREATE TABLE IF NOT EXISTS search_queries (
        id SERIAL PRIMARY KEY,
        query TEXT NOT NULL,
        ticker VARCHAR(10),
        category TEXT DEFAULT 'general',
        max_results INTEGER DEFAULT 10,
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
        result_count INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_search_queries_ticker
        ON search_queries (ticker, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_search_queries_status
        ON search_queries (status, created_at DESC);
    """,

    # 19. 검색 결과
    """
    CREATE TABLE IF NOT EXISTS search_results (
        id SERIAL PRIMARY KEY,
        query_id INT REFERENCES search_queries(id),
        url TEXT NOT NULL,
        canonical_url TEXT,
        title TEXT,
        snippet TEXT,
        engine TEXT,
        rank INT,
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'fetched', 'failed')),
        fetched_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_search_results_query
        ON search_results (query_id, rank);
    CREATE INDEX IF NOT EXISTS idx_search_results_url
        ON search_results (canonical_url);
    """,

    # 20. 페이지 추출 결과
    """
    CREATE TABLE IF NOT EXISTS page_extractions (
        id SERIAL PRIMARY KEY,
        search_result_id INT REFERENCES search_results(id),
        raw_content_hash TEXT,
        raw_content_path TEXT,
        structured_data JSONB,
        extraction_schema TEXT,
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'extracted', 'partial', 'failed')),
        error_message TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_page_extractions_result
        ON page_extractions (search_result_id);
    CREATE INDEX IF NOT EXISTS idx_page_extractions_status
        ON page_extractions (status);
    """,

    # 21. 리서치 결과 (Claude 추론)
    """
    CREATE TABLE IF NOT EXISTS research_outputs (
        id SERIAL PRIMARY KEY,
        query_id INT REFERENCES search_queries(id),
        ticker VARCHAR(10),
        extraction_ids INTEGER[],
        output_type TEXT DEFAULT 'research_contract',
        output_data JSONB NOT NULL,
        model_used TEXT,
        status TEXT DEFAULT 'completed' CHECK (status IN ('completed', 'partial', 'failed')),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_research_outputs_ticker
        ON research_outputs (ticker, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_research_outputs_query
        ON research_outputs (query_id);
    """,

    # ── 마켓플레이스 확장 테이블 ────────────────────────────────────────────────

    # 22. 종목 마스터 (KRX 전종목 + ETF/ETN)
    """
    CREATE TABLE IF NOT EXISTS stock_master (
        ticker          VARCHAR(10) PRIMARY KEY,
        name            TEXT NOT NULL,
        market          VARCHAR(10) NOT NULL CHECK (market IN ('KOSPI', 'KOSDAQ', 'KONEX')),
        sector          VARCHAR(80),
        industry        VARCHAR(120),
        market_cap      BIGINT,
        listing_date    DATE,
        is_etf          BOOLEAN NOT NULL DEFAULT FALSE,
        is_etn          BOOLEAN NOT NULL DEFAULT FALSE,
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        tier            VARCHAR(10) DEFAULT 'universe' CHECK (tier IN ('core', 'extended', 'universe')),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_stock_master_market
        ON stock_master (market, is_active);
    CREATE INDEX IF NOT EXISTS idx_stock_master_sector
        ON stock_master (sector);
    CREATE INDEX IF NOT EXISTS idx_stock_master_tier
        ON stock_master (tier, market_cap DESC NULLS LAST);
    CREATE INDEX IF NOT EXISTS idx_stock_master_etf
        ON stock_master (is_etf) WHERE is_etf = TRUE;
    """,

    # 22-b. 티커 마스터 (정규화된 티커 통합 관리)
    """
    CREATE TABLE IF NOT EXISTS ticker_master (
        canonical       VARCHAR(20) PRIMARY KEY,
        raw_code        VARCHAR(10) NOT NULL,
        name            TEXT NOT NULL,
        market          VARCHAR(20) NOT NULL,
        suffix          VARCHAR(5) NOT NULL,
        asset_type      VARCHAR(10) NOT NULL DEFAULT 'stock'
                            CHECK (asset_type IN ('stock', 'etf', 'etn', 'index', 'commodity', 'currency', 'rate')),
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ticker_master_raw
        ON ticker_master (raw_code) WHERE is_active = TRUE;
    CREATE INDEX IF NOT EXISTS idx_ticker_master_market
        ON ticker_master (market, is_active);
    CREATE INDEX IF NOT EXISTS idx_ticker_master_asset
        ON ticker_master (asset_type, is_active);

    -- 기본 종목 시드 데이터 (core 종목)
    INSERT INTO ticker_master (canonical, raw_code, name, market, suffix, asset_type)
    VALUES
        ('005930.KS', '005930', '삼성전자', 'KOSPI', 'KS', 'stock'),
        ('000660.KS', '000660', 'SK하이닉스', 'KOSPI', 'KS', 'stock'),
        ('259960.KS', '259960', '크래프톤', 'KOSPI', 'KS', 'stock'),
        ('005380.KS', '005380', '현대자동차', 'KOSPI', 'KS', 'stock'),
        ('000270.KS', '000270', '기아', 'KOSPI', 'KS', 'stock'),
        ('051910.KS', '051910', 'LG화학', 'KOSPI', 'KS', 'stock'),
        ('006800.KS', '006800', '미래에셋증권', 'KOSPI', 'KS', 'stock'),
        ('034020.KS', '034020', '두산에너빌리티', 'KOSPI', 'KS', 'stock'),
        ('003670.KS', '003670', '포스코퓨처엠', 'KOSPI', 'KS', 'stock'),
        ('028260.KS', '028260', '삼성물산', 'KOSPI', 'KS', 'stock'),
        ('035420.KS', '035420', 'NAVER', 'KOSPI', 'KS', 'stock'),
        ('035720.KS', '035720', '카카오', 'KOSPI', 'KS', 'stock'),
        ('068270.KS', '068270', '셀트리온', 'KOSPI', 'KS', 'stock'),
        ('105560.KS', '105560', 'KB금융', 'KOSPI', 'KS', 'stock'),
        ('055550.KS', '055550', '신한지주', 'KOSPI', 'KS', 'stock'),
        ('329180.KS', '329180', 'HD현대중공업', 'KOSPI', 'KS', 'stock'),
        ('373220.KS', '373220', 'LG에너지솔루션', 'KOSPI', 'KS', 'stock'),
        ('207940.KS', '207940', '삼성바이오로직스', 'KOSPI', 'KS', 'stock'),
        ('247540.KQ', '247540', '에코프로비엠', 'KOSDAQ', 'KQ', 'stock'),
        ('196170.KQ', '196170', '알테오젠', 'KOSDAQ', 'KQ', 'stock')
    ON CONFLICT (canonical) DO NOTHING;
    """,

    # 23. 테마 → 종목 매핑
    """
    CREATE TABLE IF NOT EXISTS theme_stocks (
        id          BIGSERIAL PRIMARY KEY,
        theme_slug  VARCHAR(60) NOT NULL,
        theme_name  TEXT NOT NULL,
        ticker      VARCHAR(10) NOT NULL,
        is_leader   BOOLEAN NOT NULL DEFAULT FALSE,
        added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (theme_slug, ticker)
    );
    CREATE INDEX IF NOT EXISTS idx_theme_stocks_slug
        ON theme_stocks (theme_slug);
    CREATE INDEX IF NOT EXISTS idx_theme_stocks_ticker
        ON theme_stocks (ticker);
    """,

    # 24. 매크로 지표 (해외지수/환율/원자재/금리)
    """
    CREATE TABLE IF NOT EXISTS macro_indicators (
        id              BIGSERIAL PRIMARY KEY,
        category        VARCHAR(30) NOT NULL CHECK (category IN ('index', 'currency', 'commodity', 'rate')),
        symbol          VARCHAR(30) NOT NULL,
        name            TEXT NOT NULL,
        value           NUMERIC(18, 4) NOT NULL,
        change_pct      NUMERIC(8, 4),
        previous_close  NUMERIC(18, 4),
        snapshot_date   DATE NOT NULL,
        source          VARCHAR(30) NOT NULL DEFAULT 'fdr',
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (symbol, snapshot_date)
    );
    CREATE INDEX IF NOT EXISTS idx_macro_indicators_category
        ON macro_indicators (category, snapshot_date DESC);
    CREATE INDEX IF NOT EXISTS idx_macro_indicators_symbol
        ON macro_indicators (symbol, snapshot_date DESC);
    """,

    # 25. 일별 사전 계산 랭킹
    """
    CREATE TABLE IF NOT EXISTS daily_rankings (
        id              BIGSERIAL PRIMARY KEY,
        ranking_date    DATE NOT NULL,
        ranking_type    VARCHAR(30) NOT NULL CHECK (ranking_type IN (
            'market_cap', 'volume', 'turnover', 'gainer', 'loser', 'new_high', 'new_low'
        )),
        rank            INTEGER NOT NULL CHECK (rank >= 1),
        ticker          VARCHAR(10) NOT NULL,
        name            TEXT NOT NULL,
        value           NUMERIC(18, 4),
        change_pct      NUMERIC(8, 4),
        extra           JSONB,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (ranking_date, ranking_type, rank)
    );
    CREATE INDEX IF NOT EXISTS idx_daily_rankings_date_type
        ON daily_rankings (ranking_date DESC, ranking_type);
    """,

    # 26. 관심 종목 (watchlist)
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id                  BIGSERIAL PRIMARY KEY,
        user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        group_name          VARCHAR(60) NOT NULL DEFAULT 'default',
        ticker              VARCHAR(10) NOT NULL,
        name                TEXT NOT NULL,
        price_alert_above   INTEGER,
        price_alert_below   INTEGER,
        added_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, group_name, ticker)
    );
    CREATE INDEX IF NOT EXISTS idx_watchlist_user
        ON watchlist (user_id, group_name);
    CREATE INDEX IF NOT EXISTS idx_watchlist_ticker
        ON watchlist (ticker);
    """,

    # ── 전략 승격 + 리스크 스냅샷 테이블 ──────────────────────────────────────

    # 27. 전략 승격 기록
    """
    CREATE TABLE IF NOT EXISTS strategy_promotions (
        id                  BIGSERIAL PRIMARY KEY,
        strategy_id         VARCHAR(10) NOT NULL,
        from_mode           VARCHAR(10) NOT NULL CHECK (from_mode IN ('virtual', 'paper', 'real')),
        to_mode             VARCHAR(10) NOT NULL CHECK (to_mode IN ('virtual', 'paper', 'real')),
        criteria_snapshot   JSONB,
        actual_snapshot     JSONB,
        approved_by         VARCHAR(50) NOT NULL DEFAULT 'system',
        forced              BOOLEAN NOT NULL DEFAULT FALSE,
        promoted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_strategy_promotions_strategy
        ON strategy_promotions (strategy_id, promoted_at DESC);
    """,

    # 28. 합산 리스크 스냅샷
    """
    CREATE TABLE IF NOT EXISTS aggregate_risk_snapshots (
        id              BIGSERIAL PRIMARY KEY,
        risk_data       JSONB NOT NULL,
        snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_aggregate_risk_snapshots_at
        ON aggregate_risk_snapshots (snapshot_at DESC);
    """,

    # ── account_scope CHECK 확장 (virtual 추가) ─────────────────────────────
    """
    ALTER TABLE trading_accounts
        DROP CONSTRAINT IF EXISTS trading_accounts_account_scope_check;
    ALTER TABLE trading_accounts
        ADD CONSTRAINT trading_accounts_account_scope_check
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    """,

    """
    ALTER TABLE portfolio_positions
        DROP CONSTRAINT IF EXISTS portfolio_positions_account_scope_check;
    ALTER TABLE portfolio_positions
        ADD CONSTRAINT portfolio_positions_account_scope_check
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    """,

    """
    ALTER TABLE trade_history
        DROP CONSTRAINT IF EXISTS trade_history_account_scope_check;
    ALTER TABLE trade_history
        ADD CONSTRAINT trade_history_account_scope_check
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    """,

    """
    ALTER TABLE broker_orders
        DROP CONSTRAINT IF EXISTS broker_orders_account_scope_check;
    ALTER TABLE broker_orders
        ADD CONSTRAINT broker_orders_account_scope_check
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    """,

    """
    ALTER TABLE account_snapshots
        DROP CONSTRAINT IF EXISTS account_snapshots_account_scope_check;
    ALTER TABLE account_snapshots
        ADD CONSTRAINT account_snapshots_account_scope_check
        CHECK (account_scope IN ('paper', 'real', 'virtual'));
    """,

    # ── strategy_id 컬럼 추가 (이미 없으면) ──────────────────────────────────
    """
    ALTER TABLE trading_accounts ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE broker_orders ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    ALTER TABLE account_snapshots ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(10);
    """,

    # ── signal_source CHECK 확장 (VIRTUAL, EXIT 추가) ──────────────────────
    """
    ALTER TABLE trade_history
        DROP CONSTRAINT IF EXISTS trade_history_signal_source_check;
    ALTER TABLE broker_orders
        DROP CONSTRAINT IF EXISTS broker_orders_signal_source_check;
    """,
]

DROP_TABLES_SQL = """
DROP TABLE IF EXISTS
    aggregate_risk_snapshots,
    strategy_promotions,
    watchlist,
    daily_rankings,
    macro_indicators,
    theme_stocks,
    agent_registry,
    ticker_master,
    stock_master,
    research_outputs,
    page_extractions,
    search_results,
    search_queries,
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
    ohlcv_daily,
    instruments,
    markets,
    market_data,
    users
CASCADE;
"""


_PLACEHOLDER_VALUES = {
    "admin@example.com",
    "CHANGE_ME_ADMIN@example.com",
    "CHANGE_ME",
    "admin1234",
    "CHANGE_ME_STRONG_PASSWORD",
    "",
}


def _is_enabled(raw: Optional[str]) -> bool:
    # 기본값 false — 명시적으로 활성화해야만 시딩 동작
    return (raw or "false").strip().lower() not in {"0", "false", "no", "off"}


def get_default_admin_seed() -> Optional[Tuple[str, str, str]]:
    """환경 변수에서 기본 admin seed 설정을 읽어옵니다."""
    if not _is_enabled(os.getenv("DEFAULT_ADMIN_SEED_ENABLED", "false")):
        return None

    email = os.getenv("DEFAULT_ADMIN_EMAIL", "").strip()
    name = os.getenv("DEFAULT_ADMIN_NAME", "Admin").strip() or "Admin"
    password = os.getenv("DEFAULT_ADMIN_PASSWORD", "")

    if not email or not password:
        logger.warning("기본 admin seed 설정이 비어 있어 계정 생성을 건너뜁니다.")
        return None

    if email in _PLACEHOLDER_VALUES or password in _PLACEHOLDER_VALUES:
        logger.warning(
            "기본 admin seed에 placeholder 값이 감지되어 계정 생성을 건너뜁니다. "
            "DEFAULT_ADMIN_EMAIL 및 DEFAULT_ADMIN_PASSWORD를 실제 값으로 변경하세요."
        )
        return None

    return email, name, password


async def seed_default_admin(conn: asyncpg.Connection) -> bool:
    """기본 admin 계정이 없으면 생성합니다."""
    seed = get_default_admin_seed()
    if seed is None:
        logger.info("기본 admin seed 비활성화 또는 설정 누락으로 건너뜁니다.")
        return False

    email, name, password = seed
    exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM users WHERE email = $1)",
        email,
    )
    if exists:
        logger.info("기본 admin 계정이 이미 존재합니다: %s", email)
        return False

    await conn.execute(
        """
        INSERT INTO users (email, name, password_hash, is_admin)
        VALUES ($1, $2, $3, TRUE)
        """,
        email,
        name,
        hash_password(password),
    )
    logger.info("기본 admin 계정 시드 완료: %s", email)
    return True


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

        # ohlcv_daily 연도별 파티션 생성 (2010~2027 + default)
        for year in range(2010, 2028):
            partition_ddl = (
                f"CREATE TABLE IF NOT EXISTS ohlcv_daily_{year} "
                f"PARTITION OF ohlcv_daily "
                f"FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')"
            )
            await conn.execute(partition_ddl)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS ohlcv_daily_default "
            "PARTITION OF ohlcv_daily DEFAULT"
        )
        logger.info("ohlcv_daily 파티션 생성 완료 (2010~2027 + default)")

        await seed_default_admin(conn)

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
