# 📝 progress.md — 현재 세션 진척도

> 에이전트와 "현재 어디까지 했는지" 맞추는 단기 기억 파일입니다.
> 모든 작업 완료 후 반드시 업데이트하세요.

---

## 🏃 현재 스프린트 목표

**Phase 11 — N-way 블렌딩 + StrategyRunner Registry**

기존 elif 체인을 StrategyRunner Protocol + Registry 패턴으로 리팩토링하고, A/B/RL N-way 블렌딩을 구현했습니다.

---

## ✅ 할 일 목록

### 🔄 진행 중 (Phase 2)

- [x] `src/agents/collector.py` — CollectorAgent MVP (FinanceDataReader 일봉 수집)
- [x] `src/agents/collector.py` — KIS WebSocket 실시간 틱 수집 본연동
- [x] `src/db/models.py` + `src/db/queries.py` — Pydantic 모델 및 DB 쿼리 함수
- [x] `src/llm/claude_client.py` — Claude CLI / SDK 래퍼
- [x] `src/llm/gpt_client.py` — OpenAI GPT-4o 클라이언트
- [x] `src/llm/gemini_client.py` — Google Gemini CLI 래퍼
- [x] `src/agents/predictor.py` — PredictorAgent MVP (Claude 단일 인스턴스 + 규칙 필백)
- [x] `src/agents/portfolio_manager.py` — PortfolioManagerAgent (페이퍼 주문 처리)
- [x] `src/agents/notifier.py` — NotifierAgent (Telegram 기본 알림)
- [x] `src/agents/orchestrator.py` — OrchestratorAgent (기본 수집→예측→주문 사이클)

### ✅ 완료

#### Phase 1 — 인프라 및 기본 LLM 서빙

- [x] Project 초기화
- [x] FastAPI 서버 기본 구조
- [x] PostgreSQL 세팅
- [x] Redis 세팅
- [x] `.env.example` 및 `Dockerfile`
- [x] DB 마이그레이션 (Alembic)

#### Phase 2 — 데이터 수집, LLM 호출, 기본 에이전트

- [x] CollectorAgent (KIS WebSocket + FinanceDataReader)
- [x] LLM 클라이언트 (Claude/GPT-4o/Gemini)
- [x] PredictorAgent (단일 인스턴스)
- [x] PortfolioManagerAgent
- [x] NotifierAgent
- [x] OrchestratorAgent (기본 사이클)

#### Phase 3 — 멀티 프레딕터 + 토너먼트

- [x] StrategyRunner Protocol (run(tickers) → PredictionSignal[])
- [x] StrategyRunnerRegistry
- [x] Strategy A (Tournament): 5개 Predictor, rolling_accuracy
- [x] Strategy B (Consensus Debate): Proposer/Challenger/Synthesizer

#### Phase 4 — RL Trading & Search Strategy

- [x] Strategy S (Search/Scraping) **← NEW in this session**
  - [x] `SearchAgent` (Tavily + ScrapeGraphAI)
  - [x] `ResearchPortfolioManager` (SearchAgent 래핑)
  - [x] Sentiment → Signal 매핑
  - [x] Redis 캐싱 (4시간 TTL)
  - [x] `IndexCollector` (KOSPI/KOSDAQ 수집)
  - [x] `index_scheduler.py` (APScheduler)
- [ ] Strategy RL (Reinforcement Learning) — 다음 Phase

#### Phase 5 — N-way 블렌딩 (진행 중)

- [x] N-way Signal Blending 구조 (A:0.3, B:0.3, S:0.2, RL:0.2)
- [x] Signal blending 로직
- [x] Circuit Breaker & Rules 적용
- [x] Strategy S (SearchRunner) Orchestrator 통합 **← COMPLETED in this session**
- [ ] 성능 최적화 및 튜닝

---

## 📊 파일 현황

| 파일 | 상태 | 비고 |
|------|------|------|
| `src/agents/search_agent.py` | ✅ 구현 | SearchAgent MVP |
| `src/agents/research_portfolio_manager.py` | ✅ 구현 | ResearchPortfolioManager + sentiment→signal 매핑 |
| `src/agents/search_runner.py` | ✅ 구현 | SearchRunner (Strategy S StrategyRunner 구현) |
| `src/agents/index_collector.py` | ✅ 구현 | IndexCollector (KOSPI/KOSDAQ) |
| `src/agents/orchestrator.py` | ✅ 수정 | TYPE_CHECKING 임포트 수정 + SearchRunner 통합 준비 |
| `src/schedulers/index_scheduler.py` | ✅ 구현 | APScheduler로 지수 수집 자동화 |
| `src/utils/config.py` | ✅ 확인 | strategy_blend_weights: S:0.20 이미 구성됨 |
| `test/test_search_runner.py` | ✅ 수정 | SearchRunner 임포트 경로 수정 |
| `test/test_search_runner_integration.py` | ✅ 구현 | Strategy S Orchestrator 통합 테스트 |
| `MEMORY.md` | ✅ 업데이트 | 기술적 결정 기록 |
| `docs/AGENTS.md` | ✅ 업데이트 | 멀티 에이전트 정의 |

---

## 🎯 Next Immediate Tasks

1. [x] Orchestrator에 Strategy S 통합 (SearchRunner 등록) **← COMPLETED**
2. [x] Strategy S 가중치를 블렌딩에 반영 (`strategy_blend_weights["S"] = 0.20`) **← CONFIRMED**
3. [x] AST 검증 + 코드 품질 검증 통과
4. [x] README 업데이트 (4전략 N-way 블렌딩 반영, 확장 상태 표 추가)
5. [x] Copilot 리뷰 코드 품질 이슈 수정 (risk_summary, StrategyPromoter, PromotionCheckResult)
6. [x] 마켓플레이스 논의 문서 Closure
7. [ ] 성능 최적화 및 튜닝 (다음 스프린트)

---

*Last updated: 2026-03-16*
*Strategy S Orchestrator 통합 + Copilot 리뷰 수정 + README/문서 업데이트 완료*
