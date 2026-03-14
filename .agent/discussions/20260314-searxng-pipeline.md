# Discussion: SearXNG 검색/스크래핑 파이프라인 생성 방식

status: open
created_at: 2026-03-14
topic_slug: searxng-pipeline
owner: user
related_files:
- .agent/tech_stack.md
- .agent/roadmap.md
- architecture.md
- docs/TOOLS.md

## 1. Question

`SearXNG → 웹 페이지 접속 → ScrapeGraphAI 구조화 → Claude CLI 추론` 파이프라인을 어떤 컴포넌트 구조로 구현하고, 기존 에이전트 시스템과 어떻게 연결하며, 데이터 저장/재사용 규격은 어떻게 정의할 것인가?

## 2. Background

### 확정된 기술 방향 (tech_stack.md)

| 구성요소 | 역할 | 배포 방식 |
|----------|------|-----------|
| SearXNG | 검색 결과 생성 | Docker |
| ScrapeGraphAI | 페이지 구조화/파싱 | Docker 또는 worker 컨테이너 |
| Claude CLI | 추출 결과의 의미 해석과 최종 구조화 | agent/worker |
| 브라우저 렌더러 | JS-heavy 페이지 fetch/render | Docker sidecar |

규칙:
- **Tavily는 사용하지 않는다** (SearXNG로 대체)
- ScrapeGraphAI는 페이지 구조화만 담당
- 최종 추출/판단은 Claude CLI가 담당

### roadmap.md Phase 8 완료 기준

- 동일 질의의 검색 결과, 원문 출처, 추출 결과를 각각 조회 가능
- 실패 케이스가 `partial` 또는 `failed` 상태로 구분 기록
- Strategy/RL이 재사용 가능한 JSON contract 확보

### 아직 정의되지 않은 사항

1. SearXNG 인스턴스 설정과 검색 카테고리(뉴스/일반/금융) 구성
2. fetch/render worker의 구체적 구현 방식 (Playwright? Selenium? 브라우저 sidecar?)
3. ScrapeGraphAI 출력 포맷과 스키마
4. Claude CLI 호출 방식 (subprocess? API? SDK?)
5. 검색 결과/추출 결과 저장 DB 스키마
6. Strategy B prompt와 RL feature에 연결하는 research contract 포맷
7. 재실행/캐싱 정책 (동일 질의 재검색 주기)

## 3. Constraints

1. **Docker Compose 기반 로컬 배포** — 인프라 표준 (`tech_stack.md`)
2. **Tavily 사용 금지** — SearXNG가 검색 담당
3. **Claude가 최종 판단** — ScrapeGraphAI는 구조화만, 의미 해석은 Claude
4. **기존 에이전트 런타임 비침범** — 검색 파이프라인은 별도 서비스로 동작하되, 결과만 DB/API로 공급
5. **비동기 I/O 원칙** — 검색/스크래핑은 네트워크 I/O 중심이므로 `async/await` 필수
6. **출처 추적 가능** — 모든 추출 결과에 원본 URL, 검색 질의, 추출 시점 기록

## 4. Options

### Option A: 모놀리식 SearchAgent

하나의 Python 에이전트(`src/agents/search_agent.py`)가 SearXNG 호출 → fetch → ScrapeGraphAI → Claude CLI를 순차 실행한다.

```
SearchAgent.run(query)
  ├── httpx.get(searxng_url, params={q: query})  → search_results[]
  ├── for url in search_results:
  │     ├── httpx.get(url) or playwright.goto(url)  → raw_html
  │     └── scrapegraph.extract(raw_html, schema)   → structured_data
  └── claude_cli.reason(structured_data)             → research_output
```

장점: 구현 단순, 디버깅 쉬움
단점: JS-heavy 페이지 처리 어려움, 단일 실패 시 전체 파이프라인 실패, 확장성 부족

### Option B: 3-Stage Pipeline (Queue 기반)

Redis를 메시지 버스로 활용하여 3단계를 독립 worker로 분리한다.

```
Stage 1: SearchWorker
  - SearXNG API 호출 → search_results 테이블 저장 → fetch 큐에 URL 발행

Stage 2: FetchWorker
  - URL 큐 소비 → Playwright/브라우저로 렌더링 → raw_pages 테이블 저장
  - ScrapeGraphAI로 구조화 → extracted_data 테이블 저장

Stage 3: ReasoningWorker
  - extracted_data 큐 소비 → Claude CLI/SDK로 최종 분석
  - research_outputs 테이블 저장 → Strategy/RL에 공급
```

장점: 각 단계 독립 스케일링, 부분 실패 복구 가능, 재시도 용이
단점: 인프라 복잡도 증가, Redis 큐 관리 필요, 로컬 개발 환경 무거움

### Option C: 하이브리드 (동기 파이프라인 + 비동기 fetch)

SearchAgent가 전체 흐름을 조율하되, fetch/render만 비동기 worker pool로 분리한다.

```
SearchAgent.run(query)
  ├── searxng_client.search(query)  → urls[]
  ├── fetch_pool.fetch_all(urls)    → [raw_html, ...]  (asyncio.gather, Playwright pool)
  ├── scrape_pool.extract_all(...)  → [structured, ...]
  └── claude_reason(structured)     → research_output
```

장점: 단일 진입점 유지하면서 fetch 병렬화, 중간 복잡도
단점: Playwright pool 관리 필요, Claude CLI 호출이 병목이 될 수 있음

## 5. AI Opinions

### Claude (아키텍처 설계)

**Option C(하이브리드)를 권장하되, 저장 계층은 Option B의 테이블 분리 구조를 채택한다.**

이유:
- 현재 규모(한국 시장 수십 종목)에서 Redis 큐 기반 3-stage는 과도한 인프라다
- 하지만 저장은 반드시 단계별로 분리해야 재사용과 디버깅이 가능하다
- Playwright는 Docker sidecar로 `mcr.microsoft.com/playwright` 이미지를 띄우고, SearchAgent가 CDP(Chrome DevTools Protocol)로 연결하면 된다

제안 저장 스키마:

```sql
-- 검색 요청/결과
CREATE TABLE search_queries (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    category TEXT DEFAULT 'general',  -- general, news, finance
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE search_results (
    id SERIAL PRIMARY KEY,
    query_id INT REFERENCES search_queries(id),
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    rank INT,
    fetched BOOLEAN DEFAULT FALSE,
    status TEXT DEFAULT 'pending'  -- pending, fetched, failed
);

-- 페이지 fetch/추출
CREATE TABLE page_extractions (
    id SERIAL PRIMARY KEY,
    search_result_id INT REFERENCES search_results(id),
    raw_content_hash TEXT,  -- 원문 저장은 S3/파일, hash만 DB
    structured_data JSONB,  -- ScrapeGraphAI 출력
    extraction_schema TEXT, -- 사용된 스키마 버전
    status TEXT DEFAULT 'pending',  -- pending, extracted, partial, failed
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Claude 추론 결과
CREATE TABLE research_outputs (
    id SERIAL PRIMARY KEY,
    extraction_ids INT[],  -- 복수 extraction을 종합할 수 있음
    query_id INT REFERENCES search_queries(id),
    ticker TEXT,
    output_type TEXT,  -- sentiment, news_summary, event_detection
    output_data JSONB,
    model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Gemini (운영 안정성)

**Option B의 큐 기반 구조를 장기적으로 권장하되, MVP는 Option C로 시작한다.**

추가 제안:
- 캐싱 정책: 동일 URL은 24시간 내 재fetch하지 않음 (search_results.fetched + created_at 기준)
- Rate limiting: SearXNG는 자체 호스팅이라 제한 없지만, 대상 웹사이트에 대해 도메인별 초당 1회 제한
- 실패 처리: 3회 재시도 후 `failed` 상태로 마킹, 파이프라인은 부분 결과로 계속 진행
- ScrapeGraphAI 출력 검증: 필수 필드 누락 시 `partial`로 마킹

### GPT (실용 구현)

**Claude CLI 대신 Claude SDK(API)를 사용할 것을 권장한다.**

이유:
- CLI subprocess 호출은 프로세스 오버헤드와 에러 핸들링이 복잡하다
- `anthropic` Python SDK로 직접 호출하면 비동기 처리, 스트리밍, 에러 처리가 자연스럽다
- 다만 `tech_stack.md`에 "Claude CLI" 명시이므로 사용자 승인 필요

Research Contract 포맷 제안:

```json
{
  "ticker": "259960",
  "query": "크래프톤 2026년 실적 전망",
  "timestamp_utc": "2026-03-14T10:00:00Z",
  "sources": [
    {"url": "...", "title": "...", "extraction_id": 42}
  ],
  "sentiment": "bullish",
  "confidence": 0.72,
  "key_facts": ["..."],
  "risk_factors": ["..."],
  "summary": "..."
}
```

### Codex (레포 적합성)

**Option C를 기본으로 두되, 실행 경로는 "주문 직전 동기 호출"이 아니라 "리서치 스냅샷 생산"으로 분리하는 편이 더 안전하다.**

이유:
- 현재 시스템은 장중 주문 경로의 안정성이 더 중요하므로, 웹 fetch/render 지연이 Strategy B나 RL의 실시간 의사결정 경로를 직접 막지 않도록 해야 한다
- 따라서 SearchAgent는 `query/job -> source -> extraction -> research_output`를 생성하는 producer로 두고, Strategy B/RL은 해당 시점에 이미 저장된 snapshot만 읽는 구조가 운영 리스크가 낮다
- 현재 `tech_stack.md`에는 Claude CLI가 승인 경로로 적혀 있으므로, MVP는 CLI를 유지하되 `ReasoningClient` 같은 얇은 어댑터를 두어 이후 SDK 전환만 쉽게 만드는 편이 좋다

추가 제안:
- `page_extractions`에는 `raw_content_hash`만이 아니라 `raw_content_path` 또는 `blob_path`도 함께 남겨 재추론과 디버깅이 가능해야 한다
- Research Contract에는 `url`, `title` 외에 `source_id`, `published_at`, `retrieved_at`, `extraction_status`를 포함해 citation과 신선도 판단을 분리해야 한다
- 동일 URL의 파라미터 변형이 중복 저장되지 않도록 canonical URL 정규화와 도메인별 rate limit를 초기에 넣는 편이 장기적으로 비용이 덜 든다
- Claude reasoning은 페이지별 호출보다 query 기준 top-N source를 묶어 한 번에 수행하는 쪽이 비용, 지연, citation 일관성 측면에서 유리하다

## 6. Interim Conclusion

**Option C(하이브리드 파이프라인) + 단계별 DB 저장 구조로 MVP를 구현한다.**

구체적 결정 사항:

1. **진입점**: `src/agents/search_agent.py` — SearchAgent 클래스가 전체 파이프라인 조율
2. **검색**: SearXNG Docker 인스턴스에 `httpx`로 JSON API 호출
3. **페이지 fetch**: `asyncio.gather`로 병렬 fetch, JS-heavy 페이지는 Playwright Docker sidecar 경유
4. **구조화**: ScrapeGraphAI Docker 컨테이너에 HTTP API로 요청 (또는 Python 라이브러리 직접 호출)
5. **추론**: Claude CLI 또는 SDK (사용자 최종 확인 필요) — research contract JSON 생성
6. **저장**: 4-테이블 구조 (search_queries, search_results, page_extractions, research_outputs)
7. **캐싱**: URL 단위 24시간 캐시, 도메인별 rate limit 1req/sec
8. **Docker Compose 추가 서비스**: searxng, playwright-server (선택), scrapegraphai-worker (선택)
9. **Research Contract**: JSON 포맷으로 Strategy B prompt와 RL feature에 공급

## 7. Final Decision

(논의 후 확정)

## 8. Follow-up Actions

- [ ] `docker-compose.yml`에 SearXNG 서비스 정의 추가
- [ ] SearXNG `settings.yml` 초기 설정 (검색 엔진, 카테고리, 언어=ko)
- [ ] `src/agents/search_agent.py` 기본 구조 작성
- [ ] SearXNG JSON API 클라이언트 (`src/utils/searxng_client.py`)
- [ ] Playwright Docker sidecar 설정 또는 `playwright` pip 패키지 선택 확정
- [ ] ScrapeGraphAI 호출 방식 확정 (Docker API vs Python import)
- [ ] Claude CLI vs SDK 최종 결정 (tech_stack.md 업데이트 필요 시)
- [ ] DB 마이그레이션: 4-테이블 생성 SQL
- [ ] Research Contract JSON 스키마 정의 (`docs/research_contract.json`)
- [ ] Strategy B prompt에 research_output 주입 포인트 설계
- [ ] RL feature에 sentiment/key_facts 반영 방식 설계
- [ ] 통합 테스트: 검색 → 추출 → 추론 end-to-end

## 9. Closure Checklist

- [ ] 구조/장기 방향 변경 사항을 `.agent/roadmap.md`에 반영
- [ ] 이번 세션의 할 일을 `progress.md`에 반영
- [ ] 계속 유지되어야 하는 운영 규칙을 `MEMORY.md`에 반영
- [ ] 필요한 영구 문서 반영 후 이 논의 문서를 삭제
