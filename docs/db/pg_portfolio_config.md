> 정책: 항상 200줄 이내를 유지한다.

# portfolio_config

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `portfolio_config` |
| 역할 | 포트폴리오 전역 설정. 단일 행으로 운영. 블렌드 비율, 리스크 한도, 거래 모드 관리. |
| 사용 여부 | ✅ 활성 — orchestrator, portfolio_manager, API에서 참조 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 단일 행 |
| strategy_blend_ratio | NUMERIC(3,2) | A:B 블렌드 비율 (기본 0.50) |
| max_position_pct | INTEGER | 최대 포지션 비중 (기본 20%) |
| daily_loss_limit_pct | INTEGER | 일일 손실 한도 (기본 3%) |
| enable_paper_trading | BOOLEAN | 페이퍼 트레이딩 활성화 |
| enable_real_trading | BOOLEAN | 실거래 활성화 |
| primary_account_scope | VARCHAR(10) | paper / real / virtual |

## 테이블 관계

- ← `trading_accounts(account_scope)` — primary_account_scope와 연결
- 독립 설정 테이블 (FK 없음, 단일 행)
