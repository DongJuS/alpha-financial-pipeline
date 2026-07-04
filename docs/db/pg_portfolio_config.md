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
| daily_loss_limit_pct | INTEGER | Phase A Layer 3 일일 실현 손실 한도 (기본 3%). `_is_daily_loss_blocked` 소비. |
| individual_stop_loss_pct | INTEGER | Phase A Layer 1 개별 종목 손절 임계 (기본 7%). `_check_rule_based_exits` 소비. |
| take_profit_pct | INTEGER | Take profit 임계 (기본 5%). `_check_rule_based_exits` (Phase A) + Phase B 부분 매도 소비. |
| portfolio_drawdown_limit_pct | INTEGER | Phase A Layer 2 포트폴리오 drawdown 임계 (기본 8%). `_check_portfolio_drawdown` 소비. |
| enable_paper_trading | BOOLEAN | 페이퍼 트레이딩 활성화 |
| enable_real_trading | BOOLEAN | 실거래 활성화 |
| primary_account_scope | VARCHAR(10) | paper / real / virtual |

## 테이블 관계

- ← `trading_accounts(account_scope)` — primary_account_scope와 연결
- 독립 설정 테이블 (FK 없음, 단일 행)

## Sell strategy 리스크 파라미터 (Phase A 확장)

세 개의 `*_pct` 컬럼 (individual_stop_loss / take_profit / portfolio_drawdown_limit)
은 Phase A 하드 손절 3-layer 의 mandate 파라미터를 코드 하드코딩에서 DB config
로 이관한 것. 기존 `daily_loss_limit_pct` (Layer 3) 와 같은 축.

- 값 변경 시 `_check_rule_based_exits`, `_check_portfolio_drawdown`,
  `_is_daily_loss_blocked` 가 다음 사이클부터 즉시 새 값 소비.
- 감사 요건 상 하드코딩 회피. 모든 파라미터가 조회 가능해야 함.

전문 스펙: `docs/plans/SELL_STRATEGY_PHASES.md` §3-3.
