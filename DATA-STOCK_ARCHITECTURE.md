# 📊 DATA-STOCK_ARCHITECTURE — 데이터 수집·저장 경로 상세 설계

> 이 문서는 시스템의 모든 데이터 수집 소스와 저장 경로를 코드 레벨에서 추적한 결과입니다.
> 전체 아키텍처 맵은 [architecture.md](architecture.md)를 참조하세요.

---

## 1. 데이터 수집 소스

### 1-1. CollectorAgent (`src/agents/collector.py`)

시스템의 핵심 데이터 수집기입니다. 3가지 수집 모드를 지원합니다.

#### 일봉 수집 (`collect_daily_bars`)

- **소스:** `FinanceDataReader.DataReader(ticker, start_date)` — KRX 전종목 OHLCV
- **종목 해석:** `FinanceDataReader.StockListing("KRX")` 로 KOSPI/KOSDAQ 종목 목록 로드
- **수집 필드:** ticker, name, market, timestamp_kst, open, high, low, close, volume, change_pct
- **저장:** PostgreSQL `market_data` + Redis 캐시 + S3 Parquet + Redis Pub/Sub 이벤트
- **스케줄:** APScheduler 크론 08:30 KST

#### Yahoo 일봉 수집 (`collect_yahoo_daily_bars`)

- **소스 1차:** Yahoo Finance Chart API (`query1.finance.yahoo.com/v8/finance/chart/{ticker}`)
- **소스 fallback:** `yfinance` 라이브러리 (`yf.download()`)
- **종목 변환:** 내부 티커 → Yahoo 심볼 (`005930` → `005930.KS`, KOSDAQ은 `.KQ`)
- **수집 범위:** `range_` 파라미터로 조절 (기본 10y)
- **저장:** PostgreSQL `market_data` 만 (Redis/S3 미사용 — **불일치 주의**)

#### 실시간 틱 수집 (`collect_realtime_ticks`)

- **소스:** KIS Developers WebSocket (`H0STCNT0` TR — 실시간 체결)
- **인증 흐름:** `kis_app_key/secret` → REST `/oauth2/Approval` → `approval_key` 발급 → WebSocket 접속
- **파싱:** `0|TR_ID|COUNT|field1^field2^...` 형식 패킷 → ticker/price/volume 추출
- **보정:** WebSocket 파싱 실패 시 REST API `FHKST01010100` (현재가 조회)로 보정
- **버퍼링:** 100건 또는 1초마다 배치 flush (매건 INSERT 대신)
- **저장:** PostgreSQL `market_data` (배치 flush) + Redis 캐시 (매 틱) + Redis Pub/Sub
- **S3 미사용** — 일봉과 불일치
- **장애 대응:** WebSocket 재연결 3회 초과 시 FDR 일봉 수집으로 fallback

#### Historical Bulk 수집 (`fetch_historical_ohlcv`)

- **일봉:** FDR `DataReader(ticker, start_date, end_date)` → PostgreSQL `market_data`
- **분봉:** KIS REST API `FHKST03010200` (분봉 차트) → 하루씩 순회 → PostgreSQL `market_data`
- **rate limit:** KIS API 초당 1회 제한 준수 (`asyncio.sleep(1.0)`)

### 1-2. IndexCollector (`src/agents/index_collector.py`)

- **소스:** KIS REST API `inquire-index-price` (시장 지수 조회)
- **수집 대상:** KOSPI(`0001`), KOSDAQ(`1001`)
- **저장:** Redis `redis:cache:market_index` (TTL 120초) — **DB 미저장**

### 1-3. MacroCollector (`src/agents/macro_collector.py`)

- **소스:** `FinanceDataReader.DataReader()` — 해외 지수, 환율, 원자재
- **수집 대상:**
  - 해외지수 6종: S&P500, NASDAQ, DJI, N225, HSI, SSEC
  - 환율 4종: USD/KRW, EUR/KRW, JPY/KRW, CNY/KRW
  - 원자재 3종: 금, WTI, 구리
- **저장:** PostgreSQL `macro_indicators` + Redis `redis:cache:macro:{category}` (TTL 1시간)

### 1-4. KrxStockMasterCollector (`src/agents/krx_stock_master_collector.py`)

- **소스:** `FinanceDataReader.StockListing("KRX")` + `StockListing("ETF/KR")`
- **수집 규모:** KRX 전종목 ~2,650개 + ETF
- **수집 필드:** ticker, name, market, sector, industry, market_cap, listing_date, is_etf, is_etn
- **저장:** PostgreSQL `krx_stock_master` + Redis 3개 캐시 (krx_stock_master, sector_map, etf_list — 각 TTL 24시간)

### 1-5. GenCollectorAgent (`src/agents/gen_collector.py`)

- **소스:** 자체 Gen REST API 서버 (`/gen/tickers`, `/gen/ohlcv/{ticker}`, `/gen/quotes`, `/gen/index`, `/gen/macro`)
- **용도:** 파이프라인 정합성 테스트용 (랜덤 시세 생성)
- **저장:** CollectorAgent와 동일 경로 (PostgreSQL + Redis + S3 + Pub/Sub)

### 1-6. KIS Broker (`src/brokers/kis.py`)

- **소스:** KIS Developers REST API
  - 잔고 조회: `TTTC8434R` (실전) / `VTTC8434R` (모의)
  - 일별 체결 조회: `TTTC8001R` / `VTTC8001R`
  - 현재가 조회: `FHKST01010100`
  - 주문: `TTTC0802U` (매수) / `TTTC0801U` (매도)
- **인증:** Redis `kis:oauth_token:{scope}` 에서 access_token 조회
- **저장:** PostgreSQL `broker_orders`, `trading_accounts`, `trade_history`

### 1-7. Yahoo Finance 서비스 (`src/services/yahoo_finance.py`)

- **소스:** `query1/query2.finance.yahoo.com/v8/finance/chart/` (JSON API)
- **fallback:** Playwright 브라우저 자동화 (Yahoo 페이지 직접 접근)
- **반환만 함** — 호출자(CollectorAgent)가 저장 담당

### 1-8. SearXNG Client (`src/utils/searxng_client.py`)

- **소스:** SearXNG 인스턴스 JSON API (`/search?format=json`)
- **설정:** `SEARXNG_API_URL` 환경변수 (기본 `http://localhost:8888`)
- **기능:** rate limiting (도메인별 1초), URL 정규화 (tracking 파라미터 제거), 재시도 (exponential backoff)
- **반환만 함** — SearchAgent/SearchRunner가 결과를 받아 처리

### 1-9. SearchAgent (`src/agents/search_agent.py`)

- **상태:** stub 구현 (TODO)
- **설계 방향:** `SearXNG → 웹 페이지 접속 → ScrapeGraphAI 구조화 → Claude CLI 추론`
- **주문 권한 없음** — 정보 수집/구조화만 담당

---

## 2. 데이터 저장소

### 2-1. PostgreSQL (`src/utils/db_client.py`)

asyncpg 커넥션 풀 기반. `DATABASE_URL` 환경변수로 연결. max_size=30.

#### 테이블 전체 목록 (코드에서 확인된 것)

| 테이블 | 유니크 제약 | 주요 쓰기 에이전트 | 쿼리 파일 |
|---|---|---|---|
| `market_data` | `(ticker, timestamp_kst, interval)` | collector, gen_collector | `queries.py` |
| `predictions` | auto-increment id | predictor | `queries.py` |
| `debate_transcripts` | auto-increment id | strategy_b | `queries.py` |
| `portfolio_positions` | `(ticker, account_scope)` | portfolio_manager | `queries.py` |
| `trade_history` | auto-increment id | paper_trading, kis broker | `queries.py` |
| `broker_orders` | `client_order_id` | kis broker | `queries.py` |
| `trading_accounts` | `account_scope` | kis broker | `queries.py` |
| `account_snapshots` | auto-increment id (시계열) | account_state | `queries.py` |
| `portfolio_config` | 단일 행 | portfolio_manager | `queries.py` |
| `model_role_configs` | `config_key` | config API | `queries.py` |
| `predictor_tournament_scores` | `(agent_id, trading_date)` | strategy_a_tournament | `queries.py` |
| `agent_heartbeats` | auto-increment id (시계열) | 모든 에이전트 | `queries.py` |
| `notification_history` | auto-increment id | notifier | `queries.py` |
| `real_trading_audit` | auto-increment id | audit API | `queries.py` |
| `operational_audits` | auto-increment id | audit | `queries.py` |
| `paper_trading_runs` | auto-increment id | paper_trading | `queries.py` |
| `krx_stock_master` | `ticker` | krx_stock_master_collector | `marketplace_queries.py` |
| `theme_stocks` | `(theme_slug, ticker)` | marketplace | `marketplace_queries.py` |
| `macro_indicators` | `(symbol, snapshot_date)` | macro_collector | `marketplace_queries.py` |
| `daily_rankings` | `(ranking_date, ranking_type, rank)` | ranking_calculator | `marketplace_queries.py` |
| `watchlist` | `(user_id, group_name, ticker)` | watchlist API | `marketplace_queries.py` |

### 2-2. Redis (`src/utils/redis_client.py`)

`redis.asyncio` (aioredis 호환) 싱글턴. `REDIS_URL` 환경변수. max_connections=20.

#### 캐시 키 전체 목록

| 키 패턴 | TTL | 용도 | 쓰기 주체 |
|---|---|---|---|
| `heartbeat:{agent_id}` | 90초 | 에이전트 생존 신호 | 모든 에이전트 |
| `kis:oauth_token:{scope}` | 23시간 | KIS OAuth access_token | kis_session |
| `krx:holidays:{year}` | 24시간 | KRX 휴장일 캘린더 | fetch_krx_holidays |
| `redis:cache:latest_ticks:{ticker}` | 60초 | 최신 시세 (단건 JSON) | collector |
| `redis:cache:realtime_series:{ticker}` | 1시간 | 실시간 시계열 (최대 300건 리스트) | collector |
| `redis:cache:market_index` | 120초 | KOSPI/KOSDAQ 지수 | index_collector |
| `redis:cache:krx_stock_master` | 24시간 | 전종목 마스터 | krx_stock_master_collector |
| `redis:cache:sector_map` | 24시간 | 섹터 → 종목 매핑 | krx_stock_master_collector |
| `redis:cache:theme_map` | 24시간 | 테마 → 종목 매핑 | marketplace |
| `redis:cache:rankings:{ranking_type}` | 5분 | 랭킹 (장중 빈번 갱신) | ranking_calculator |
| `redis:cache:macro:{category}` | 1시간 | 매크로 지표 | macro_collector |
| `redis:cache:etf_list` | 24시간 | ETF/ETN 목록 | krx_stock_master_collector |
| `memory:macro_context` | 4시간 | 거시경제 컨텍스트 (LLM용) | macro_collector |

#### Pub/Sub 채널

| 채널 | 발행 페이로드 | 구독자 |
|---|---|---|
| `redis:topic:market_data` | `{type, agent_id, count/ticker/price, timestamp_utc}` | orchestrator, predictor |
| `redis:topic:signals` | 예측 시그널 | portfolio_manager |
| `redis:topic:orders` | 주문 이벤트 | notifier |
| `redis:topic:heartbeat` | 하트비트 | orchestrator |
| `redis:topic:alerts` | 알림 | notifier |

### 2-3. S3/MinIO (`src/utils/s3_client.py` + `src/services/datalake.py`)

boto3 기반. `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME` 환경변수.

#### Hive-style 파티셔닝 구조

```
s3://{bucket}/
├── daily_bars/date=2026-03-18/daily_bars_083012.parquet
├── tick_data/date=2026-03-18/tick_data_093045.parquet
├── predictions/date=2026-03-18/predictions_084500.parquet
├── orders/date=2026-03-18/orders_090100.parquet
├── blend_results/date=2026-03-18/blend_results_085500.parquet
├── debate_transcripts/date=.../...
└── rl_episodes/date=.../...
```

#### DataType별 PyArrow 스키마

| DataType | 저장 함수 | 필드 요약 |
|---|---|---|
| `daily_bars` | `store_daily_bars()` | ticker, name, market, timestamp_kst, OHLCV, change_pct, market_cap, foreigner_ratio |
| `predictions` | `store_predictions()` | agent_id, llm_model, strategy, ticker, signal, confidence, target/stop, reasoning, is_shadow |
| `orders` | `store_orders()` | ticker, name, signal, quantity, price, signal_source, agent_id, account_scope, strategy_id |
| `blend_results` | `store_blend_results()` | ticker, blended_signal, blended_confidence, strategy_weights(JSON) |
| `debate_transcripts` | 미구현 (enum만 존재) | — |
| `rl_episodes` | 미구현 (enum만 존재) | — |

- 압축: Snappy
- 업로드 재시도: 최대 3회, exponential backoff (1s → 2s → 4s)

### 2-4. 로컬 파일 시스템

#### RL 정책 저장 (`artifacts/rl/`)

```
artifacts/rl/
├── models/{algorithm}/{ticker}/{policy_id}.json    # 학습된 RL 정책
├── models/registry.json                             # 정책 레지스트리
├── active_policies.json                             # V1 레거시 호환
├── data/                                            # 학습 데이터셋
├── profiles/                                        # 에이전트 프로파일
├── truefx/                                          # TrueFX 데이터
├── yahoo/                                           # Yahoo Finance 데이터
└── yfinance/                                        # yfinance 데이터
```

#### 실험 메타데이터 (`config/experiments/`)

```
config/experiments/
├── strategy_a/{run_id}.json
├── strategy_b/{run_id}.json
├── rl/{run_id}.json
└── search/{run_id}.json
```

각 JSON에는 `run_id`, `domain`, `config_version`, `status`, `commit_hash`, `metrics` 등이 기록됩니다.

---

## 3. 저장소 일관성 매트릭스

각 수집 경로가 어떤 저장소에 쓰는지 한눈에 보기:

| 수집 경로 | PostgreSQL | Redis 캐시 | Redis Pub/Sub | S3 Parquet |
|---|:---:|:---:|:---:|:---:|
| `collect_daily_bars` (FDR) | ✅ `market_data` | ✅ latest_ticks | ✅ market_data | ✅ daily_bars |
| `collect_yahoo_daily_bars` | ✅ `market_data` | ❌ | ❌ | ❌ |
| `collect_realtime_ticks` (KIS WS) | ✅ `market_data` | ✅ latest_ticks | ✅ market_data | ❌ |
| `fetch_historical_ohlcv` (FDR/KIS) | ✅ `market_data` | ❌ | ❌ | ❌ |
| IndexCollector (KIS REST) | ❌ | ✅ market_index | ❌ | ❌ |
| MacroCollector (FDR) | ✅ `macro_indicators` | ✅ macro:{cat} | ❌ | ❌ |
| KrxStockMasterCollector (FDR) | ✅ `krx_stock_master` | ✅ krx_stock_master 외 3개 | ❌ | ❌ |
| GenCollector (Gen API) | ✅ `market_data` | ✅ latest_ticks | ✅ market_data | ✅ daily_bars |
| KIS Broker (KIS REST) | ✅ broker_orders 외 | ❌ | ❌ | ❌ |
| Predictor 출력 | ✅ `predictions` | ✅ signals | ✅ signals | ✅ predictions |
| Portfolio Manager 출력 | ✅ positions/trades | ❌ | ✅ orders | ✅ orders |
| Blender 출력 | ❌ | ❌ | ❌ | ✅ blend_results |

> ⚠️ **불일치 포인트:** Yahoo 일봉과 Historical 수집은 PG만 사용합니다. 실시간 틱은 S3에 저장하지 않습니다.
> 이 불일치가 의도된 것인지 향후 정리가 필요합니다.

---

## 4. 전체 데이터 흐름도

```
┌─────────────── 수집 소스 ──────────────────┐
│                                             │
│  FinanceDataReader ──┐                      │
│  Yahoo Finance ──────┤                      │
│  KIS REST API ───────┼── CollectorAgent ──┐ │
│  KIS WebSocket ──────┤                    │ │
│  Gen Server API ─────┘                    │ │
│                                           │ │
│  FinanceDataReader ── MacroCollector ────┐ │ │
│  FinanceDataReader ── StockMasterColl ─┐│ │ │
│  KIS REST API ──── IndexCollector ───┐ ││ │ │
│  SearXNG ──────── SearchAgent ─────┐ │ ││ │ │
│                                    │ │ ││ │ │
└────────────────────────────────────┼─┼─┼┼─┼─┘
                                     │ │ ││ │
              ┌──────────────────────┼─┼─┼┼─┘
              │                      │ │ ││
              ▼                      │ │ ││
┌─── PostgreSQL ──────────────────┐  │ │ ││
│ market_data (OHLCV)             │←─┼─┘ ││
│ macro_indicators                │←─┘   ││
│ krx_stock_master, theme_stocks      │←─────┘│
│ predictions, debate_transcripts │       │
│ portfolio_positions             │       │
│ trade_history, broker_orders    │       │
│ trading_accounts                │       │
│ account_snapshots               │       │
│ agent_heartbeats                │       │
│ daily_rankings, watchlist       │       │
└─────────────────────────────────┘       │
                                          │
              ┌───────────────────────────┘
              ▼
┌─── Redis ───────────────────────┐
│ 캐시: latest_ticks, market_index│
│       krx_stock_master, macro, etc  │
│ Pub/Sub: market_data, signals   │
│          orders, alerts         │
│ 인증: kis:oauth_token           │
│ 헬스: heartbeat:{agent_id}      │
└─────────────────────────────────┘

              │
              ▼
┌─── S3/MinIO (Parquet) ──────────┐
│ daily_bars/date=YYYY-MM-DD/     │
│ predictions/date=.../           │
│ orders/date=.../                │
│ blend_results/date=.../         │
└─────────────────────────────────┘

              │
              ▼
┌─── 로컬 파일 ───────────────────┐
│ artifacts/rl/models/            │
│ config/experiments/             │
└─────────────────────────────────┘
```

---

## 5. 환경 변수 참조

데이터 경로와 관련된 주요 환경변수:

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | PostgreSQL 연결 문자열 |
| `REDIS_URL` | Redis 연결 문자열 |
| `S3_ENDPOINT_URL` | S3/MinIO 엔드포인트 |
| `S3_ACCESS_KEY` | S3 접근 키 |
| `S3_SECRET_KEY` | S3 시크릿 키 |
| `S3_BUCKET_NAME` | S3 버킷 이름 |
| `S3_REGION` | S3 리전 |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | KIS API 인증 |
| `KIS_IS_PAPER_TRADING` | 모의투자 여부 |
| `SEARXNG_API_URL` | SearXNG 인스턴스 URL |

---

## 6. 끊어진 파이프라인 (2026-03-18 감사 결과)

> 코드는 존재하지만 실제로 데이터가 흐르지 않거나 저장되지 않는 지점들.

| # | 심각도 | 위치 | 증상 |
|---|:---:|---|---|
| 1 | 🔴 | `search_agent.py` | `run_research()` 완전 stub. 항상 neutral/0.5 반환. SearXNG 클라이언트 호출 코드 없음 |
| 2 | 🔴 | `orchestrator.py` CLI | `_main_async()`에서 Runner 0개 등록 → 빈 레지스트리 → 예측 0건 → 블렌딩 불가 |
| 3 | 🔴 | `datalake.py` | `debate_transcripts`, `rl_episodes` DataType enum만 존재, store 함수 미구현 |
| 4 | 🟡 | `collect_yahoo_daily_bars` | PG만 저장. Redis 캐시·S3 Parquet·Pub/Sub 전부 누락 (FDR 일봉과 불일치) |
| 5 | 🟡 | `collect_realtime_ticks` | S3 Parquet 미저장. `tick_data` DataType은 enum에 있으나 store 함수 없음 |
| 6 | 🟡 | `api/main.py` lifespan | IndexCollector만 스케줄링됨. CollectorAgent 일봉/MacroCollector/KrxStockMasterCollector 스케줄 없음 |
| 7 | 🟡 | `IndexCollector` | Redis 캐시만 저장(TTL 120초). PG 미저장 → 재시작 시 지수 이력 소실 |
| 8 | 🟡 | `macro_collector.py` | Redis Pub/Sub 미발행. 다른 에이전트가 매크로 변동을 실시간 감지 불가 |
| 9 | 🟢 | `rl_runner.py` | `active_policies.json` 없으면 시그널 0건 반환 → 블렌딩 가중치만 소모 |
| 10 | 🟢 | `krx_stock_master_collector` | Redis `theme_map` 캐시 키 정의되어 있으나 실제 쓰기 코드 미확인 |
| 11 | 🟢 | `fetch_historical_ohlcv` | PG만 저장. 과거 데이터 S3 백업 없음 (cold storage 미활용) |

> 심각도 기준: 🔴 Critical (기능 완전 불능) · 🟡 Warning (부분 동작, 데이터 유실 위험) · 🟢 Notice (개선 권장)

---

*Last updated: 2026-03-18*
