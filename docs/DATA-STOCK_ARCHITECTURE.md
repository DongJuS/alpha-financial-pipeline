

QA 문서가 아니라 직접 코드를 읽어서 파악하겠습니다. 
주요 소스 파일들을 하나씩 확인하겠습니다.먼저 프로젝트의 소스 구조를 직접 확인하겠습니다.
이제 핵심 파일들을 직접 읽겠습니다.
이제 나머지 핵심 저장소 코드들을 읽겠습니다.
이제 DB 모델, 쿼리, Redis, S3 클라이언트 코드를 읽겠습니다.
이제 RL 관련 파일 저장 경로와 DB 초기화, marketplace 쿼리도 확인하겠습니다.
마지막으로 search_agent와 gen_collector도 확인하겠습니다.모든 핵심 코드를 직접 읽었습니다. 
아래에 코드 기반으로 파악한 데이터 수집/저장 경로를 정리합니다.

---

## 데이터 수집 소스 (코드 기반)

### 1. CollectorAgent (`src/agents/collector.py`)

수집 방식이 3가지로 나뉩니다.

**일봉 수집 (`collect_daily_bars`)**: `FinanceDataReader.DataReader(ticker, start_date)`로 KRX 종목의 OHLCV를 가져옵니다. 저장 경로는 PostgreSQL `market_data` 테이블 (upsert), Redis 캐시 (`redis:cache:latest_ticks:{ticker}`, `redis:cache:realtime_series:{ticker}`), S3/MinIO Parquet (`daily_bars/date=YYYY-MM-DD/*.parquet`) 3곳입니다. 수집 후 Redis Pub/Sub `redis:topic:market_data` 채널로 `data_ready` 이벤트를 발행합니다.

**Yahoo 일봉 수집 (`collect_yahoo_daily_bars`)**: Yahoo Finance Chart API (`query1.finance.yahoo.com/v8/finance/chart/`) 또는 yfinance 라이브러리 fallback으로 수집합니다. 저장은 PostgreSQL `market_data`에만 합니다.

**실시간 틱 수집 (`collect_realtime_ticks`)**: KIS WebSocket(`H0STCNT0` TR)으로 실시간 체결가를 수신합니다. 100건 또는 1초마다 배치로 PostgreSQL `market_data`에 flush하고, 매 틱마다 Redis 캐시 갱신 + Pub/Sub 발행합니다. WebSocket 실패 시 FDR 일봉으로 fallback합니다.

### 2. IndexCollector (`src/agents/index_collector.py`)

`KISPaperApiClient.fetch_index_quote()`로 KOSPI(0001), KOSDAQ(1001) 지수를 KIS REST API에서 조회합니다. 저장은 Redis `redis:cache:market_index` 키에 TTL 120초로 캐싱합니다. DB에는 저장하지 않습니다.

### 3. MacroCollector (`src/agents/macro_collector.py`)

`FinanceDataReader.DataReader()`로 해외지수 6종(S&P500, NASDAQ, DJI, N225, HSI, SSEC), 환율 4종(USD/KRW, EUR/KRW, JPY/KRW, CNY/KRW), 원자재 3종(금, WTI, 구리)을 수집합니다. 저장은 PostgreSQL `macro_indicators` 테이블 upsert + Redis `redis:cache:macro:{category}` (TTL 1시간) 캐싱입니다.

### 4. StockMasterCollector (`src/agents/stock_master_collector.py`)

`FinanceDataReader.StockListing("KRX")`로 KRX 전종목(~2,650개) + `StockListing("ETF/KR")`로 ETF 목록을 수집합니다. 저장은 PostgreSQL `stock_master` 테이블 upsert + Redis 3개 캐시(`redis:cache:stock_master`, `redis:cache:sector_map`, `redis:cache:etf_list`, 각 TTL 24시간)입니다.

### 5. GenCollectorAgent (`src/agents/gen_collector.py`)

자체 Gen REST API 서버(`/gen/tickers`, `/gen/ohlcv/{ticker}`, `/gen/quotes`, `/gen/index`, `/gen/macro`)에서 랜덤 시세 데이터를 수집합니다. 파이프라인 정합성 테스트용이며, 저장 경로는 CollectorAgent와 동일(PostgreSQL `market_data` + Redis + S3 + Pub/Sub)입니다.

### 6. KIS Broker (`src/brokers/kis.py`)

KIS REST API에서 잔고 조회(`inquire_balance`), 일별 체결 조회(`inquire_daily_ccld`)로 데이터를 수집합니다. 주문 실행 시 PostgreSQL `broker_orders` 테이블에 주문 기록을 INSERT/UPDATE하고, `trading_accounts` 테이블에 계좌 정보를 upsert합니다.

### 7. Yahoo Finance 서비스 (`src/services/yahoo_finance.py`)

`query1/query2.finance.yahoo.com` Chart API로 OHLCV를 가져오며, 실패 시 Playwright 브라우저로 fallback합니다. 이 모듈 자체는 저장하지 않고 `YahooDailyBar` 객체를 반환합니다(호출자가 저장).

### 8. SearXNG Client (`src/utils/searxng_client.py`)

`SearXNGClient.search()`로 SearXNG 인스턴스에 JSON API 요청을 보내 웹 검색 결과를 가져옵니다. 반환만 하고 직접 저장하지 않습니다. SearchAgent/SearchRunner가 호출합니다.

### 9. SearchAgent (`src/agents/search_agent.py`)

현재 stub 구현 상태입니다. Tavily Search + ScrapeGraphAI 기반 리서치 구조가 설계되어 있지만, 실제 API 호출은 TODO입니다.

---

## 데이터 저장소 (코드 기반)

### PostgreSQL (`src/utils/db_client.py` — asyncpg 풀)

`DATABASE_URL` 환경변수로 연결하며, 커넥션 풀 max_size=30입니다. 쿼리 코드에서 확인된 **테이블 목록**:

| 테이블 | 용도 | 쓰는 곳 |
|---|---|---|
| `market_data` | OHLCV 시세 (일봉/틱), `(ticker, timestamp_kst, interval)` 유니크 | collector, gen_collector |
| `predictions` | 예측 시그널 (A/B/RL/S/BLEND) | predictor |
| `debate_transcripts` | Strategy B 토론 내용 | strategy_b |
| `portfolio_positions` | 보유 포지션, `(ticker, account_scope)` 유니크 | portfolio_manager |
| `trade_history` | 매매 체결 기록 | paper_trading, kis broker |
| `broker_orders` | 브로커 주문 상세 | kis broker |
| `trading_accounts` | 계좌 정보 (paper/real), `account_scope` 유니크 | kis broker |
| `account_snapshots` | 계좌 상태 스냅샷 (시계열) | account_state |
| `portfolio_config` | 포트폴리오 설정 (blend ratio, 리스크 한도) | portfolio_manager |
| `model_role_configs` | LLM 모델-역할 매핑 | config API |
| `predictor_tournament_scores` | Strategy A 토너먼트 점수 | strategy_a_tournament |
| `agent_heartbeats` | 에이전트 상태 기록 | 모든 에이전트 |
| `notification_history` | 알림 이력 | notifier |
| `real_trading_audit` | 실거래 전환 감사 로그 | audit API |
| `operational_audits` | 운영 감사 로그 | audit |
| `paper_trading_runs` | 모의투자 시뮬레이션 결과 | paper_trading |
| `stock_master` | KRX 전종목 마스터 | stock_master_collector |
| `theme_stocks` | 테마 → 종목 매핑 | marketplace |
| `macro_indicators` | 매크로 지표 | macro_collector |
| `daily_rankings` | 일별 랭킹 (시총, 거래량 등) | ranking_calculator |
| `watchlist` | 사용자 관심 종목 | watchlist API |

### Redis (`src/utils/redis_client.py` — aioredis 싱글턴)

`REDIS_URL` 환경변수로 연결합니다.

**캐시 키:**
- `redis:cache:latest_ticks:{ticker}` (TTL 60초) — 최신 시세
- `redis:cache:realtime_series:{ticker}` (TTL 1시간, 최대 300건 리스트) — 실시간 시계열
- `redis:cache:market_index` (TTL 120초) — KOSPI/KOSDAQ 지수
- `redis:cache:stock_master` (TTL 24시간) — 전종목 마스터
- `redis:cache:sector_map` (TTL 24시간) — 섹터 매핑
- `redis:cache:etf_list` (TTL 24시간) — ETF 목록
- `redis:cache:macro:{category}` (TTL 1시간) — 매크로 지표
- `redis:cache:rankings:{ranking_type}` (TTL 5분) — 랭킹
- `heartbeat:{agent_id}` (TTL 90초) — 에이전트 생존 신호
- `kis:oauth_token:{scope}` (TTL 23시간) — KIS OAuth 토큰
- `memory:macro_context` (TTL 4시간) — 거시경제 컨텍스트

**Pub/Sub 채널:**
- `redis:topic:market_data` — 시세 데이터 이벤트
- `redis:topic:signals` — 예측 신호
- `redis:topic:orders` — 주문 이벤트
- `redis:topic:heartbeat` — 하트비트
- `redis:topic:alerts` — 알림

### S3/MinIO (`src/utils/s3_client.py` + `src/services/datalake.py`)

`S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME` 환경변수로 연결합니다. boto3 기반이며, Hive-style 파티셔닝으로 Parquet 파일을 저장합니다.

**저장 데이터 유형** (`datalake.py`의 `DataType`):
- `daily_bars/date=YYYY-MM-DD/*.parquet` — 일봉 OHLCV
- `tick_data/date=.../*.parquet` — 틱 데이터
- `predictions/date=.../*.parquet` — 예측 시그널
- `orders/date=.../*.parquet` — 주문 기록
- `blend_results/date=.../*.parquet` — 블렌딩 결과
- `debate_transcripts/` — 토론 트랜스크립트
- `rl_episodes/` — RL 에피소드

### 로컬 파일 시스템 (`artifacts/rl/`)

RL 정책 저장소 (`src/agents/rl_policy_store_v2.py`):
- `artifacts/rl/models/<algorithm>/<ticker>/<policy_id>.json` — 학습된 RL 정책
- `artifacts/rl/models/registry.json` — 정책 레지스트리 (활성 정책 관리)
- `artifacts/rl/active_policies.json` — V1 레거시 호환용

실험 메타데이터 (`src/utils/experiment_tracker.py`):
- `config/experiments/<domain>/<run_id>.json` — 실험 결과 기록

---

## 전체 데이터 흐름 요약

```
[수집 소스]                    [저장소]
                              
FinanceDataReader ──┐         ┌── PostgreSQL (market_data)
Yahoo Finance ──────┤         ├── Redis (캐시 + Pub/Sub)
KIS REST API ───────┼── 수집 ─┼── S3/MinIO (Parquet)
KIS WebSocket ──────┤    │    └── 로컬 파일 (artifacts/rl/)
Gen Server API ─────┤    │
SearXNG ────────────┘    │
                         │
                    ┌────┘
                    ▼
[가공 에이전트]
Predictor (A/B/RL/S) → predictions 테이블 + S3
Blending → blend_results + S3
Portfolio Manager → portfolio_positions, trade_history
KIS Broker → broker_orders, trading_accounts
RL Training → artifacts/rl/models/
Experiment Tracker → config/experiments/
```