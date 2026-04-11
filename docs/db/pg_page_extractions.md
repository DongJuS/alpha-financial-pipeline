> 정책: 항상 200줄 이내를 유지한다.

# page_extractions

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `page_extractions` |
| 역할 | 크롤링 추출 결과. 웹 페이지에서 구조화 데이터 추출. |
| 사용 여부 | ⏸ 중단 — Strategy S 개발 보류 (2026-03-28~). 스키마만 존재. |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 자동 증가 |
| search_result_id | INT FK | → search_results.id |
| structured_data | JSONB | 구조화 추출 데이터 |
| extraction_schema | TEXT | 추출 스키마 |
| status | TEXT | pending / extracted / partial / failed |
| error_message | TEXT | 실패 시 에러 |

## 테이블 관계

- → `search_results(id)` FK
- ← `research_outputs(extraction_ids)` 배열 참조
