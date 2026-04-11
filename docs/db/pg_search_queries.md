> 정책: 항상 200줄 이내를 유지한다.

# search_queries

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `search_queries` |
| 역할 | SearXNG 검색 파이프라인 쿼리 기록. Strategy S(Search) 입력. |
| 사용 여부 | ⏸ 중단 — Strategy S 개발 보류 (2026-03-28~). 스키마만 존재. |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 자동 증가 |
| query | TEXT | 검색 쿼리 |
| ticker | VARCHAR(10) | 관련 종목 |
| category | TEXT | 카테고리 (기본 general) |
| status | TEXT | pending / completed / failed |
| result_count | INTEGER | 결과 수 |

## 테이블 관계

- ← `search_results(query_id)` FK
- ← `research_outputs(query_id)` FK
