# 마켓플레이스 섹션 확장 — 진짜 증권사 수준의 종목·섹터 커버리지

status: closed
created_at: 2026-03-15
topic_slug: marketplace-sector-expansion
owner: ddj
related_files:
- ui/web/src/pages/Market.tsx
- src/api/routers/market.py
- src/agents/collector.py
- architecture.md
- .agent/tech_stack.md
- .agent/discussions/20260315-external-access-deployment.md

## 1. Question

현재 Market 페이지는 단순 종목 50개 리스트 + OHLCV 차트 + 실시간 시세로 구성되어 있다.
이를 **진짜 증권사(토스증권, 키움, 미래에셋) 수준의 마켓플레이스**로 확장하려면 어떤 종목/섹터 구조, 데이터 파이프라인, UI 설계가 필요한가?
서버 비용은 **월 1만원 이하**로 유지해야 한다.

## 2. Background

### 현재 상태

- **종목 수집:** FinanceDataReader(EOD) + KIS WebSocket(장중 틱) — 현재 `per_page=50`으로 제한
- **Market 페이지:** KOSPI/KOSDAQ 지수 카드 + 단일 종목 OHLCV 차트 + 실시간 가격 추이
- **데이터 소스:** KRX 기준 KOSPI ~950종목, KOSDAQ ~1,700종목 = 약 2,650 상장 종목
- **부족한 것:** 섹터/테마 분류, 시가총액 랭킹, 거래량 상위, 상승/하락률, ETF/ETN, 해외지수, 환율, 원자재, 암호화폐 참조 데이터
- **인프라:** Mac Mini(Apple Silicon) + Docker Compose, 배포는 Oracle Cloud Free + Cloudflare Tunnel 검토 중

### 비교 대상 (실제 증권사 마켓플레이스)

토스증권, 키움증권 등의 마켓 탭은 보통 다음을 제공한다:
- 주요 지수 (KOSPI, KOSDAQ, S&P500, NASDAQ, 니케이 등)
- 섹터별 분류 (반도체, 바이오, 금융, 에너지, IT 등)
- 테마별 분류 (AI, 2차전지, 방산, 로봇 등)
- 시가총액 TOP N
- 거래량/거래대금 TOP N
- 상승률/하락률 TOP N
- ETF/ETN 카테고리
- 해외지수, 환율, 원자재, 금리 참조
- 관심 종목(워치리스트)

## 3. Constraints

- **서버 비용 월 1만원(≈$7) 이하** — 유료 데이터 API 사용 불가, 무료/오픈소스 데이터만
- **기존 기술 스택 유지** — FinanceDataReader, KIS API, PostgreSQL, Redis, React + Recharts
- **새 패키지 최소화** — tech_stack.md에 명시된 것 위주, 추가 시 문서화
- **Mac Mini 단일 서버** — CPU/메모리/디스크 한계 고려 (M시리즈 8~16GB RAM 가정)
- **KIS WebSocket 실시간 구독** — 동시 구독 종목 수 제한 있음 (약 20~40개)
- **데이터 신선도** — EOD 데이터는 1일 1회, 실시간은 장중만, 해외/환율은 무료 소스 한계

## 4. Options

### Option A: 계층적 확장 (Phase 기반 점진적 추가)
- Phase 1: 섹터/테마 정적 매핑 + 기존 종목 전체 확장
- Phase 2: 랭킹/TOP N 집계 뷰
- Phase 3: ETF/해외지수/환율 무료 데이터 추가
- Phase 4: 워치리스트 + 개인화

### Option B: 데이터 레이크 우선 (수집 파이프라인부터)
- 전체 KRX 종목 마스터 + 섹터 코드를 DB에 먼저 적재
- 집계/뷰를 DB 레벨에서 미리 만들어두고 UI는 점진적

### Option C: UI 먼저 (mock 데이터 → 점진적 연결)
- 증권사 레벨 UI를 먼저 설계/구현
- 데이터는 mock → FDR → KIS 순으로 교체

## 5. AI Opinions

---

### 🏦 Agent 1 — Marcus Chen (골드만삭스 15년차, Equity Research & Market Structure 전문가)

**페르소나:** 뉴욕 Goldman Sachs에서 Equity Research → Electronic Trading → Market Microstructure를 거친 시니어 MD. 한국 시장 커버리지 경험 있음. "리테일 투자자가 보는 마켓 데이터의 본질은 **의사결정을 돕는 구조화된 컨텍스트**"라는 철학.

#### 핵심 의견: "종목 수보다 **구조화된 컨텍스트**가 먼저다"

증권사 마켓플레이스를 만들겠다는 목표는 좋지만, 단순히 2,650개 종목을 나열하면 네이버 금융과 다를 바 없다. 진짜 차별화는 **"이 종목이 왜 움직이고 있는지"를 보여주는 구조**에 있다.

#### 1) 섹터/테마 데이터 구조 제안

KOSPI/KOSDAQ 종목의 섹터 분류는 KRX가 공식 제공하는 **GICS(Global Industry Classification Standard) 기반 업종 분류**를 쓰면 된다. FinanceDataReader의 `fdr.StockListing('KRX')` 응답에 이미 `Sector`, `Industry` 필드가 포함되어 있다.

```
Level 1 — 대분류 (11개 GICS Sector)
├── 정보기술 (IT)
├── 헬스케어
├── 산업재
├── 경기소비재
├── 필수소비재
├── 금융
├── 커뮤니케이션서비스
├── 에너지
├── 소재
├── 유틸리티
└── 부동산

Level 2 — 테마 (동적, 시장 관심도 기반)
├── AI/반도체
├── 2차전지/EV
├── 바이오/신약
├── 방산/우주
├── 로봇/자동화
├── K-콘텐츠
└── (SearXNG 검색 기반으로 동적 추가 가능)
```

**핵심:** GICS 대분류는 정적이고 안정적 → DB에 한 번 적재하면 분기 1회 갱신. 테마는 시장 트렌드 → 검색 파이프라인(Strategy S)과 연동해 반자동 갱신.

#### 2) 종목 커버리지 우선순위

2,650개 전부 동시 수집은 비효율적이다. 증권사도 내부적으로 티어를 나눈다:

| 티어 | 종목 수 | EOD 수집 | 실시간 | 설명 |
|------|---------|----------|--------|------|
| Tier 1 — Core | ~100 | 매일 | 장중 WebSocket | 시총 TOP 50 + 전략 보유종목 + 관심종목 |
| Tier 2 — Extended | ~500 | 매일 | 요청 시 | 섹터 대표 + 테마 리더 + 거래량 상위 |
| Tier 3 — Universe | ~2,650 | 주 1회 | 미제공 | 전체 종목 마스터(검색/필터용) |

이렇게 하면 **매일 EOD 수집은 ~600건**(FDR 무료, API 호출 ~2분), **실시간은 ~40건**(KIS WebSocket 제한 내), 나머지는 주간 배치.

#### 3) 무료 데이터로 가능한 해외/매크로 참조

| 데이터 | 무료 소스 | 갱신 주기 | 비용 |
|--------|-----------|-----------|------|
| 미국 3대 지수 (S&P500, NASDAQ, DOW) | FDR `StockListing('S&P500')` 또는 Yahoo Finance scrape | 1일 1회 EOD | $0 |
| USD/KRW 환율 | FDR `DataReader('USD/KRW', ...)` 또는 한국은행 ECOS API (무료) | 1일 1회 | $0 |
| 주요 원자재 (금, 유가, 구리) | FDR 또는 investing.com scrape | 1일 1회 | $0 |
| 한국 금리 (기준금리, 국고채) | 한국은행 ECOS API (무료, API key 발급) | 월 1회 | $0 |
| 암호화폐 참조 (BTC, ETH) | CoinGecko API (무료 tier, 30 calls/min) | 5분 | $0 |
| ETF 목록 + NAV | FDR `ETFListing()` + KRX ETF API | 1일 1회 | $0 |

**총 추가 비용: $0** — 전부 무료 API와 FDR으로 커버 가능.

#### 4) UI 구조 제안 (증권사 레퍼런스)

```
마켓 센터 (Market)
├── 📊 지수 개요
│   ├── 국내: KOSPI, KOSDAQ, KRX300
│   ├── 해외: S&P500, NASDAQ, 니케이225, 상해종합
│   ├── 환율: USD/KRW, EUR/KRW, JPY/KRW, CNY/KRW
│   └── 원자재: WTI, 금, 구리
│
├── 🏷️ 섹터 맵
│   ├── GICS 11개 섹터별 등락률 히트맵
│   ├── 섹터 클릭 → 해당 섹터 종목 리스트
│   └── 섹터 내 시총/등락률 정렬
│
├── 🔥 테마
│   ├── 인기 테마 (거래량/뉴스 빈도 기반)
│   ├── 테마별 대장주 + 관련 종목
│   └── (Strategy S 검색 결과와 연동)
│
├── 📈 랭킹
│   ├── 시가총액 TOP 30
│   ├── 거래량 TOP 30
│   ├── 상승률 TOP 20 / 하락률 TOP 20
│   ├── 52주 신고가 / 신저가
│   └── 외국인/기관 순매수 TOP (KIS API)
│
├── 💎 ETF/ETN
│   ├── 카테고리별: 국내지수, 해외지수, 섹터, 채권, 원자재, 레버리지/인버스
│   ├── 순자산총액 TOP
│   └── 괴리율 모니터링
│
├── ⭐ 관심종목 (워치리스트)
│   ├── 사용자 커스텀 그룹
│   ├── 전략별 보유종목 자동 등록
│   └── 가격 알림 설정
│
└── 🔍 종목 상세
    ├── OHLCV 차트 (일/주/월)
    ├── 실시간 가격
    ├── 재무 요약 (PER, PBR, 배당수익률)
    ├── 관련 뉴스 (SearXNG)
    └── AI 분석 요약 (Strategy A/B 시그널)
```

#### 5) 장기 비전: "AI 증권사"로의 차별화

일반 증권사는 데이터를 보여주기만 한다. 우리 시스템은 이미 Strategy A/B/RL/S가 있으므로:
- 섹터 히트맵에 "AI가 주목하는 섹터" 표시
- 랭킹에 "AI 매수 시그널 일치 종목" 하이라이트
- 테마에 "Strategy S가 감지한 신규 테마" 자동 추가
- 종목 상세에 "AI 분석 요약" 탭

이것이 네이버 금융이나 토스증권과의 결정적 차이점이 된다.

#### 비용 영향 분석

| 항목 | 현재 | 확장 후 | 월 비용 |
|------|------|---------|---------|
| EOD 데이터 수집 | ~50종목 | Tier1 100 + Tier2 500 | $0 (FDR 무료) |
| 실시간 틱 | ~10종목 | ~40종목 (KIS 제한) | $0 (KIS 무료) |
| 해외지수/환율 | 없음 | 일 1회 배치 | $0 (FDR/ECOS) |
| DB 저장 | ~5GB | ~20GB (1년 기준) | $0 (로컬 PG) |
| Redis 캐시 | ~100MB | ~500MB | $0 (로컬) |
| 서버 | Mac Mini | Mac Mini (동일) | ₩0 (전기세 제외) |
| 도메인/CF Tunnel | — | Cloudflare 무료 | ₩1,100/월 |
| **합계** | | | **₩1,100/월** |

**결론: 월 1만원 예산 안에서 증권사 수준의 마켓플레이스가 가능하다.**

#### 추천: Option A (계층적 확장) + Option B (데이터 레이크 먼저) 하이브리드

1. **즉시:** KRX 전체 종목 마스터 + GICS 섹터 코드를 DB에 적재 (fdr.StockListing 1회)
2. **1주차:** 섹터 맵 + 시총/거래량 랭킹 UI (EOD 데이터 기반)
3. **2주차:** 해외지수/환율/원자재 참조 데이터 + 테마 초안
4. **3주차:** ETF 카테고리 + 워치리스트
5. **4주차:** AI 분석 연동 (Strategy 시그널 오버레이)

---

### 🖥️ Agent 2 — 박서준 (구글 15년차, Large-Scale Backend / Data Infrastructure 전문가)

**페르소나:** 구글 서울 → 마운틴뷰에서 Search Infrastructure → Ads Serving → YouTube Data Pipeline을 거친 Staff Engineer. 초당 수십만 QPS를 다루던 경험. "작은 시스템이라도 **구조가 맞으면 10배 확장에 코드 변경이 0**"이라는 신조.

#### 핵심 의견: "Mac Mini 단일 서버에서 2,650종목을 서빙하려면 **캐싱 전략이 전부**다"

Marcus의 데이터 구조 제안에 동의한다. 하지만 실제 구현에서 가장 중요한 건 **"어떻게 수집하고 어떻게 캐싱하느냐"**다. Mac Mini 하나로 증권사 수준의 응답성을 만들려면 Google에서 쓰는 핵심 패턴 3가지를 적용해야 한다.

#### 1) 데이터 파이프라인 설계 — 배치 vs 실시간 분리

```
┌─────────────────────────────────────────────────┐
│              Data Ingestion Layer                │
├─────────────────────────────────────────────────┤
│                                                 │
│  [Batch — APScheduler]                          │
│  ├── 06:00 KST: KRX 종목 마스터 갱신            │
│  │   └── fdr.StockListing('KRX')               │
│  │   └── → stock_master 테이블 UPSERT           │
│  │   └── → Redis sector_map 캐시 갱신           │
│  │                                              │
│  ├── 08:00 KST: Tier1+Tier2 EOD 수집           │
│  │   └── fdr.DataReader(tickers, start, end)    │
│  │   └── → market_data 테이블 INSERT            │
│  │   └── → Redis ranking_cache 사전 계산        │
│  │                                              │
│  ├── 08:10 KST: 해외지수/환율/원자재 수집        │
│  │   └── fdr.DataReader('USD/KRW', ...)         │
│  │   └── → macro_indicators 테이블              │
│  │   └── → Redis macro_cache TTL 1h             │
│  │                                              │
│  └── 22:00 KST (주 1회): Tier3 전체 EOD 수집    │
│      └── → 전체 종목 마스터 기반 배치              │
│                                                 │
│  [Realtime — KIS WebSocket]                     │
│  ├── 09:00~15:30: Tier1 ~40종목 틱 수집         │
│  │   └── → Redis latest_ticks:{ticker} TTL 60s  │
│  │   └── → Redis realtime_ranking 실시간 갱신    │
│  └── 15:30~: WebSocket 해제, 마지막 틱 유지      │
│                                                 │
└─────────────────────────────────────────────────┘
```

#### 2) 캐싱 아키텍처 — Redis 레이어 설계

Google에서 배운 핵심: **"DB를 직접 치는 요청은 0이어야 한다."** 모든 읽기는 Redis를 거치고, DB는 write-path에서만 사용한다.

```
Redis 캐시 구조
├── market:master                    # 전체 종목 마스터 (Hash)
│   TTL: 24h, 갱신: 06:00 배치
│   key: ticker → {name, sector, industry, market_cap, ...}
│
├── market:sector:{sector_code}      # 섹터별 종목 리스트 (Sorted Set)
│   TTL: 24h, score: market_cap
│   member: ticker
│
├── market:theme:{theme_slug}        # 테마별 종목 (Set)
│   TTL: 24h, 수동/반자동 관리
│
├── market:ranking:mcap              # 시총 TOP (Sorted Set)
│   TTL: 24h, 갱신: 08:00 배치
│
├── market:ranking:volume            # 거래량 TOP (Sorted Set)
│   TTL: 5min (장중), 갱신: 실시간 틱 기반
│
├── market:ranking:change_up         # 상승률 TOP (Sorted Set)
│   TTL: 5min, 갱신: 실시간 틱 기반
│
├── market:ranking:change_down       # 하락률 TOP (Sorted Set)
│   TTL: 5min, 갱신: 실시간 틱 기반
│
├── market:macro:{indicator}         # 해외지수/환율/원자재 (String)
│   TTL: 1h~24h, 갱신: 08:10 배치
│
├── market:etf:categories            # ETF 카테고리 목록 (Hash)
│   TTL: 24h
│
├── market:sector_heatmap            # 섹터 히트맵 사전 계산 (String/JSON)
│   TTL: 5min (장중) / 24h (장외)
│
└── market:summary                   # 마켓 요약 대시보드용 (String/JSON)
    TTL: 30s (장중) / 24h (장외)
    {kospi, kosdaq, usd_krw, top_gainers_3, top_losers_3, ...}
```

**핵심 수치:**
- Redis 메모리: 2,650종목 마스터 ~15MB + 랭킹/캐시 ~50MB = **총 ~70MB**
- Mac Mini 8GB RAM 기준 Redis에 512MB 할당해도 충분
- 캐시 히트율 목표: **95% 이상** (DB 직접 조회는 write 시점과 cache miss 시에만)

#### 3) API 엔드포인트 설계 — 증권사 수준

```python
# 신규 엔드포인트 (기존 /market/* 확장)

# 종목 마스터
GET /market/stocks                    # 전체 종목 (페이지네이션, 필터)
GET /market/stocks/{ticker}           # 종목 상세 (캐시)
GET /market/stocks/search?q=삼성      # 종목 검색 (Redis full-text 또는 prefix)

# 섹터
GET /market/sectors                   # 섹터 목록 + 등락률
GET /market/sectors/{code}/stocks     # 섹터 내 종목
GET /market/sectors/heatmap           # 섹터 히트맵 데이터

# 테마
GET /market/themes                    # 테마 목록
GET /market/themes/{slug}/stocks      # 테마 내 종목

# 랭킹
GET /market/rankings/{type}           # mcap, volume, change_up, change_down, new_high, new_low
  ?period=today|week|month
  &limit=30

# 매크로/참조
GET /market/macro/indices             # 국내외 지수
GET /market/macro/currencies          # 환율
GET /market/macro/commodities         # 원자재
GET /market/macro/rates               # 금리

# ETF
GET /market/etf                       # ETF 목록 (카테고리별)
GET /market/etf/{ticker}              # ETF 상세 (NAV, 괴리율)

# 워치리스트
GET    /market/watchlist              # 관심종목 조회
POST   /market/watchlist              # 관심종목 추가
DELETE /market/watchlist/{ticker}     # 관심종목 삭제
```

#### 4) DB 스키마 확장

```sql
-- 종목 마스터 (KRX 전체)
CREATE TABLE stock_master (
    ticker         VARCHAR(12) PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    name_en        VARCHAR(100),
    market         VARCHAR(10) NOT NULL,  -- KOSPI, KOSDAQ, KONEX
    sector_code    VARCHAR(10),           -- GICS sector
    sector_name    VARCHAR(50),
    industry_code  VARCHAR(10),           -- GICS industry
    industry_name  VARCHAR(80),
    market_cap     BIGINT,                -- 시가총액 (원)
    shares_out     BIGINT,                -- 발행주식수
    listing_date   DATE,
    is_etf         BOOLEAN DEFAULT FALSE,
    etf_category   VARCHAR(50),           -- 국내지수, 해외지수, 섹터, 채권, ...
    tier           SMALLINT DEFAULT 3,    -- 1=Core, 2=Extended, 3=Universe
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 테마 매핑
CREATE TABLE theme_stocks (
    theme_slug     VARCHAR(50) NOT NULL,
    theme_name     VARCHAR(100) NOT NULL,
    ticker         VARCHAR(12) REFERENCES stock_master(ticker),
    is_leader      BOOLEAN DEFAULT FALSE,  -- 대장주 여부
    added_at       TIMESTAMPTZ DEFAULT NOW(),
    source         VARCHAR(20) DEFAULT 'manual',  -- manual, search_agent
    PRIMARY KEY (theme_slug, ticker)
);

-- 매크로 지표
CREATE TABLE macro_indicators (
    indicator_code VARCHAR(30) NOT NULL,  -- SP500, NASDAQ, USD_KRW, WTI, ...
    indicator_name VARCHAR(100) NOT NULL,
    category       VARCHAR(20) NOT NULL,  -- index, currency, commodity, rate
    value          NUMERIC(18, 6),
    change_pct     NUMERIC(8, 4),
    recorded_at    DATE NOT NULL,
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (indicator_code, recorded_at)
);

-- 워치리스트
CREATE TABLE watchlist (
    user_id        INTEGER NOT NULL,
    group_name     VARCHAR(50) DEFAULT 'default',
    ticker         VARCHAR(12) REFERENCES stock_master(ticker),
    added_at       TIMESTAMPTZ DEFAULT NOW(),
    price_alert_up   NUMERIC(12, 0),  -- 가격 상한 알림
    price_alert_down NUMERIC(12, 0),  -- 가격 하한 알림
    PRIMARY KEY (user_id, group_name, ticker)
);

-- 일별 랭킹 스냅샷 (배치 계산 후 저장)
CREATE TABLE daily_rankings (
    ranking_date   DATE NOT NULL,
    ranking_type   VARCHAR(20) NOT NULL,  -- mcap, volume, change_up, change_down
    rank           SMALLINT NOT NULL,
    ticker         VARCHAR(12) NOT NULL,
    value          NUMERIC(18, 4),
    PRIMARY KEY (ranking_date, ranking_type, rank)
);
```

#### 5) 성능 예산 분석 (Mac Mini 기준)

| 리소스 | 현재 사용 | 확장 후 예상 | Mac Mini 한계 | 여유율 |
|--------|-----------|-------------|--------------|--------|
| CPU | ~5% 평균 | ~15% 평균, 피크 40% (배치 시) | 100% (8코어) | 충분 |
| RAM | ~2GB | ~4GB (PG 1.5GB + Redis 512MB + App 1GB + OS 1GB) | 8~16GB | 충분 |
| Disk | ~5GB | ~25GB (1년 후) | 256GB~1TB | 충분 |
| Network | ~1Mbps | ~5Mbps (피크) | 1Gbps | 충분 |

**배치 수집 시간 예측:**
- Tier1+2 EOD 600종목: FDR 병렬 5스레드 → ~3분
- 해외/매크로 10개 지표: ~10초
- Tier3 전체 2,650종목 (주 1회): ~12분
- 섹터 히트맵/랭킹 계산: ~30초

**API 응답 시간 목표:**
- Redis 캐시 히트: < 10ms
- DB 폴백: < 50ms
- 페이지 로드 (마켓 메인): < 200ms

#### 6) 비용 요약

| 항목 | 월 비용 |
|------|---------|
| Mac Mini 전기세 | ~₩3,000 (24시간 가동, 20W 평균) |
| Cloudflare Tunnel (도메인 없이) | ₩0 |
| 도메인 (.dev 또는 .app) | ₩1,100/월 (연 ₩13,000 기준) |
| FDR / ECOS / CoinGecko API | ₩0 (무료) |
| KIS API | ₩0 (개인투자자 무료) |
| PostgreSQL / Redis | ₩0 (로컬 Docker) |
| **합계** | **₩4,100/월** |

예산 ₩10,000 대비 **₩5,900 여유** → 향후 유료 데이터 소스 추가 가능.

#### 추천 구현 순서

Marcus의 점진적 확장에 동의하되, **데이터 레이어를 먼저 견고하게** 만들어야 한다:

1. **Week 1 (데이터 기반):**
   - `stock_master` 테이블 생성 + `fdr.StockListing('KRX')` 일일 배치
   - `macro_indicators` 테이블 + 해외지수/환율 배치
   - Redis 캐시 구조 셋업 + 종목 마스터 캐싱
   - API: `/market/stocks`, `/market/sectors`, `/market/macro/*`

2. **Week 2 (랭킹 + 집계):**
   - `daily_rankings` 배치 계산 (장 마감 후)
   - Redis 실시간 랭킹 (장중 틱 기반)
   - API: `/market/rankings/*`, `/market/sectors/heatmap`
   - UI: 섹터 히트맵 + 랭킹 탭

3. **Week 3 (테마 + ETF):**
   - `theme_stocks` 초기 매핑 (수동 30개 테마)
   - ETF 카테고리 분류
   - Strategy S 연동 포인트 설계
   - UI: 테마 브라우저 + ETF 탭

4. **Week 4 (워치리스트 + AI 연동):**
   - `watchlist` 테이블 + CRUD API
   - Strategy A/B/RL 시그널 오버레이
   - "AI가 주목하는" 배지 시스템
   - UI: 종목 상세 페이지 리뉴얼

5. **Week 5+ (최적화):**
   - 캐시 히트율 모니터링 + 튜닝
   - FDR 호출 실패 시 폴백 경로
   - 장중/장외 모드 자동 전환
   - 모바일 반응형 최적화

#### 스케일링 리스크와 대응

| 리스크 | 확률 | 대응 |
|--------|------|------|
| FDR API 불안정/장애 | 중 | 24시간 캐시 + Yahoo Finance 폴백 |
| KIS WebSocket 40종목 제한 | 높음 | 동적 구독 (화면에 보이는 종목만 구독) |
| Redis 메모리 부족 | 낮음 | TTL 조정 + LRU eviction 설정 |
| PG 디스크 부족 | 낮음 (1년 후) | 90일 파티셔닝 + Cold 아카이브 |
| 동시 접속 증가 | 낮음 (개인용) | Cloudflare CDN + API rate limit |

---

## 6. Interim Conclusion

두 에이전트의 의견이 수렴하는 지점:

1. **Option A+B 하이브리드** — 데이터 레이크(종목 마스터 + 섹터/매크로)를 먼저 구축하고, UI는 점진적으로 확장
2. **종목 티어링** — 전체 2,650개를 Tier 1/2/3으로 나눠 수집 빈도와 리소스 배분
3. **Redis 중심 읽기 경로** — 모든 읽기는 Redis 캐시, DB는 쓰기 전용
4. **월 ₩4,100 예산** — 현재 인프라로 충분, 예산 여유 ₩5,900
5. **AI 차별화** — 기존 Strategy A/B/RL/S 시그널을 마켓플레이스에 오버레이하는 것이 핵심 경쟁력
6. **5주 구현 계획** — 데이터 → 랭킹 → 테마/ETF → 워치리스트/AI → 최적화

### 데이터 소스 커버리지 요약

| 카테고리 | 항목 수 | 소스 | 비용 |
|----------|---------|------|------|
| 국내 주식 (KOSPI+KOSDAQ) | ~2,650 | FDR + KIS | ₩0 |
| GICS 섹터 분류 | 11 대분류 | FDR StockListing | ₩0 |
| 투자 테마 | 30+ | 수동 + Strategy S | ₩0 |
| 해외 주요 지수 | 6~10 | FDR | ₩0 |
| 환율 | 4~6 | FDR / ECOS | ₩0 |
| 원자재 | 3~5 | FDR | ₩0 |
| 금리 | 2~3 | ECOS | ₩0 |
| ETF/ETN | ~700 | FDR ETFListing | ₩0 |
| 암호화폐 참조 | 2~5 | CoinGecko 무료 | ₩0 |
| **총 종목/지표** | **~3,400+** | | **₩0** |

## 7. Final Decision

### 7-1. AI 의견 종합 (Marcus + 박서준 + Antigravity)

**3자 합의 사항:**
- **Option A+B 하이브리드** 채택 — 데이터 레이크(종목 마스터 + 섹터 + 매크로)를 먼저 구축하고, UI는 점진적 확장
- **Redis 캐시 중심 읽기 경로** — 모든 읽기는 Redis, DB는 쓰기 전용. 캐시 히트율 95%+ 목표
- **월 ~₩4,100 비용** — 예산 ₩10,000 대비 충분한 여유 (₩5,900)
- **AI 시그널 오버레이가 핵심 차별화** — 단순 데이터 제공이 아닌 "AI 투자 비서 플랫폼"

**Antigravity 추가 제안:**
- KIS WebSocket 40종목 제한을 정식 아키텍처 과제로 격상 → **Dynamic Connection Pool Manager** 장기 설계 필요

**의견 차이/보완 관계:**
- Marcus(증권) — "무엇을 보여줄 것인가" (데이터 구조, 섹터/테마 분류, UI 계층)
- 박서준(백엔드) — "어떻게 서빙할 것인가" (캐싱 전략, 배치 파이프라인, 성능 예산)
- Antigravity — 둘의 합의를 승인하면서 WebSocket 병목을 장기 아키텍처 과제로 추가

### 7-2. 사용자 결정 사항 (2026-03-15)

| # | 결정 항목 | 선택 | 비고 |
|---|----------|------|------|
| D-1 | 자산 커버리지 범위 | **국내주식+섹터+테마, ETF/ETN, 해외지수+환율** | 암호화폐는 제외 |
| D-2 | 종목 티어링 | **전체 매일 수집** (2,650종목 EOD 매일) | Marcus 3티어 대신 단순화. 배치 ~12분 수용 |
| D-3 | AI 시그널 오버레이 시기 | **Week 4** (원안대로) | 데이터/랭킹/테마/ETF 완성 후 마지막에 연동 |
| D-4 | Dynamic WebSocket 관리 | **별도 논의 문서로 분리** | 복잡도가 높아 독립 discussion으로 깊이 논의 |

### 7-3. 확정된 구현 계획

**자산 커버리지 (암호화폐 제외):**

| 카테고리 | 항목 수 | 소스 | 비용 |
|----------|---------|------|------|
| 국내 주식 (KOSPI+KOSDAQ) | ~2,650 | FDR + KIS | ₩0 |
| GICS 섹터 분류 | 11 대분류 | FDR StockListing | ₩0 |
| 투자 테마 | 30+ | 수동 + Strategy S | ₩0 |
| 해외 주요 지수 | 6~10 | FDR | ₩0 |
| 환율 | 4~6 | FDR / ECOS | ₩0 |
| 원자재 | 3~5 | FDR | ₩0 |
| 금리 | 2~3 | ECOS | ₩0 |
| ETF/ETN | ~700 | FDR ETFListing | ₩0 |

**종목 수집 정책 (D-2 반영):**
- Tier 구분 없이 **전체 2,650종목 + ETF 700종목 매일 EOD 수집**
- FDR 배치 ~12분 (22:00 KST 실행)
- 실시간 WebSocket은 기존 Tier1(~40종목) 유지, 동적 관리는 별도 논의

**5주 구현 로드맵:**

| Week | 내용 | 산출물 |
|------|------|--------|
| 1 | 데이터 기반 구축 | `stock_master` + `macro_indicators` 테이블, 전체 종목 배치 수집기, Redis 캐시 구조, `/market/stocks`, `/sectors`, `/macro/*` API |
| 2 | 랭킹 + 집계 | `daily_rankings` 배치 계산, Redis 실시간 랭킹, 섹터 히트맵 API/UI, 랭킹 탭 UI |
| 3 | 테마 + ETF | `theme_stocks` 초기 30개 테마 매핑, ETF 카테고리 분류, 테마 브라우저 + ETF 탭 UI |
| 4 | AI 연동 + 워치리스트 | Strategy A/B/RL/S 시그널 오버레이, "AI가 주목하는" 배지, `watchlist` CRUD, 종목 상세 리뉴얼 |
| 5+ | 최적화 | 캐시 히트율 튜닝, FDR 폴백, 장중/장외 자동 전환, 모바일 반응형 |

## 8. Follow-up Actions

- [x] `stock_master` 테이블 스키마 확정 및 `init_db.py`에 추가
- [x] 전체 종목 + ETF 매일 EOD 배치 수집기 구현 (`fdr.StockListing('KRX')` + `fdr.ETFListing()`)
- [x] `macro_indicators` 테이블 + 해외지수/환율/원자재/금리 배치 수집기 구현
- [x] Redis 캐시 구조 설계 문서화 및 `redis_client.py` 확장
- [x] Market API 엔드포인트 확장 (`/sectors`, `/rankings`, `/macro/*`, `/etf`)
- [x] 섹터 히트맵 UI 컴포넌트 설계
- [x] 테마 초기 데이터 수동 매핑 (30개 테마)
- [x] ETF 카테고리 분류 기준 확정
- [x] 워치리스트 DB/API/UI 설계
- [x] Strategy S ↔ 테마 자동 감지 연동 포인트 설계 (SearchRunner + 마켓플레이스 테마 구조 연결)
- [x] `roadmap.md`에 Marketplace Expansion Phase 추가 (Phase 13)
- [ ] **별도 논의 문서 생성:** Dynamic Connection Pool Manager (WebSocket 동적 구독 관리) — 향후 필요 시

## 9. Closure Checklist

- [x] 구조/장기 방향 변경 사항을 `.agent/roadmap.md`에 반영 (Phase 13 추가)
- [x] 이번 세션의 할 일을 `progress.md`에 반영
- [x] 계속 유지되어야 하는 운영 규칙을 `MEMORY.md`에 반영 (Copilot 리뷰 교훈 기록)
- [x] 논의 문서 status: closed로 변경 (영구 문서로 참조 보존)
