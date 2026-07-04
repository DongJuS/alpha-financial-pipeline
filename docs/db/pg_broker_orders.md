> 정책: 항상 200줄 이내를 유지한다.

# broker_orders

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `broker_orders` |
| 역할 | 브로커 주문 이력. PENDING → FILLED/REJECTED/CANCELLED 상태 전이. |
| 사용 여부 | ✅ 활성 — virtual_broker, KIS broker에서 주문 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| client_order_id | TEXT UNIQUE | 클라이언트 주문 ID |
| account_scope | VARCHAR(10) | paper / real / virtual |
| ticker | VARCHAR(10) | 종목코드 |
| side | VARCHAR(4) | BUY / SELL |
| order_type | VARCHAR(10) | MARKET / LIMIT |
| requested_quantity | INTEGER | 요청 수량 |
| filled_quantity | INTEGER | 체결 수량 |
| status | VARCHAR(16) | PENDING/FILLED/REJECTED/CANCELLED |
| signal_source | VARCHAR(10) | A/B/BLEND/RL/S/L/EXIT/VIRTUAL |
| blend_meta | JSONB | 블렌딩 메타데이터 |
| strategy_id | VARCHAR(10) | 전략 ID |
| trigger_source | VARCHAR(20) | Sell strategy Phase A~D 발주 원인: `llm_signal` / `hard_stop_L1` / `hard_stop_L2` / `take_profit` / `time_exit` / `rebalance` |
| trigger_snapshot | JSONB | 트리거 시점 layer/가격/상태 스냅샷. 감사 재현용. |

## 테이블 관계

- → `trading_accounts(account_scope)` 논리적 참조
- → `trade_history` — 체결 시 trade_history에 기록 생성

## Sell strategy 컬럼 (Phase A~D 감사)

`signal_source` (기존) 와 `trigger_source` (Phase A 신규) 는 축이 다르다:
- `signal_source` = **누가 냈나** (전략 or EXIT rule)
- `trigger_source` = **왜 매도가 나갔나 세부 원인** (LLM signal 인지 hard stop L1 인지)
- Hard stop 발주 시 두 축 병기 예: `signal_source='EXIT'`, `trigger_source='hard_stop_L1'`

`trigger_snapshot` 은 트리거 시점 상태를 dict 로 저장해 사후 감사 (dry-run
오탐 판정, 파라미터 재조정, 24 h 반등 조회) 를 가능하게 한다.

전문 스펙: `docs/plans/SELL_STRATEGY_PHASES.md` §3-3.
