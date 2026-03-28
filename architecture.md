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
├── MEMORY.md              # 활성 운영 규칙 및 미해결 이슈
├── MEMORY-archive.md      # 완료된 기술적 결정 이력 (원문 보존)
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
│   ├── smoke_test.py
│   ├── post_discussion_to_blog.py   # 논의 문서 → Blogger 포스팅
│   └── setup_blogger_oauth.py       # Blogger OAuth 초기 설정
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

> **상세 문서:** 수집 소스별 저장 경로, 테이블 전체 목록, Redis 키/TTL, S3 파티셔닝 구조, 저장소 일관성 매트릭스 등
> 코드 레벨의 상세 내용은 **[DATA-STOCK_ARCHITECTURE.md](DATA-STOCK_ARCHITECTURE.md)** 를 참조하세요.

### 메모리 3-Tier

| Tier | 저장소 | 수명 | 용도 |
|------|--------|------|------|
| Hot | Redis | ~24h | 실시간 틱, 진행 중 토론 상태, 헬스비트, OAuth 토큰 |
| Warm | PostgreSQL | 90일 | 거래 이력, 예측 기록, 토너먼트 점수, 토론 전문 |
| Cold | S3/MinIO (Parquet) + PostgreSQL Archive | 무기한 | 연간 성과, 원본 OHLCV, 주요 이벤트 로그 |

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
| `stock_master` | StockMasterCollector |
| `macro_indicators` | MacroCollector |
| `broker_orders` | KIS Broker |
| `trading_accounts` | KIS Broker |
| `account_snapshots` | AccountState |

> 전체 20개 테이블의 유니크 제약, 쿼리 파일 매핑은 → [DATA-STOCK_ARCHITECTURE.md §2-1](DATA-STOCK_ARCHITECTURE.md#2-1-postgresql-srcutilsdb_clientpy)

### Redis 주요 키

| 키 패턴 | TTL | 용도 |
|---------|-----|------|
| `heartbeat:{agent_id}` | 90s | 에이전트 생존 신호 |
| `kis:oauth_token:{scope}` | 23h | KIS API 인증 토큰 |
| `krx:holidays:{year}` | 24h | KRX 휴장일 캘린더 |
| `redis:cache:latest_ticks:{ticker}` | 60s | 실시간 시세 캐시 |
| `redis:cache:market_index` | 120s | KOSPI/KOSDAQ 지수 |
| `redis:cache:stock_master` | 24h | 전종목 마스터 |
| `redis:cache:macro:{category}` | 1h | 매크로 지표 |
| `memory:macro_context` | 4h | 거시경제 컨텍스트 |

> 전체 13개 키 패턴 + 5개 Pub/Sub 채널 상세는 → [DATA-STOCK_ARCHITECTURE.md §2-2](DATA-STOCK_ARCHITECTURE.md#2-2-redis-srcutilsredis_clientpy)

### S3/MinIO Data Lake

| 파티션 | 저장 내용 | 압축 |
|--------|----------|------|
| `daily_bars/date=YYYY-MM-DD/` | 일봉 OHLCV Parquet | Snappy |
| `predictions/date=.../` | 예측 시그널 | Snappy |
| `orders/date=.../` | 주문 기록 | Snappy |
| `blend_results/date=.../` | 블렌딩 결과 | Snappy |

> PyArrow 스키마, 재시도 로직, DataType enum 상세는 → [DATA-STOCK_ARCHITECTURE.md §2-3](DATA-STOCK_ARCHITECTURE.md#2-3-s3minio-srcutilss3_clientpy--srcservicesdatalakepy)

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

1. **시크릿 격리:** KIS/Telegram 등 시크릿은 `.env`에만 존재, 코드에 하드코딩 절대 금지. LLM은 API 키 대신 CLI/OAuth 모드 사용 (Claude CLI + Gemini ADC)
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

### 블로그 자동 포스팅 파이프라인 (2026-03-28 추가)

- `.agent/discussions/*.md` 논의 문서를 Google Blogger에 자동/수동 포스팅합니다.
- **자동 훅**: Claude Code PostToolUse 훅이 Write/Edit 감지 → draft로 포스팅
- **수동 트리거**: `/post-discussion` 슬래시 커맨드 또는 `scripts/post_discussion_to_blog.py`
- **흐름**: 논의 MD → 프론트매터 파싱 → 프로젝트 컨텍스트 삽입 → HTML 변환 → Blogger API v3
- **중복 방지**: 동일 제목의 글이 있으면 업데이트
- **핵심 파일**: `src/utils/blog_client.py`, `src/utils/discussion_renderer.py`

### 문서 아카이브 체계 (2026-03-28 추가)

- `MEMORY.md`: 활성 운영 규칙 + 미해결 이슈만 유지 (200줄 이내)
- `MEMORY-archive.md`: 완료된 기술적 결정의 원문 전체를 보존
- 논의 문서는 결론 확정 → 영구 문서 반영 → 블로그 포스팅 → 삭제

### 확장 원칙

1. 새 기능은 기존 시스템을 대체하지 않고 레이어로 추가합니다.
2. 모든 전략 계열 기능은 `paper first` 원칙을 유지합니다.
3. 주문 권한은 계속 `PortfolioManagerAgent`에 집중합니다.

*Last updated: 2026-03-28*

