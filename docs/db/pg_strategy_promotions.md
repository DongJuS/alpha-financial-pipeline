> 정책: 항상 200줄 이내를 유지한다.

# strategy_promotions

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `strategy_promotions` |
| 역할 | 전략 승격 기록. virtual → paper → real 단계별 승격 이력. |
| 사용 여부 | ✅ 활성 — strategy_promotion.py에서 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| strategy_id | VARCHAR(10) | 전략 ID |
| from_mode | VARCHAR(10) | virtual / paper / real |
| to_mode | VARCHAR(10) | virtual / paper / real |
| criteria_snapshot | JSONB | 승격 기준 스냅샷 |
| actual_snapshot | JSONB | 실제 성과 스냅샷 |
| approved_by | VARCHAR(50) | 승인자 (기본 system) |
| forced | BOOLEAN | 강제 승격 여부 |

## 테이블 관계

- → `trading_accounts(strategy_id)` 논리적 참조
- 독립 이력 테이블 (FK 없음)
