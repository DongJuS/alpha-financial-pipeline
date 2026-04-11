> 정책: 항상 200줄 이내를 유지한다.

# search_results

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `search_results` |
| 역할 | 웹 검색 결과. URL, 제목, 스니펫, 검색 엔진, 순위 기록. |
| 사용 여부 | ⏸ 중단 — Strategy S 개발 보류 (2026-03-28~). 스키마만 존재. |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 자동 증가 |
| query_id | INT FK | → search_queries.id |
| url | TEXT | 결과 URL |
| title | TEXT | 제목 |
| snippet | TEXT | 스니펫 |
| engine | TEXT | 검색 엔진 |
| rank | INT | 순위 |
| status | TEXT | pending / fetched / failed |

## 테이블 관계

- → `search_queries(id)` FK
- ← `page_extractions(search_result_id)` FK
