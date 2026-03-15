# 🧭 SEARCH_PIPELINE.md — 검색/스크래핑 파이프라인 흐름

> 검색 요청이 들어온 뒤 결과가 전략/RL 계층에 전달되기까지의 단계를 정리합니다.

---

## 1. 처리 단계

```text
1. query generation
2. SearXNG search
3. candidate filtering
4. page fetch/render
5. ScrapeGraphAI structuring
6. Claude CLI extraction
7. storage and retrieval
8. strategy / RL consumption
```

---

## 2. 단계별 설명

### 1) Query Generation
- 티커, 기업명, 섹터, 이벤트 키워드를 조합
- 검색 목적을 `news`, `filing`, `research`, `macro` 등으로 태깅

### 2) SearXNG Search
- 상위 후보 URL, 제목, snippet, 도메인 수집
- 검색 실행 시점과 질의 파라미터 저장

### 3) Candidate Filtering
- 중복 URL 제거
- 허용 도메인/차단 도메인 정책 반영
- 종목 연관성 낮은 결과 제거

### 4) Page Fetch / Render
- 일반 HTML 페이지는 직접 fetch
- JS-heavy 페이지는 렌더러를 통해 DOM 확보

### 5) ScrapeGraphAI Structuring
- 본문, 표, 날짜, 작성자, 핵심 섹션을 구조화
- 실패 시 구조화 오류 상태 기록

### 6) Claude CLI Extraction
- 구조화 결과를 바탕으로 사실, 근거, 이벤트, 영향 포인트 추출
- 투자에 유용한 feature 또는 메모로 정리

### 7) Storage and Retrieval
- 검색 job, 결과 URL, 원문 소스, 추출 결과를 분리 저장
- 이후 동일 query 또는 source를 재조회 가능하게 유지

### 8) Strategy / RL Consumption
- Strategy B는 토론 입력 컨텍스트로 활용
- RL은 feature engineering 또는 event signal 보강에 활용

---

## 3. 상태 모델

검색 job은 아래 상태를 가질 수 있습니다.

| 상태 | 의미 |
|------|------|
| `queued` | 실행 대기 |
| `running` | 검색/스크래핑/추출 진행 중 |
| `completed` | 모든 단계 완료 |
| `partial` | 일부 source 또는 extraction 실패 |
| `failed` | 전체 실패 |

---

## 4. 재실행 기준

- SearXNG 응답 실패
- fetch/render 타임아웃
- ScrapeGraphAI 구조화 실패
- Claude CLI extraction 실패

실패 원인은 단계별로 기록하고, 재실행 시 이전 상태와 비교할 수 있어야 합니다.

---

## 5. 출력 계약 예시

```json
{
  "query_id": "rq_20260314_001",
  "ticker": "005930",
  "intent": "research",
  "sources": [
    {
      "source_id": "src_1",
      "url": "https://example.com/report",
      "structured": true,
      "extraction_id": "ext_1"
    }
  ]
}
```

---

*Last updated: 2026-03-14*
