# 🧠 MEMORY.md — 메모리 시스템 설계 문서

> 이 파일은 메모리 시스템의 **구조 설계 문서**입니다.
> 실제 기술적 결정 기록은 루트의 `MEMORY.md`를 참조하세요.

---

## 📐 메모리 3-Tier 구조

에이전트의 기억은 세 계층으로 나뉩니다. 데이터의 성격과 수명에 따라 저장 계층이 결정됩니다.

| 계층 | 저장소 | 수명 | 용도 |
|------|--------|------|------|
| **Hot Memory** | Redis | 최대 24시간 | 현재 세션 컨텍스트, 최신 시그널, 진행 중인 토론 상태 |
| **Warm Memory** | PostgreSQL | 90일 롤링 | 거래 이력, 예측 점수, 토너먼트 결과, 토론 전문 |
| **Cold Memory** | PostgreSQL (아카이브) | 무기한 | 연간 성과 요약, 주요 시장 이벤트 로그 |

---

## 🔑 Redis Hot Memory 키 구조

| Redis 키 | TTL | 쓰는 에이전트 | 읽는 에이전트 | 내용 |
|---------|-----|-------------|-------------|------|
| `heartbeat:{agent_id}` | 90초 | 각 에이전트 | Orchestrator | 에이전트 헬스비트 |
| `krx:holidays:{year}` | 24시간 | Collector | Collector, Orchestrator | KRX 휴장일 목록 |
| `kis:oauth_token` | 23시간 | PortfolioManager | PortfolioManager | KIS OAuth2 토큰 |
| `memory:macro_context` | 4시간 | Orchestrator | Predictor | 거시경제 컨텍스트 |
| `redis:cache:latest_ticks:{ticker}` | 60초 | Collector | Predictor | 최신 틱 데이터 |
| `strategy_a:winner` | 24시간 | Orchestrator | PortfolioManager | Strategy A 우승 인스턴스 ID |
| `strategy_b:debate:{date}:state` | 1시간 | Orchestrator | Predictor, Orchestrator | Strategy B 토론 진행 상태 |
| `portfolio:positions:snapshot` | 5분 | PortfolioManager | 모든 에이전트 | 최신 포트폴리오 스냅샷 |

---

## 🗄️ PostgreSQL Warm Memory 테이블

### `market_data` — 시장 데이터
```sql
CREATE TABLE market_data (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL,
    name            VARCHAR(50),
    market          VARCHAR(10),        -- 'KOSPI' | 'KOSDAQ'
    data_type       VARCHAR(10),        -- 'daily' | 'tick'
    timestamp_kst   TIMESTAMPTZ NOT NULL,
    open            INTEGER,
    high            INTEGER,
    low             INTEGER,
    close           INTEGER,
    volume          BIGINT,
    change_pct      DECIMAL(6,2),
    market_cap      BIGINT,
    foreigner_ratio DECIMAL(5,2),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_market_data_ticker_time ON market_data(ticker, timestamp_kst DESC);
```

### `predictions` — 예측 시그널
```sql
CREATE TABLE predictions (
    id                   BIGSERIAL PRIMARY KEY,
    agent_id             VARCHAR(30) NOT NULL,    -- e.g. 'predictor_3'
    llm_model            VARCHAR(30),             -- 'claude-sonnet-4-6' | 'gpt-4o' | 'gemini-1.5-pro'
    strategy             CHAR(1) NOT NULL,        -- 'A' | 'B'
    ticker               VARCHAR(10) NOT NULL,
    signal               VARCHAR(4) NOT NULL,     -- 'BUY' | 'SELL' | 'HOLD'
    confidence           DECIMAL(3,2),
    target_price         INTEGER,
    stop_loss            INTEGER,
    reasoning_summary    TEXT,
    debate_transcript_id BIGINT,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);
```

### `predictor_tournament_scores` — 토너먼트 점수
```sql
CREATE TABLE predictor_tournament_scores (
    id              BIGSERIAL PRIMARY KEY,
    agent_id        VARCHAR(30) NOT NULL,
    trade_date      DATE NOT NULL,
    ticker          VARCHAR(10) NOT NULL,
    predicted_signal VARCHAR(4),
    actual_direction VARCHAR(4),        -- 'UP' | 'DOWN' | 'FLAT'
    is_correct      BOOLEAN,
    rolling_5d_acc  DECIMAL(4,3),       -- 0.000 ~ 1.000
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### `portfolio_positions` — 현재 보유 포지션
```sql
CREATE TABLE portfolio_positions (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL,
    name            VARCHAR(50),
    quantity        INTEGER NOT NULL,
    avg_price       INTEGER NOT NULL,
    current_price   INTEGER,
    unrealized_pnl  INTEGER,            -- KRW
    weight_pct      DECIMAL(5,2),       -- 포트폴리오 비중 %
    opened_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### `trade_history` — 거래 이력
```sql
CREATE TABLE trade_history (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL,
    action          VARCHAR(4) NOT NULL,    -- 'BUY' | 'SELL'
    quantity        INTEGER NOT NULL,
    price           INTEGER NOT NULL,
    amount          BIGINT NOT NULL,        -- quantity * price (KRW)
    strategy        CHAR(1),               -- 'A' | 'B'
    signal_agent_id VARCHAR(30),
    reasoning       TEXT,
    is_paper        BOOLEAN DEFAULT TRUE,
    kis_order_id    VARCHAR(50),
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);
```

### `agent_heartbeats` — 헬스비트 로그
```sql
CREATE TABLE agent_heartbeats (
    id              BIGSERIAL PRIMARY KEY,
    agent_id        VARCHAR(30) NOT NULL,
    status          VARCHAR(10) NOT NULL,   -- 'healthy' | 'degraded' | 'error'
    last_action     TEXT,
    metrics_json    JSONB,
    recorded_at     TIMESTAMPTZ DEFAULT NOW()
);
-- 7일 보관 후 삭제 (rolling)
```

### `debate_transcripts` — Strategy B 토론 전문
```sql
CREATE TABLE debate_transcripts (
    id              BIGSERIAL PRIMARY KEY,
    debate_date     DATE NOT NULL,
    ticker          VARCHAR(10) NOT NULL,
    rounds          INTEGER,
    consensus_reached BOOLEAN,
    final_signal    VARCHAR(4),
    proposer_content TEXT,
    challenger1_content TEXT,
    challenger2_content TEXT,
    synthesizer_content TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
-- 90일 보관 후 cold storage로 이동
```

---

## 📦 에이전트별 메모리 읽기/쓰기 계약

### CollectorAgent
- **쓰기:** `market_data` 테이블, `redis:cache:latest_ticks:{ticker}`, `krx:holidays:{year}`
- **읽기:** `krx:holidays:{year}` (장 개장 여부 판단)

### PredictorAgent
- **쓰기:** `predictions` 테이블
- **읽기:**
  - 최근 30거래일 `market_data`
  - `redis:cache:latest_ticks:{ticker}`
  - `portfolio:positions:snapshot` (현재 보유 현황)
  - `predictor_tournament_scores` (자신의 최근 5일 정확도)
  - `memory:macro_context`

### PortfolioManagerAgent
- **쓰기:** `portfolio_positions`, `trade_history`, `kis:oauth_token`
- **읽기:** `redis:topic:signals`, `portfolio_positions`, `predictions`

### OrchestratorAgent
- **쓰기:** `predictor_tournament_scores`, `debate_transcripts`, `strategy_a:winner`, `memory:macro_context`
- **읽기:** 모든 `heartbeat:*`, `predictions`, `agent_heartbeats`

---

## 🔄 LangGraph 체크포인팅

- **백엔드:** PostgreSQL (`AsyncPostgresSaver`)
- **thread_id 네이밍:**
  - Strategy A: `strategy_a_{YYYYMMDD}`
  - Strategy B: `strategy_b_{YYYYMMDD}`
  - System: `orchestrator_system`
- **용도:** 워크플로우 중단 시 마지막 상태에서 재시작

---

## 🧹 메모리 정리 스케줄

| 작업 | 스케줄 | 내용 |
|------|--------|------|
| Redis TTL 자동 만료 | 상시 | 각 키의 TTL 설정에 따라 자동 삭제 |
| `market_data` 아카이브 | 매일 02:00 KST | 90일 이상된 데이터 cold storage 이동 |
| `agent_heartbeats` 삭제 | 매일 02:00 KST | 7일 이상된 로그 삭제 |
| `debate_transcripts` 아카이브 | 매일 02:00 KST | 90일 이상된 토론 전문 cold storage 이동 |

---

*Last updated: 2026-03-12*
