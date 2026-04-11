> 정책: 항상 200줄 이내를 유지한다.

# real_trading_audit

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `real_trading_audit` |
| 역할 | 실거래 전환 감사 로그. paper↔real 전환 시 readiness 검증 결과 기록. |
| 사용 여부 | ✅ 활성 — API 실거래 전환 요청 시 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| requested_at | TIMESTAMPTZ | 요청 시각 |
| requested_by_email | TEXT | 요청자 이메일 |
| requested_paper_enabled | BOOLEAN | 페이퍼 활성화 요청 |
| requested_real_enabled | BOOLEAN | 실거래 활성화 요청 |
| requested_primary_account_scope | VARCHAR(10) | paper / real |
| confirmation_code_ok | BOOLEAN | 확인 코드 검증 |
| readiness_passed | BOOLEAN | 준비도 검증 통과 |
| readiness_summary | JSONB | 준비도 상세 |
| applied | BOOLEAN | 실제 적용 여부 |

## 테이블 관계

- → `portfolio_config` — 전환 결과 반영 대상
- 독립 감사 테이블 (FK 없음)
