# 🏛️ Architecture — 알파 시스템 전체 아키텍처 설계

> 이 파일은 시스템의 전체 구조, 데이터 흐름, 기술 결정의 근거를 설명합니다.
> 새로운 기능을 구현하기 전에 반드시 이 문서를 통해 전체 맵핑을 파악하세요.

---

## 📖 시스템 개요

알파(Alpha)는 한국 주식시장(KOSPI/KOSDAQ)을 대상으로 동작하는 **멀티 에이전트 자동 투자 시스템**입니다.
5개의 독립적인 에이전트가 Redis Pub/Sub을 통해 비동기로 통신하며, 두 가지 AI 트레이딩 전략을 동시에 운용합니다.

---

## 📂 디렉터리 구조

```
agents-investing/
├── CLAUDE.md              # 에이전트 행동 강령 (최우선 진입점)
├── MEMORY.md              # 기술적 결정 및 문제 해결 누적 기록
├── progress.md            # 현재 세션 진행 상황
├── README.md              # 프로젝트 소개 문서
├── architecture.md        # 전체 아키텍처 설계 (이 파일)
│
├── .agent/                # 에이전트 전용 지침서
│   ├── conventions.md     # 코드 스타일, 카멜 케이션
│   ├── prompts.md         # 재사용 프롬프트 템플릿
│   ├── roadmap.md         # Phase 1~7 마일스톤
│   └── tech_stack.md      # 허용/금지 패키지 목록
│
├── docs/                  # 시스템 설계 문서
│   ├── AGENTS.md          # 에이전트 명세 및 메시지 카트릭트
│   ├── BOOTSTRAP.md       # 부팅 절차
│   ├── HEARTBEAT.md       # 헬스 모니터링 규격
│   ├── IDENTITY.md        # 에이전트 페르소나 및 LLM 프롬프트
│   ├── MEMORY.md          # 메모리 시스템 설계
│   ├── SOUL.md            # 핵심 가치관
│   ├── TOOLS.md           # 도구 목록 및 쌍근 제어
│   ├── USER.md            # 사용자 페르소나
│   └── api_spec.md        # REST API 엔드포인트 명세
│
├── src/                   # 백엔드 소스 코드 (Python)
│   ├── agents/            # 에이전트 구현
│   │   ├── collector.py
│   │   ├── predictor.py
│   │   ├── portfolio_manager.py
│   │   ├── notifier.py
│   │   └── orchestrator.py
│   ├── api/               # FastAPI 라우터
│   ├── db/                # PostgreSQL 모델 및 쿼리
│   ├── llm/               # LLM 클라이언트 (Claude/GPT/Gemini)
│   └── utils/             # 공통 유틸리티
│
├── ui/                    # 프론트엔드 (TypeScript + React)
│   ├── src/
│   │   ├── components/    # UI 컴포넌트
│   │   ├── pages/         # 페이지 라우트
│   │   ├── hooks/         # React Query 훅
│   │   └── stores/        # Zustand 상태
│   └── package.json
│
├── scripts/               # 운영 스크립트
│   ├── db/init_db.py
│   ├── kis_auth.py
│   ├── fetch_krx_holidays.py
│   ├── health_check.py
│   ├── test_llm_connections.py
│   └── smoke_test.py
│
└── test/                  # 테스트 코드
    ├── unit/
    └── integration/
```

---

## 🔄 전체 데이터 흐름

```
외부 데이터 소스
  ├── FinanceDataReader (EOD OHLCV)
  └── KIS Developers WebSocket (장중 틱)
          │
          ▼
   CollectorAgent
   PostgreSQL: market_data
   Redis: latest_ticks:{ticker}
          │
          │ redis:topic:market_data
          ▼
   OrchestratorAgent (N-way StrategyRegistry)
   ┌──────────────────────────────────────────────────────────────────────┐
   │                                                                      │
   ▼              ▼              ▼              ▼
Strategy A   Strategy B   Strategy RL   Strategy S
Tournament   Debate      RL Trading    Search/Research
(A)          (B)         (RL)          (S)
   │              │              │              │
   └──────────────┴──────────────┴──────────────┘
                  │ N-way blend + weights
                  ▼
        PortfolioManagerAgent
        리스크 규칙 검증 (하드코딩)
        KIS Developers API
        PostgreSQL: portfolio_positions, trade_history
                  │
                  │ redis:topic:orders
                  ▼
           NotifierAgent
           Telegram Bot
                  │
                  ▼
           [React 대시보드]
           FastAPI REST API
```

---

## 🤖 5개 에이전트 아키텍처

### CollectorAgent
- **트리거:** APScheduler 크론 (08:30 일괄 수집, 09:00-15:30 장중 틱)
- **출력:** PostgreSQL `market_data`, Redis `latest_ticks:{ticker}`
- **의존성:** FinanceDataReader, KIS WebSocket

### PredictorAgent (×5 인스턴스)
- **트리거:** OrchestratorAgent spawn (Strategy A: 08:45, Strategy B: 08:30)
- **LLM 연동:**
  - 인스턴스 1, 2: Claude CLI (`subprocess` 호출)
  - 인스턴스 3, 4: OpenAI GPT-4o (`openai` SDK, OAuth API Key)
  - 인스턴스 5: Gemini CLI (`subprocess` 호출)
- **출력:** PostgreSQL `predictions`, Redis `redis:topic:signals`

### PortfolioManagerAgent
- **트리거:** `redis:topic:signals` 수신
- **책임:** 유일하게 `kis_place_order` 도구 사용 가능
- **리스크 규칙:** 코드 레벨 하드코딩 (LLM 오버라이드 불가)
  - 단일 종목 최대 비중 20%
  - 일손실 -3% 서킷브레이커
- **출력:** PostgreSQL `portfolio_positions`, `trade_history`

### NotifierAgent
- **트리거:** 모든 주요 이벤트 (`redis:topic:alerts`, 스케줄)
- **유일하게:** `telegram_send` 도구 사용 가능
- **알림 채널:** Telegram Bot API

### OrchestratorAgent
- **구현:** LangGraph StateGraph + PostgreSQL AsyncPostgresSaver
- **역할:** 상태 기계, 에이전트 스폰/모니터링, 토너먼트 스코어링
- **헬스 모니터링:** 60초 간격 폴링, TTL 90초 Redis heartbeat 키

---

## 🧠 두 가지 트레이딩 전략

### Strategy A — Tournament (경쟁 방식)

```
08:45 KST
  OrchestratorAgent → 5개 PredictorAgent 병렬 spawn
  각 인스턴스: 서로 다른 LLM + 투자 성향

  [Warren-Claude] [Tech-Claude] [Mo-GPT] [Contra-GPT] [Macro-Gemini]
       │               │           │           │              │
       └───────────────┴───────────┴───────────┴──────────────┘
                               ↓ 장 마감 후
               OrchestratorAgent 토너먼트 스코어링
               (5일 rolling accuracy 비교)
                               ↓
               우승 인스턴스의 시그널 → PortfolioManagerAgent
```

### Strategy B — Consensus/Debate (토론 방식)

```
08:30 KST
  Proposer (Claude): 종목별 투자 논거 제시
       ↓
  Challenger 1 (GPT-4o): 단기 리스크 반론
  Challenger 2 (Gemini): 거시경제 리스크 반론
       ↓
  Proposer: 재반박 (최대 3라운드)
       ↓
  Synthesizer (Claude): 최종 합의 시그널 도출
  (합의 실패 시 HOLD)
       ↓
  08:55 KST → PortfolioManagerAgent
```

두 전략은 **동시에** 운용되며, 사용자가 설정하는 `STRATEGY_BLEND_RATIO`에 따라 가중치가 결정됩니다.

---

## 📮 데이터 아키텍처

### 메모리 3-Tier

| Tier | 저장소 | 수명 | 용도 |
|------|--------|------|------|
| Hot | Redis | ~24h | 실시간 틱, 진행 중 토론 상태, 헬스비트, OAuth 토큰 |
| Warm | PostgreSQL | 90일 | 거래 이력, 예측 기록, 토너먼트 점수, 토론 전문 |
| Cold | PostgreSQL Archive | 무기한 | 연간 성과, 주요 이벤트 로그 |
| Archive | S3 Data Lake (MinIO) | 무기한 | 원시 데이터 전체 (Parquet), RL 학습/백테스트용 |

### 주요 PostgreSQL 테이블

| 테이블 | 주요 쓰기 에이전트 |
|--------|-----------------|
| `market_data` | CollectorAgent |
| `predictions` | PredictorAgent |
| `predictor_tournament_scores` | OrchestratorAgent |
| `portfolio_positions` | PortfolioManagerAgent |
| `trade_history` | PortfolioManagerAgent |
| `debate_transcripts` | OrchestratorAgent |
| `agent_heartbeats` | 모든 에이전트 (7일 롤링) |

### Redis 주요 키

| 키 패턴 | TTL | 용도 |
|---------|-----|------|
| `heartbeat:{agent_id}` | 90s | 에이전트 생존 신호 |
| `kis:oauth_token` | 23h | KIS API 인증 토큰 |
| `krx:holidays:{year}` | 24h | KRX 휴장일 캘린더 |
| `redis:cache:latest_ticks:{ticker}` | 60s | 실시간 시세 캐시 |
| `memory:macro_context` | 4h | 거시경제 캐텍스트 |

### S3 Data Lake (MinIO + Parquet)

운영 데이터베이스(PostgreSQL)와 별도로, 모든 원시 데이터를 장기 보관하는 **읽기 전용 아카이브**입니다.
분석, RL 학습, 백테스트 등 배치 워크로드에 활용합니다.

**인프라:**

| 구성요소 | 개발 환경 | 프로덕션 |
|----------|-----------|----------|
| 오브젝트 스토리지 | MinIO (Docker) | AWS S3 |
| 직렬화 포맷 | Apache Parquet (Snappy 압축) | 동일 |
| 클라이언트 | boto3 (s3v4 서명) | 동일 |

개발→프로덕션 전환 시 `S3_ENDPOINT_URL`만 변경하면 됩니다.

**단일 버킷 구조:**

```
alpha-lake/                          ← 버킷 (1개)
├── ticks/                           ← 실시간 틱 데이터
│   └── year=2026/month=03/day=15/
│       ├── 005930.parquet           ← 삼성전자
│       └── 000660.parquet           ← SK하이닉스
├── daily_bars/                      ← 일봉 OHLCV
│   └── year=2026/month=03/day=15/
│       └── 005930.parquet
├── macro/                           ← 거시경제 지표
│   └── year=2026/month=03/day=15/
│       └── macro_snapshot.parquet
├── search/                          ← 검색/스크래핑 결과
│   └── year=2026/month=03/day=15/
│       └── searxng_results.parquet
├── research/                        ← 리서치 분석 결과
│   └── year=2026/month=03/day=15/
│       └── analysis.parquet
├── predictions/                     ← AI 예측 시그널
│   └── year=2026/month=03/day=15/
│       └── 005930.parquet
└── orders/                          ← 주문 실행 기록
    └── year=2026/month=03/day=15/
        └── order_12345.parquet
```

파티셔닝은 `{data_type}/year=YYYY/month=MM/day=DD/{filename}.parquet` Hive 스타일을 따릅니다.
하나의 버킷에서 prefix 기반으로 데이터를 분리하며, 접근 정책이나 수명주기가 달라질 경우에만 버킷을 분리합니다.

**7가지 데이터 타입:**

| DataType | 쓰기 에이전트 | 설명 |
|----------|--------------|------|
| `ticks` | CollectorAgent | 실시간 체결 틱 (100건 배치 플러시) |
| `daily_bars` | CollectorAgent | 일봉 OHLCV (FDR, Yahoo) |
| `macro` | CollectorAgent | 거시경제 지표 스냅샷 |
| `search` | SearchAgent | SearXNG 검색 결과 |
| `research` | SearchAgent | ScrapeGraphAI + Claude 분석 |
| `predictions` | PredictorAgent | 전략 A/B 예측 시그널 |
| `orders` | PortfolioManager | 주문 실행 결과 |

**데이터 흐름:**

```
CollectorAgent ──┬── ticks (100건 버퍼 → 플러시)
                 ├── daily_bars
                 └── macro
                            ↘
SearchAgent ────┬── search       boto3
                └── research  ──────→  MinIO / S3
                            ↗         (alpha-lake)
PredictorAgent ── predictions
PortfolioManager ── orders
```

**구현 파일:**

| 파일 | 역할 |
|------|------|
| `src/utils/s3_client.py` | boto3 싱글턴 클라이언트, CRUD 유틸리티 |
| `src/services/datalake.py` | PyArrow 스키마 정의, Parquet 직렬화, 편의 함수 |
| `src/api/main.py` | FastAPI 시작 시 버킷 자동 생성 (실패해도 서버 기동) |

**설계 원칙:**

1. Data Lake는 **읽기 전용 아카이브**입니다. 운영 쿼리는 PostgreSQL을 사용합니다.
2. S3 저장 실패는 경고만 남기고 서비스를 중단하지 않습니다 (graceful degradation).
3. 틱 데이터는 네트워크 부하를 줄이기 위해 100건 단위로 배치 플러시합니다.
4. 모든 Parquet 파일은 Snappy 압축 + 컬럼 통계 + 페이지 인덱스를 포함합니다.

---

## 🌐 API 레이어 (FastAPI)

백엔드는 FastAPI로 구현되며, React 대시보드와 통신합니다.

```
GET  /api/v1/market/*          # 시장 데이터
GET  /api/v1/agents/*          # 에이전트 상태 및 로그
GET  /api/v1/strategy/*        # Strategy A/B 시그널 및 토너먼트
GET  /api/v1/portfolio/*       # 포트폴리오, 거래 이력, 성과
POST /api/v1/portfolio/config  # 설정 변경
GET  /api/v1/notifications/*   # 알림 이력 및 설정
```

상세 명세: [docs/api_spec.md](docs/api_spec.md)

---

## 🖥️ 프론트엔드 아키텍처 (React)

**디자인 레퍼런스:** Toss 비즈니스 스타일 (카드 기반, 큰 숫자, 미니바)

```
ui/src/
├── pages/
│   ├── Dashboard.tsx     # 홈 (포트폴리오 요약, 시그널 요약, 에이전트 상태)
│   ├── Strategy.tsx      # Strategy A 토너먼트 + Strategy B 토론
│   ├── Portfolio.tsx     # 포지션, 거래 이력, 성과 차트
│   ├── Market.tsx        # 시장 데이터, 캔들차트
│   └── Settings.tsx      # 전략 설정, 알림 설정
├── components/
│   ├── AgentStatusBar/   # 에이전트 헬스비트 실시간 표시
│   ├── SignalCard/        # BUY/SELL/HOLD 시그널 카드
│   ├── TournamentTable/  # 토너먼트 순위표
│   └── DebateViewer/     # Strategy B 토론 전문 뷰어
└── hooks/
    ├── useAgentStatus.ts  # React Query: /agents/status SSE 또는 polling
    ├── useSignals.ts      # React Query: /strategy/combined
    └── usePortfolio.ts    # React Query: /portfolio/positions
```

**상태 관리:**
- 서버 상태: TanStack React Query (polling 또는 WebSocket)
- 클라이언트 상태: Zustand (테마, 사이드바 등 UI 상태)

---

## 🔐 보안 설계

1. **API 키 격리:** 모든 시크릿은 `.env`에만 존재, 코드에 하드코딩 절대 금지
2. **트레이딩 권한 분리:** `kis_place_order`는 PortfolioManagerAgent 전용
3. **리스크 규칙 하드코딩:** 서킷브레이커는 LLM 레이어 아래 코드 레벨에서 강제
4. **페이퍼 트레이딩 기본값:** `KIS_IS_PAPER_TRADING=true`, 실거래 전환 시 별도 확인 단계
5. **JWT 인증:** 대시보드 API는 Bearer 토큰 필수

---

## 🛠️ 개발 도구

| 도구 | 용도 |
|------|------|
| Python `pytest` | 백엔드 단위/통합 테스트 |
| `vitest` | 프론트엔드 테스트 |
| ESLint + Prettier | 프론트엔드 코드 품질 |
| `ruff` | Python 린팅 |
| APScheduler | 크론 스케줄링 (장중 수집 등) |
| LangGraph | 에이전트 워크플로우 상태 기계 |

---

## 📋 개발 원칙

1. **에이전트 분리:** 각 에이전트는 자신의 도구 범위 외에 쌍근 불가
2. **실패 안전 (Fail Safe):** 데이터 없으면 HOLD, 에이전트 장애 시 포지션 현상 유지
3. **투명성:** 모든 매매 결정은 reasoning과 함께 기록
4. **무료 API 우선:** KRX 무료 데이터로 시작, 필요 시 유료 확장
5. **페이퍼 저먼저:** 모든 새 기능은 페이퍼 트레이딩에서 먼저 검증

---

## 확장 레이어 메모

### 강화학습 트레이딩 레이어

- 기존 Strategy A/B와 병렬로 동작하는 추가 기능입니다.
- 데이터셋/피처 생성, 환경/시뮬레이터, 학습, 평가, 정책 추론으로 구성합니다.
- RL 정책은 직접 브로커를 호출하지 않고, 최종 주문은 항상 `PortfolioManagerAgent`를 통과합니다.

### 검색/스크래핑 리서치 레이어

- 기존 전략 입력을 보강하는 추가 기능입니다.
- 권장 흐름은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI 파싱 -> Claude CLI 추론` 입니다.
- 이 레이어는 정보 수집과 구조화만 담당하며 직접 주문 권한을 갖지 않습니다.

### 확장 원칙

1. 새 기능은 기존 시스템을 대체하지 않고 레이어로 추가합니다.
2. 모든 전략 계열 기능은 `paper first` 원칙을 유지합니다.
3. 주문 권한은 계속 `PortfolioManagerAgent`에 집중합니다.

*Last updated: 2026-03-15*

