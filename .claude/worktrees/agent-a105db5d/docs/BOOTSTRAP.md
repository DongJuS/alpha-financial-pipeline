# 🚀 BOOTSTRAP.md — 시스템/에이전트 최초 부팅 절차

> 시스템을 처음 설치하거나, 장애 복구 후 재시작하거나, 새 환경에 배포할 때 이 절차를 따르세요.

---

## ✅ 사전 요구사항 체크리스트

```
[ ] Python 3.11+
[ ] Node.js 20+
[ ] PostgreSQL 15+
[ ] Redis 7+
[ ] Docker (권장, 컨테이너 실행용)
[ ] KIS Developers 계좌 및 앱 등록 완료
[ ] Anthropic API 키 발급
[ ] OpenAI API 키 발급
[ ] Google Gemini API 키 발급
[ ] Telegram Bot 생성 및 Chat ID 확인
[ ] claude CLI 설치: npm install -g @anthropic-ai/claude-code
[ ] gemini CLI 설치: (공식 Google Gemini CLI 문서 참조)
```

---

## 1. 환경변수 설정

`.env.example`을 복사하여 `.env` 파일을 생성합니다.

```bash
cp .env.example .env
```

`.env` 파일의 모든 항목을 채웁니다:

```dotenv
# ─── App ───────────────────────────────────────────────
NODE_ENV=development
PORT=8000
APP_URL=http://localhost:8000

# ─── Database ──────────────────────────────────────────
DATABASE_URL=postgresql://alpha_user:password@localhost:5432/alpha_db

# ─── Redis ─────────────────────────────────────────────
REDIS_URL=redis://localhost:6379

# ─── LLM API Keys ──────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...

# ─── KIS Developers (한국투자증권) ───────────────────────
KIS_APP_KEY=PSxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_ACCOUNT_NUMBER=XXXXXXXXXX-XX
KIS_IS_PAPER_TRADING=true          # 반드시 true로 시작

# ─── Telegram ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHijklMNOpqrSTUvwxyz
TELEGRAM_CHAT_ID=123456789

# ─── Strategy ──────────────────────────────────────────
STRATEGY_A_PREDICTOR_COUNT=5
STRATEGY_BLEND_RATIO=0.5           # 0.0=전략A만, 1.0=전략B만

# ─── Logging ───────────────────────────────────────────
LOG_LEVEL=INFO
```

> ⚠️ `.env` 파일은 절대 git에 커밋하지 마세요.

---

## 2A. Docker 기반 부팅 (권장)

```bash
# 1) 컨테이너 실행
docker compose up -d --build postgres redis api ui

# 2) DB 스키마 생성 (최초 1회)
docker compose run --rm api python scripts/db/init_db.py

# 3) 상태 확인
docker compose ps
curl http://localhost:8000/health
```

접속 URL:
- Frontend: `http://localhost:5173`
- Backend API Docs: `http://localhost:8000/docs`

중지:
```bash
docker compose down
```

---

## 2. Python 의존성 설치

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. 데이터베이스 초기화

```bash
# PostgreSQL 데이터베이스 및 사용자 생성
psql -U postgres -c "CREATE DATABASE alpha_db;"
psql -U postgres -c "CREATE USER alpha_user WITH PASSWORD 'password';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE alpha_db TO alpha_user;"

# 스키마 마이그레이션 (테이블 생성)
python scripts/db/init_db.py
```

**생성되는 테이블 순서:**
1. `market_data`
2. `predictions`
3. `predictor_tournament_scores`
4. `portfolio_positions`
5. `trade_history`
6. `agent_heartbeats`
7. `debate_transcripts`
8. `collector_errors`

---

## 4. KIS Developers API 설정

### 4-1. 앱 등록 (최초 1회)
1. developers.koreainvestment.com 접속
2. 계정 생성 또는 로그인
3. "앱 등록" → **모의투자(페이퍼)** 선택
4. 발급된 `AppKey`와 `AppSecret`을 `.env`에 입력

### 4-2. OAuth2 토큰 최초 발급
```bash
python scripts/kis_auth.py --init
```
- 토큰이 Redis `kis:oauth_token`에 저장됩니다
- 이후 매일 06:00 KST에 자동 갱신됩니다

### 4-3. 연결 테스트
```bash
python scripts/kis_auth.py --test
```

**KIS OAuth 엔드포인트:**
- 페이퍼: `POST https://openapivts.koreainvestment.com/oauth2/tokenP`
- 실거래: `POST https://openapi.koreainvestment.com/oauth2/tokenP`

---

## 5. KRX 휴장일 캘린더 초기화

```bash
python scripts/fetch_krx_holidays.py --year 2026
```

---

## 6. LLM CLI 설치 확인

```bash
claude --version                              # Claude CLI 확인
gemini --version                              # Gemini CLI 확인
python scripts/test_llm_connections.py        # 3종 LLM 연결 테스트
# 출력: "Claude: OK | GPT-4o: OK | Gemini: OK"
```

---

## 7. Frontend 설치

```bash
cd ui && npm install
```

---

## 8. 시스템 첫 부팅 순서

```bash
# Step 1: 인프라 확인
redis-server &
pg_isready

# Step 2: CollectorAgent 시작
# (권장) KIS WebSocket 실시간 틱 수집
python -m src.agents.collector --realtime --tickers 005930,000660 --duration-seconds 600

# 또는 일봉 수집만 수행
python -m src.agents.collector --tickers 005930,000660

# Step 3: 헬스 확인
python scripts/health_check.py --agent collector

# Step 4: OrchestratorAgent 시작
python -m src.agents.orchestrator

# (Docker 권장) Orchestrator worker 루프 실행
docker compose up -d worker
docker compose logs -f worker

# Step 5: 전체 헬스 확인
python scripts/health_check.py --all

# Step 6: Frontend 시작
cd ui && npm run dev
# http://localhost:5173 접속

# Step 7: 스모크 테스트
python scripts/smoke_test.py
```

---

## 9. 페이퍼 → 실거래 전환 체크리스트

```
[ ] 최소 30일 페이퍼 트레이딩 성과 기록 보유
[ ] `scripts/run_phase6_paper_validation.py --days 30` 최근 통과 이력 보유
[ ] 서킷브레이커 동작 테스트 완료
[ ] 최대 포지션 비중 제한 동작 확인
[ ] `scripts/validate_risk_rules.py` 최근 통과 이력 보유
[ ] `scripts/security_audit.py` 최근 통과 이력 보유
[ ] Telegram 알림 정상 수신 확인
[ ] KIS 실거래 계좌 잔고 확인
```

전환 시 `.env`에서 `KIS_IS_PAPER_TRADING=false`로 변경 후 재시작합니다.
권장: 전환 직전 `python scripts/preflight_real_trading.py`를 실행해 운영 감사 + readiness를 동시에 확인합니다.
전체 완료 검증은 `python scripts/validate_all_phases.py`를 사용합니다.

---

## 10. 주요 스크립트 목록

| 스크립트 | 용도 |
|---------|------|
| `scripts/db/init_db.py` | DB 스키마 초기화 |
| `scripts/kis_auth.py` | KIS OAuth 토큰 관리 |
| `scripts/fetch_krx_holidays.py` | KRX 휴장일 갱신 |
| `scripts/health_check.py` | 에이전트 헬스 확인 |
| `scripts/run_dual_execution.py` | Fast/Slow 2-에이전트 자동 실행 계획 생성 |
| `scripts/run_orchestrator_worker.py` | Docker/운영 Orchestrator 루프 실행기 |
| `scripts/preflight_real_trading.py` | 실거래 전환 readiness 사전 점검 |
| `scripts/security_audit.py` | 저장소 시크릿/`.env` 추적 보안 감사 |
| `scripts/validate_risk_rules.py` | 리스크 규칙(서킷브레이커/포지션 한도) 자동 검증 |
| `scripts/run_phase6_paper_validation.py` | 30일 페이퍼/고변동성/부하 자동 검증 및 기록 |
| `scripts/validate_all_phases.py` | Phase 1~7 완료율 자동 검증 |
| `scripts/test_llm_connections.py` | LLM API 연결 테스트 |
| `scripts/smoke_test.py` | 전체 플로우 스모크 테스트 |

---

## 선택적 확장 스택 메모

### 강화학습 트레이딩 확장

- 코어 트레이딩 스택을 먼저 기동한 뒤 추가합니다.
- 데이터셋/피처 생성 -> 학습/평가 -> 정책 추론 순서로 붙이는 것을 기본으로 봅니다.
- 정책 출력은 기존 `PortfolioManager` 입력 형식과 정합성을 맞춰야 합니다.

### 검색/스크래핑 리서치 확장

- 검색은 Tavily 대신 `SearXNG`를 사용합니다.
- 파이프라인은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI` 로 구성합니다.
- 이 레이어는 검색과 구조화 전용이며 직접 주문을 실행하지 않습니다.

*Last updated: 2026-03-12*

