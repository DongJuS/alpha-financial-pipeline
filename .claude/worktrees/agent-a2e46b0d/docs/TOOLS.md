# 🔧 TOOLS.md — 에이전트가 사용 가능한 도구 목록 및 사용법

> 이 파일은 시스템의 모든 도구에 대한 정식 카탈로그입니다.
> 각 에이전트는 여기에 명시된 도구만 사용할 수 있으며, 접근 권한을 반드시 확인하십시오.

---

## 🗝️ 도구 접근 제어 매트릭스

| 도구 | Collector | Predictor | Portfolio | Notifier | Orchestrator |
|------|:---------:|:---------:|:---------:|:--------:|:------------:|
| `fdr_fetch_ohlcv` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `fdr_fetch_tickers` | ✅ | ❌ | ❌ | ❌ | ✅ |
| `krx_market_calendar` | ✅ | ❌ | ❌ | ❌ | ✅ |
| `kis_get_quote` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `kis_websocket_ticks` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `kis_place_order` | ❌ | ❌ | ✅ **ONLY** | ❌ | ❌ |
| `kis_get_balance` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `kis_refresh_token` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `llm_claude_cli` | ❌ | ✅ | ❌ | ❌ | ✅ |
| `llm_openai_api` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `llm_gemini_cli` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `redis_publish` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `redis_subscribe` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `redis_get` / `redis_set` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `postgres_read` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `postgres_write` | ✅ | ✅ | ✅ | ❌ | ✅ |
| `telegram_send` | ❌ | ❌ | ❌ | ✅ **ONLY** | ❌ |

> ⚠️ **`kis_place_order`는 PortfolioManagerAgent만 호출할 수 있습니다.**
> ⚠️ **`telegram_send`는 NotifierAgent만 호출할 수 있습니다.**

---

## 📊 데이터 수집 도구

### `fdr_fetch_ohlcv`
- **설명:** FinanceDataReader를 통해 KRX 주식 OHLCV 일봉 데이터 조회
- **접근 권한:** CollectorAgent
- **레이트 리밋:** ~100 req/hour (무료, API 키 불필요)
- **사용 예시:**
```python
import FinanceDataReader as fdr

# 삼성전자 일봉 (최근 30일)
df = fdr.DataReader('005930', '2026-02-10', '2026-03-12')

# KOSPI 지수
df = fdr.DataReader('KS11', '2026-01-01')

# KOSDAQ 지수
df = fdr.DataReader('KQ11', '2026-01-01')
```
- **에러 처리:** 요청 실패 시 `collector_errors` 테이블에 기록, 마지막 성공 캐시 유지

---

### `fdr_fetch_tickers`
- **설명:** KRX 전체 종목 코드 및 종목명 목록 조회
- **접근 권한:** CollectorAgent, OrchestratorAgent
- **사용 예시:**
```python
import FinanceDataReader as fdr

kospi = fdr.StockListing('KOSPI')   # KOSPI 전체 종목
kosdaq = fdr.StockListing('KOSDAQ') # KOSDAQ 전체 종목
```

---

### `krx_market_calendar`
- **설명:** KRX 공식 휴장일 캘린더 조회 (REST API, 공개)
- **접근 권한:** CollectorAgent, OrchestratorAgent
- **엔드포인트:** `http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd`
- **캐싱:** 조회 결과를 Redis `krx:holidays:{year}` 에 TTL 24시간으로 저장
- **에러 처리:** 조회 실패 시 한국 공휴일 법정 목록을 하드코딩된 폴백으로 사용

---

### `kis_get_quote`
- **설명:** KIS Developers API를 통해 종목 실시간 시세 조회
- **접근 권한:** CollectorAgent, PortfolioManagerAgent
- **엔드포인트:**
  - 페이퍼: `https://openapivts.koreainvestment.com/uapi/domestic-stock/v1/quotations/inquire-price`
  - 실거래: `https://openapi.koreainvestment.com/uapi/domestic-stock/v1/quotations/inquire-price`
- **헤더:** `tr_id: FHKST01010100`
- **레이트 리밋:** 20 req/sec

---

### `kis_websocket_ticks`
- **설명:** KIS WebSocket을 통해 장중 실시간 틱 데이터 수신
- **접근 권한:** CollectorAgent
- **연결 URL:**
  - 페이퍼: `ws://ops.koreainvestment.com:31000`
  - 실거래: `ws://ops.koreainvestment.com:21000`
- **제약:** 계좌당 WebSocket 연결 1개
- **사용 시간:** 장중 (09:00–15:30 KST)만 활성화

---

## 💹 트레이딩 도구 (PortfolioManagerAgent 전용)

### `kis_place_order` ⚠️ 제한적 접근

> **이 도구는 PortfolioManagerAgent만 호출할 수 있습니다.**
> 다른 에이전트가 호출을 시도하면 즉시 예외를 발생시킵니다.

- **설명:** KIS API를 통해 매수/매도 주문 실행
- **엔드포인트:**
  - 페이퍼 매수: `POST https://openapivts.koreainvestment.com/uapi/domestic-stock/v1/trading/order-cash` (tr_id: `VTTC0802U`)
  - 실거래 매수: `POST https://openapi.koreainvestment.com/uapi/domestic-stock/v1/trading/order-cash` (tr_id: `TTTC0802U`)
  - 페이퍼 매도: tr_id `VTTC0801U`
  - 실거래 매도: tr_id `TTTC0801U`
- **필수 헤더:** `Authorization: Bearer {token}`, `appkey`, `appsecret`
- **주문 전 검증:** 리스크 규칙 통과 여부 반드시 확인 후 호출

---

### `kis_get_balance`
- **설명:** 계좌 잔고 및 보유 종목 조회
- **접근 권한:** PortfolioManagerAgent

---

### `kis_refresh_token`
- **설명:** KIS OAuth2 토큰 갱신
- **접근 권한:** PortfolioManagerAgent
- **스케줄:** 매일 06:00 KST 자동 갱신
- **토큰 저장:** Redis `kis:oauth_token`, TTL 23시간

---

## 🤖 LLM 도구

### `llm_claude_cli`
- **설명:** Claude CLI를 subprocess로 호출하여 LLM 추론 수행
- **접근 권한:** PredictorAgent (인스턴스 1, 2), OrchestratorAgent
- **모델:** `claude-sonnet-4-6`
- **사용 예시:**
```python
import subprocess
import json

result = subprocess.run(
    ["claude", "-p", prompt, "--output-format", "json"],
    capture_output=True, text=True, timeout=60
)
response = json.loads(result.stdout)
```
- **타임아웃:** 60초
- **에러 처리:** CLI 실패 시 Anthropic SDK로 폴백

---

### `llm_openai_api`
- **설명:** OpenAI API (OAuth)를 통해 GPT-4o 호출
- **접근 권한:** PredictorAgent (인스턴스 3, 4)
- **모델:** `gpt-4o`
- **사용 예시:**
```python
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
response = await client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "system", "content": system_prompt},
              {"role": "user", "content": user_prompt}],
    response_format={"type": "json_object"},
    temperature=0.3
)
```
- **타임아웃:** 60초

---

### `llm_gemini_cli`
- **설명:** Gemini CLI를 subprocess로 호출
- **접근 권한:** PredictorAgent (인스턴스 5)
- **모델:** `gemini-1.5-pro`
- **사용 예시:**
```python
import subprocess
import json

result = subprocess.run(
    ["gemini", "-p", prompt, "-m", "gemini-1.5-pro"],
    capture_output=True, text=True, timeout=60,
    env={**os.environ, "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY")}
)
```
- **타임아웃:** 60초

---

## 📨 메시지 버스 도구

### `redis_publish` / `redis_subscribe`
- **설명:** Redis Pub/Sub을 통한 에이전트 간 비동기 메시지 전달
- **접근 권한:** 모든 에이전트
- **채널 목록:** `docs/AGENTS.md` Redis 채널 네이밍 규칙 참조

### `redis_get` / `redis_set`
- **설명:** Redis 키-값 저장소 (캐시, 세션 상태 등)
- **접근 권한:** 모든 에이전트
- **중요 키:**
  - `krx:holidays:{year}` — KRX 휴장일 (TTL: 24h)
  - `kis:oauth_token` — KIS 토큰 (TTL: 23h)
  - `heartbeat:{agent_id}` — 에이전트 헬스비트 (TTL: 90s)
  - `memory:macro_context` — 거시경제 컨텍스트 (TTL: 4h)
  - `redis:cache:latest_ticks:{ticker}` — 최신 틱 데이터 (TTL: 60s)

---

## 🗄️ 데이터베이스 도구

### `postgres_read`
- **설명:** PostgreSQL에서 데이터 조회
- **접근 권한:** 모든 에이전트
- **드라이버:** `asyncpg`

### `postgres_write`
- **설명:** PostgreSQL에 데이터 삽입/수정
- **접근 권한:** CollectorAgent, PredictorAgent, PortfolioManagerAgent, OrchestratorAgent
- **주요 테이블:**

| 테이블 | 주 쓰기 에이전트 | 용도 |
|--------|-----------------|------|
| `market_data` | Collector | OHLCV 일봉/틱 데이터 |
| `predictions` | Predictor | 예측 시그널 기록 |
| `predictor_tournament_scores` | Orchestrator | 토너먼트 점수 |
| `portfolio_positions` | PortfolioManager | 현재 보유 포지션 |
| `trade_history` | PortfolioManager | 거래 이력 |
| `agent_heartbeats` | 모든 에이전트 | 헬스비트 로그 |
| `debate_transcripts` | Orchestrator | Strategy B 토론 전문 |
| `collector_errors` | Collector | 수집 오류 로그 |

---

## 📲 알림 도구

### `telegram_send` ⚠️ 제한적 접근

> **이 도구는 NotifierAgent만 호출할 수 있습니다.**

- **설명:** Telegram Bot API를 통해 메시지 발송
- **라이브러리:** `python-telegram-bot`
- **환경변수:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **레이트 리밋:** 채널당 시간당 최대 10건
- **사용 예시:**
```python
from telegram import Bot

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
await bot.send_message(
    chat_id=os.getenv("TELEGRAM_CHAT_ID"),
    text=message,
    parse_mode="Markdown"
)
```

---

## ⚠️ 무료 API 제약 요약

| API | 레이트 리밋 | 실시간 여부 | 주의사항 |
|-----|------------|------------|---------|
| FinanceDataReader | ~100 req/hour | EOD만 (실시간 불가) | KRX 휴장일 자동 제외 안 됨 |
| KRX 정보데이터시스템 | 1 req/sec | 지연 데이터 | HTML 스크래핑 주의 |
| KIS 페이퍼 트레이딩 | 20 req/sec | WebSocket 실시간 | 계좌당 연결 1개 |
| KIS 실거래 | 20 req/sec | WebSocket 실시간 | 실제 자금 관련, 신중히 |

---

*Last updated: 2026-03-12*
