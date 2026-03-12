# 📝 progress.md — 현재 세션 진척도

> 에이전트와 "현재 어디까지 했는지" 맞추는 단기 기억 파일입니다.
> 모든 작업 완료 후 반드시 업데이트하세요.

---

## 🎯 현재 스프린트 목표

**Phase 3 — Strategy A 토너먼트 고도화**
5개 Predictor 병렬 토너먼트 러너를 추가했고, 남은 작업은 실제 장중/장후 운영 스케줄 고도화입니다.

---

## ✅ 할 일 목록

### 🔄 진행 중 (Phase 2)

- [x] `src/agents/collector.py` — CollectorAgent MVP (FinanceDataReader 일봉 수집)
- [x] `src/agents/collector.py` — KIS WebSocket 실시간 틱 수집 본연동
- [x] `src/db/models.py` + `src/db/queries.py` — Pydantic 모델 및 DB 쿼리 함수
- [x] `src/llm/claude_client.py` — Claude CLI / SDK 래퍼
- [x] `src/llm/gpt_client.py` — OpenAI GPT-4o 클라이언트
- [x] `src/llm/gemini_client.py` — Google Gemini CLI 래퍼
- [x] `src/agents/predictor.py` — PredictorAgent MVP (Claude 단일 인스턴스 + 규칙 폴백)
- [x] `src/agents/portfolio_manager.py` — PortfolioManagerAgent (페이퍼 주문 처리)
- [x] `src/agents/notifier.py` — NotifierAgent (Telegram 기본 알림)
- [x] `src/agents/orchestrator.py` — OrchestratorAgent (기본 수집→예측→주문 사이클)

### ✅ 완료

#### Phase 1 — 인프라 기반 구축 (2026-03-12)
- [x] 프로젝트 초기 구조 세팅 (2026-03-10)
- [x] CLAUDE.md, architecture.md 작성 (2026-03-12)
- [x] `.agent/` 문서 작성 — tech_stack.md, roadmap.md, conventions.md, prompts.md (2026-03-12)
- [x] `docs/` 전체 문서 작성 — AGENTS.md, BOOTSTRAP.md, HEARTBEAT.md, IDENTITY.md, MEMORY.md, SOUL.md, TOOLS.md, USER.md, api_spec.md (2026-03-12)
- [x] README.md, MEMORY.md(루트), progress.md 작성 (2026-03-12)
- [x] **디렉터리 구조 생성** — src/, scripts/, test/, ui/ 전체 폴더 (2026-03-12)
- [x] **`scripts/db/init_db.py`** — PostgreSQL 11개 테이블 스키마 생성 스크립트 (2026-03-12)
- [x] **`src/utils/config.py`** — Pydantic v2 Settings 기반 환경변수 관리 (2026-03-12)
- [x] **`src/utils/logging.py`** — 공통 로거 설정 (2026-03-12)
- [x] **`src/utils/redis_client.py`** — Redis 비동기 클라이언트, 채널/키 상수, TTL 상수 (2026-03-12)
- [x] **`src/utils/db_client.py`** — asyncpg 연결 풀 싱글턴 (2026-03-12)
- [x] **`src/api/main.py`** — FastAPI 앱 (lifespan, CORS, /health 엔드포인트) (2026-03-12)
- [x] **`src/api/deps.py`** — JWT 의존성 주입 (2026-03-12)
- [x] **`src/api/routers/auth.py`** — 로그인, /users/me (2026-03-12)
- [x] **`src/api/routers/market.py`** — 종목 목록, OHLCV, 실시간 시세, 지수 (2026-03-12)
- [x] **`src/api/routers/agents.py`** — 에이전트 상태, 로그, 재시작 (2026-03-12)
- [x] **`src/api/routers/strategy.py`** — Strategy A/B 시그널, 토너먼트, 토론, 블렌드 (2026-03-12)
- [x] **`src/api/routers/portfolio.py`** — 포지션, 거래이력, 성과, 설정 (2026-03-12)
- [x] **`src/api/routers/notifications.py`** — 알림 이력, 테스트 발송, 설정 (2026-03-12)
- [x] **`scripts/kis_auth.py`** — KIS OAuth2 토큰 발급/확인/폐기 (2026-03-12)
- [x] **`scripts/fetch_krx_holidays.py`** — KRX 공휴일 수집·Redis 저장 (2026-03-12)
- [x] **`scripts/health_check.py`** — 시스템 전체 상태 점검 (2026-03-12)
- [x] **`scripts/smoke_test.py`** — 엔드-투-엔드 스모크 테스트 (2026-03-12)
- [x] **`.env.example`** — 전체 환경변수 템플릿 (2026-03-12)
- [x] **`requirements.txt`** — Python 의존성 목록 (2026-03-12)
- [x] **`ui/`** — React + Vite + TypeScript + Tailwind 프론트엔드 스캐폴딩 (2026-03-12)
  - package.json, vite.config.ts, tsconfig.json, tailwind.config.js
  - App.tsx, Layout, Dashboard, Strategy, Portfolio, Market, Settings 페이지
  - AgentStatusBar, SignalCard, TournamentTable 컴포넌트
  - useAgentStatus, useSignals, usePortfolio 훅
  - Zustand 상태, Axios 인스턴스

### ⏸️ 보류 / 차후

- [~] **Phase 3:** Strategy A Tournament (5개 인스턴스 병렬) — 기본 구현 완료, 운영 고도화 잔여
- [ ] **Phase 4:** Strategy B Consensus/Debate
- [ ] **Phase 5:** Toss 스타일 대시보드 완성 (캔들차트, 토론 뷰어 등)
- [ ] **Phase 6:** 30일 페이퍼 트레이딩 운용
- [ ] **Phase 7:** 실거래 준비 및 보안 감사

---

## 📋 최근 작업 로그

| 날짜 | 작업 내용 | 상태 |
|------|-----------|------|
| 2026-03-12 | Strategy A 토너먼트 기본 구현 — 5개 Predictor 병렬 실행, 예측 정답 백필, 롤링 정확도 기반 우승자 선정, Orchestrator 연동(--tournament) | ✅ 완료 |
| 2026-03-12 | CollectorAgent KIS WebSocket 본연동 — approval_key 발급, TR 구독, 틱 파싱/저장, 재연결/폴백 로직 추가 | ✅ 완료 |
| 2026-03-12 | Phase 2 코어 에이전트 MVP 추가 — collector/predictor/portfolio_manager/notifier/orchestrator, db models/queries, llm clients(claude/gpt/gemini) 구현 | ✅ 완료 |
| 2026-03-12 | Phase 1 코드 전체 구현 완료 — DB 스키마, FastAPI, KIS OAuth, KRX 휴장일, 헬스체크, 스모크테스트, 프론트엔드 스캐폴딩 | ✅ 완료 |
| 2026-03-12 | 전체 시스템 문서 작성 완료 (docs/ 9개, .agent/ 2개, 루트 4개) | ✅ 완료 |
| 2026-03-12 | README.md, architecture.md 프로젝트 내용으로 전면 재작성 | ✅ 완료 |
| 2026-03-12 | 시스템 아키텍처 확정 (5 에이전트, 2 전략, 3종 LLM, Telegram 알림) | ✅ 완료 |
| 2026-03-10 | 프로젝트 초기 구조 세팅 | ✅ 완료 |

---

## 🗺️ 전체 진행률

```
Phase 1 인프라 구축    ██████████  100% ✅ (문서 + 코드 완료)
Phase 2 코어 에이전트  ██████████  100% ✅
Phase 3 Strategy A    ████░░░░░░   40% (토너먼트 기본 구현 완료)
Phase 4 Strategy B    ░░░░░░░░░░    0%
Phase 5 대시보드       ██░░░░░░░░   20% (스캐폴딩 완료, 상세 구현 미완)
Phase 6 페이퍼 운용    ░░░░░░░░░░    0%
Phase 7 실거래 준비    ░░░░░░░░░░    0%
```

## 🚀 다음 실행 명령어

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일 편집 (DB, Redis, API 키 등 입력)

# 2. Python 의존성 설치
pip install -r requirements.txt --break-system-packages

# 3. DB 스키마 생성
python scripts/db/init_db.py

# 4. KRX 휴장일 수집
python scripts/fetch_krx_holidays.py

# 5. KIS 토큰 발급 (API 키 설정 후)
python scripts/kis_auth.py

# 6. FastAPI 서버 실행
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# 7. 헬스 체크
python scripts/health_check.py

# 8. 스모크 테스트
python scripts/smoke_test.py --skip-telegram

# 9. 프론트엔드 실행
cd ui && npm install && npm run dev
```

---

*Last updated: 2026-03-12*
