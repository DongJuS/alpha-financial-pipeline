> 정책: 항상 200줄 이내를 유지한다.

# aggregate_risk_snapshots

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `aggregate_risk_snapshots` |
| 역할 | 합산 리스크 스냅샷. 전체 포트폴리오 리스크 지표 시계열 기록. |
| 사용 여부 | ✅ 활성 — aggregate_risk.py에서 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| risk_data | JSONB | 리스크 데이터 (전체 포트폴리오 합산) |
| snapshot_at | TIMESTAMPTZ | 스냅샷 시각 |

## 테이블 관계

- 독립 테이블 (FK 없음)
- 데이터 출처: portfolio_positions, account_snapshots 기반 집계
