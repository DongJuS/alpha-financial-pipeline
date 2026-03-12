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

# 2. 컨테이너 빌드 및 실행
docker compose up -d --build postgres redis api ui

# 3. DB 스키마 초기화 (최초 1회)
docker compose run --rm api python scripts/db/init_db.py

# 4. 상태 확인
docker compose ps
curl http://localhost:8000/health
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

*Last updated: 2026-03-12*
