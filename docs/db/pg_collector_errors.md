> 정책: 항상 200줄 이내를 유지한다.

# collector_errors

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `collector_errors` |
| 역할 | 데이터 수집 오류 로그. fdr/kis_ws/krx 소스별 에러 추적. |
| 사용 여부 | ✅ 활성 — collector 에러 발생 시 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| source | VARCHAR(30) | fdr / kis_ws / krx |
| ticker | VARCHAR(10) | 관련 종목 (nullable) |
| error_type | TEXT | 에러 유형 |
| message | TEXT | 에러 메시지 |
| resolved | BOOLEAN | 해결 여부 |
| occurred_at | TIMESTAMPTZ | 발생 시각 |

## 테이블 관계

- 독립 로그 테이블 (FK 없음)
