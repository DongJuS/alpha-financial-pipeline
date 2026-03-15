# 📈 알파 (Alpha) — AI 멀티 에이전트 한국 주식 투자 시스템

여러 AI 에이전트들의 협업 및 경쟁을 통해 최적의 주식 매매 결정을 내리는 자동화 시스템입니다.
한국 KOSPI/KOSDAQ 시장을 대상으로, 무료 오픈 API를 통해 실시간 데이터를 수집하고
**3종 LLM(Claude, GPT-4o, Gemini)** 기반의 두 가지 독립적인 트레이딩 전략을 동시에 운용합니다.

---

## 🏗️ 시스템 아키텍처

```
[KRX / KIS Developers / FinanceDataReader]
              |
        CollectorAgent
              |
        OrchestratorAgent (LangGraph)
        /                \
   Strategy A            Strategy B
   (Tournament)          (Consensus/Debate)
   Claude x2             Proposer: Claude
   GPT-4o x2      ───►   Challenger 1: GPT-4o
   Gemini x1             Challenger 2: Gemini
        |                Synthesizer: Claude
        └──────┬──────────────┘
               ↓
   PortfolioManagerAgent ──► KIS Developers API (페이퍼/실거래)
               |
         NotifierAgent ──► Telegram Bot
               |
         [React 대시보드 (Toss 스타일)]
```

---

## ✨ 두 가지 트레이딩 전략

### Strategy A — 토너먼트 (경쟁)
- 매일 아침 **5개의 PredictorAgent 인스턴스**가 병렬 실행
- 각 인스턴스는 서로 다른 LLM과 투자 성향을 가짐 (가치, 기술, 모멘텀, 역추세, 거시)
- 장 마감 후 가장 정확도가 높은 인스턴스의 시그널이 다음 날 거래에 사용됨

### Strategy B — 합의 (토론)
- **4개의 LLM 역할**이 구조화된 토론을 진행
- Proposer(Claude) → Challenger 1(GPT-4o) + Challenger 2(Gemini) → Synthesizer(Claude)
- 다라운드 토론(기본 2라운드)과 confidence 임계치(기본 0.67) 기준으로 합의 판정
- 합의 도달 시 해당 시그널로 거래; 미도달 시 HOLD

두 전략은 **동시에** 운용되며, 사용자가 블렌드 비율을 조정할 수 있습니다.

---

## 🤖 7개 에이전트

| 에이전트 | 역할 |
|----------|------|
| CollectorAgent | KRX 데이터 수집 (FinanceDataReader + KIS WebSocket) |
| PredictorAgent | LLM 기반 가격 예측 (Claude CLI / GPT-4o OAuth / Gemini CLI) |
| PortfolioManagerAgent | KIS API로 페이퍼/실거래 주문 실행 |
| NotifierAgent | Telegram Bot 알림 발송 |
| OrchestratorAgent | LangGraph 기반 전체 워크플로우 조율 |
| FastFlowAgent | 작업의 전체 흐름/우선순위를 빠르게 설계 |
| SlowMeticulousAgent | 상세 체크리스트·검증 게이트를 꼼꼼히 보강 |

---

## 🛠️ 기술 스택

| 레이어 | 기술 |
|--------|------|
| **Backend** | Python 3.11+, FastAPI, LangGraph |
| **LLM** | Anthropic Claude (CLI), OpenAI GPT-4o (OAuth), Google Gemini (CLI) |
| **Data** | FinanceDataReader (KRX 무료), KIS Developers API |
| **DB** | PostgreSQL 15+, Redis 7+ |
| **Frontend** | TypeScript, React 18, Vite, Tailwind CSS |
| **알림** | Telegram Bot API |

---

## 🚀 빠른 시작 (Docker 기반 권장)

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 입력 (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, KIS_*, TELEGRAM_*)

# 2. 컨테이너 빌드 및 실행 (API/UI + Orchestrator worker)
docker compose up -d --build postgres redis api worker ui

# 3. DB 스키마 초기화 (최초 1회)
docker compose run --rm api python scripts/db/init_db.py

# 4. 상태 확인
docker compose ps
curl http://localhost:8000/health
docker compose logs -f worker
```

접속:
- Dashboard: `http://localhost:5173`
- API Docs: `http://localhost:8000/docs`

로컬(비컨테이너) 실행 절차는 [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md)를 참조하세요.

---

## ⚙️ 코어 에이전트 MVP 실행

```bash
# Collector 일봉 수집 (MVP)
python -m src.agents.collector --tickers 005930,000660

# Collector 실시간 틱 수집 (KIS WebSocket)
python -m src.agents.collector --realtime --tickers 005930,000660 --duration-seconds 300

# Predictor (Claude 단일 인스턴스 + 규칙 폴백)
python -m src.agents.predictor --agent-id predictor_1 --strategy A --tickers 005930,000660

# PortfolioManager 주문 처리 예시
python -m src.agents.portfolio_manager --signals-json '[{"ticker":"005930","signal":"BUY","strategy":"A"}]'

# Orchestrator 단일 사이클 (수집 -> 예측 -> 주문 -> 알림)
python -m src.agents.orchestrator --tickers 005930,000660

# Orchestrator 토너먼트 모드 (Predictor 5개 인스턴스)
python -m src.agents.orchestrator --tournament --tickers 005930,000660

# Orchestrator 토너먼트 고급 실행 (롤링 윈도우/최소 샘플 override)
python -m src.agents.orchestrator --tournament --tickers 005930,000660 --tournament-rolling-days 7 --tournament-min-samples 5

# Orchestrator 합의 모드 (Strategy B Debate)
python -m src.agents.orchestrator --consensus --tickers 005930,000660

# Orchestrator 합의 모드 고급 실행 (다라운드 + 임계치 override)
python -m src.agents.orchestrator --consensus --tickers 005930,000660 --consensus-rounds 3 --consensus-threshold 0.72

# Orchestrator 블렌딩 모드 (Strategy A winner + Strategy B consensus)
python -m src.agents.orchestrator --blend --tickers 005930,000660

# Orchestrator RL 모드 (Yahoo history seed -> KIS tick 선수집 -> RL 학습/평가)
python -m src.agents.orchestrator --rl --tickers 005930,000660 --rl-yahoo-seed-range 10y --rl-tick-collection-seconds 30

# RL lane 단독 실행 (기본: Yahoo history seed -> KIS tick 선수집 -> RL 학습 -> 평가 -> 추론)
python scripts/run_rl_trading.py --tickers 005930,000660

# RL signal을 주문 파이프까지 전달
python scripts/run_rl_trading.py --tickers 005930 --execute-orders

# Docker worker 단독 실행/재시작
docker compose up -d worker
docker compose restart worker

# 일일 페이퍼 리포트 자동 발송(예: 17:10 KST)
# .env:
# ORCH_ENABLE_DAILY_REPORT=true
# ORCH_DAILY_REPORT_HOUR=17
# ORCH_DAILY_REPORT_MINUTE=10

# 실거래 전환 사전 점검
# (security/risk 운영 감사 자동 실행 + readiness 평가)
docker compose run --rm api python scripts/preflight_real_trading.py

# 운영 감사만 개별 실행
docker compose run --rm api python scripts/security_audit.py
docker compose run --rm api python scripts/validate_risk_rules.py

# Phase 6(30일 페이퍼/고변동성/부하) 자동 검증
docker compose run --rm api python scripts/run_phase6_paper_validation.py --days 30

# Phase 1~7 완료율 자동 검증
docker compose run --rm api python scripts/validate_all_phases.py
```

## ✅ 테스트 실행

```bash
# 1) 단위 테스트 (핵심 로직: blending / consensus fallback / risk guard)
python3 -m unittest discover -s test -p 'test_*.py' -v

# 2) 백엔드 컴파일 검증
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall src scripts test

# 3) 통합 스모크 테스트 (Redis/API 실행 필요)
python3 scripts/smoke_test.py --skip-telegram

# 4) Docker 런타임 기준 스모크 테스트
docker compose up -d --build postgres redis api worker ui
docker compose run --rm api python scripts/db/init_db.py
docker compose run --rm api python scripts/security_audit.py
docker compose run --rm api python scripts/validate_risk_rules.py
docker compose run --rm api python scripts/run_phase6_paper_validation.py --days 30
docker compose exec -T api python scripts/smoke_test.py --skip-telegram
docker compose run --rm api python scripts/preflight_real_trading.py
docker compose run --rm api python scripts/validate_all_phases.py
docker compose run --rm api python -m unittest discover -s test -p 'test_*.py' -v
docker compose run --rm ui npm run build

# 5) RL trading lane 전용 검증
python3 scripts/validate_rl_trading.py

# 6) Python 3.11 호환성 검증 (RL)
./scripts/test_rl_py311.sh
```

---

## 📂 문서 목록

| 문서 | 내용 |
|------|------|
| [docs/AGENTS.md](docs/AGENTS.md) | 에이전트 명세, 메시지 컨트랙트, 전략 라이프사이클 |
| [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md) | 설치 및 최초 부팅 절차 |
| [docs/HEARTBEAT.md](docs/HEARTBEAT.md) | 에이전트 헬스 모니터링 규격 |
| [docs/IDENTITY.md](docs/IDENTITY.md) | 에이전트 페르소나 및 LLM 프롬프트 |
| [docs/MEMORY.md](docs/MEMORY.md) | 메모리 시스템 설계 (Redis/PostgreSQL) |
| [docs/SOUL.md](docs/SOUL.md) | 핵심 가치관 및 행동 철학 |
| [docs/TOOLS.md](docs/TOOLS.md) | 에이전트 도구 목록 및 접근 제어 |
| [docs/USER.md](docs/USER.md) | 사용자 페르소나 및 대시보드 UX 기대치 |
| [docs/REAL_TRADING_GUIDE.md](docs/REAL_TRADING_GUIDE.md) | 실거래 전환/롤백 운영 절차 |
| [docs/api_spec.md](docs/api_spec.md) | REST API 엔드포인트 명세 |
| [.agent/tech_stack.md](.agent/tech_stack.md) | 허용된 기술 스택 제약 |
| [.agent/roadmap.md](.agent/roadmap.md) | 프로젝트 로드맵 |
| [architecture.md](architecture.md) | 전체 아키텍처 설계 |

---

## ⚠️ 면책 조항

이 시스템은 교육 및 연구 목적으로 개발되었습니다.
실제 투자에서 발생하는 손익에 대해 개발자는 책임을 지지 않습니다.
실거래 모드 활성화 전 충분한 페이퍼 트레이딩 검증을 권장합니다.

---

## 확장 기능 상태 메모

- 강화학습 트레이딩은 기존 Strategy A/B를 대체하지 않고 구조에 추가되는 기능입니다.
- 검색/스크래핑 리서치 파이프라인도 기존 코어 트레이딩 위에 추가되는 기능입니다.
- 현재 README 기준 상태 표시는 두 확장 기능 모두 `통합 테스트 진행 중`입니다.
- 추후 검증이 완료되면 이 상태 문구는 운영 반영 상태에 맞게 갱신해야 합니다.

### 확장 방향

- RL Trading Lane: 데이터셋/피처 -> 학습 환경 -> 평가 -> 정책 추론 -> PortfolioManager 연결
- Search Lane: `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI 파싱 -> Claude CLI 추론`

*Last updated: 2026-03-12*
