> 정책: 항상 200줄 이내를 유지한다.

# operational_audits

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `operational_audits` |
| 역할 | 운영 감사 로그. 보안/리스크 규칙/페이퍼 검증/실거래 검증 결과. |
| 사용 여부 | ✅ 활성 — smoke_test, 운영 검증 시 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| audit_type | VARCHAR(30) | security / risk_rules / paper_reconciliation / real_reconciliation |
| passed | BOOLEAN | 통과 여부 |
| summary | TEXT | 요약 |
| details | JSONB | 상세 내용 |
| executed_by | TEXT | 실행 주체 |
| created_at | TIMESTAMPTZ | 생성 시각 |

## 테이블 관계

- 독립 감사 테이블 (FK 없음)
