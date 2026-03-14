# 🔎 SEARCH_STACK.md — 검색/스크래핑 스택 개요

> 이 문서는 연구용 검색과 웹 추출 파이프라인의 구조와 사용 원칙을 설명합니다.

---

## 1. 기본 방향

검색/스크래핑 스택은 기존 트레이딩 시스템을 대체하지 않습니다.
이 스택은 Strategy B와 RL lane에 정성적 연구 데이터와 근거 문서를 공급하는 확장 레이어입니다.

핵심 경로:

```text
SearXNG
  -> 웹 페이지 접속(fetch/render)
  -> ScrapeGraphAI
  -> Claude CLI
```

---

## 2. 사용 원칙

- Tavily는 사용하지 않습니다.
- 검색은 반드시 `SearXNG`를 통해 시작합니다.
- `ScrapeGraphAI`는 페이지 구조화와 파싱만 담당합니다.
- 최종 추출, 요약, 판단은 `Claude CLI` 계층이 맡습니다.
- 결과는 query, source, extraction 단위로 추적 가능해야 합니다.

---

## 3. 구성요소 역할

| 구성요소 | 역할 |
|----------|------|
| `search_query_agent` | 종목/테마별 검색 질의 생성, 검색 결과 후보 URL 수집 |
| fetch/render worker | 원문 HTML, 동적 렌더링 결과 수집 |
| `ScrapeGraphAI` | 본문, 표, 메타데이터 등 구조화 출력 생성 |
| `claude_extraction_agent` | 요약, 팩트 추출, 투자 관련 신호/feature 정리 |

---

## 4. 입력과 출력

입력:
- 티커, 기업명, 산업 키워드
- 거시 이벤트, 공시, 뉴스, 경쟁사 동향
- 검색 시간 범위와 우선 언어

출력:
- 검색 결과 목록
- 출처 문서 원문/메타데이터
- Claude 기반 구조화 추출 결과
- Strategy/RL에서 재사용 가능한 feature 또는 memo

---

## 5. 운영 가드레일

- 검색 결과가 있어도 출처 접근에 실패하면 추출 단계로 넘기지 않습니다.
- 추출 결과에는 원문 URL과 timestamp를 반드시 함께 남깁니다.
- 페이지 구조화 실패는 빈 요약으로 삼키지 않고 오류 상태로 기록합니다.
- 검색 결과의 품질이 낮을 경우 기존 Strategy A/B는 그대로 동작해야 합니다.

---

*Last updated: 2026-03-14*
