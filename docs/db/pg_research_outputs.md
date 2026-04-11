> 정책: 항상 200줄 이내를 유지한다.

# research_outputs

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `research_outputs` |
| 역할 | LLM 리서치 결과. 검색+추출 데이터를 Claude로 분석한 결과물. |
| 사용 여부 | ⏸ 중단 — Strategy S 개발 보류 (2026-03-28~). 스키마만 존재. |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 자동 증가 |
| query_id | INT FK | → search_queries.id |
| ticker | VARCHAR(10) | 관련 종목 |
| extraction_ids | INTEGER[] | 사용된 page_extractions ID 배열 |
| output_type | TEXT | research_contract 등 |
| output_data | JSONB | 분석 결과 |
| model_used | TEXT | 사용 LLM |
| status | TEXT | completed / partial / failed |

## 테이블 관계

- → `search_queries(id)` FK
- → `page_extractions(id)` 배열 참조 (extraction_ids)
