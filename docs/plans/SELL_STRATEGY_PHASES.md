# Sell Strategy — Phase A~D 로드맵

> **작성일**: 2026-07-02
> **상태**: draft (Phase A 착수 대기)
> **관련 코드**: `src/agents/predictor.py`, `src/schedulers/unified_scheduler.py`, `broker_orders` 테이블
> **선행 문서**: `docs/REAL_TRADING_GUIDE.md`, `docs/RL_TRADING.md`

---

## 0. TL;DR

시스템에 이미 있는 것: LLM 프롬프트의 SELL 가이드 (익절 +5% / 손절 -3% 권장).

시스템에 없는 것 (본 로드맵의 스코프): **LLM 판단을 우회하는 안전망 룰 4종**.

1. **Phase A — Hard Stop-Loss** (LLM 무관 강제 손절)
2. **Phase B — Partial Exit** (단타 특화, 2-level scaling out)
3. **Phase C — Time-based Exit** (3일 강제 청산)
4. **Phase D — Rebalancing** (단타 mandate 상 스킵)

각 phase 는 이전 phase 의 30일 dry-run 관측 후에만 다음 진입.

---

## 1. Investment Mandate (사용자 결정, 2026-07-02)

본 로드맵의 모든 파라미터가 이 mandate 로부터 파생된다. 파라미터 변경이 필요하면 먼저 mandate 를 재검토한다.

| 축 | 결정 | 파생 원칙 |
|---|---|---|
| 자본 우선순위 | **자본 보존 최우선** | 감내 손실 룰 tight, 리스크 감내 지표는 프로 표준 준수 |
| 투자 기간 | **단타 (1~3일)** | 오버나이트 리스크 방어, 매일 청산 원칙, 리밸런싱 skip |
| 시스템 신뢰도 | **완전 자동** | Human-in-the-loop 없음, hard stop 즉시 실행, Telegram 은 사후 알림만 |
| 감내 손실 | 일일 실현 **-3%** · 포트 drawdown **-8%** · 개별 종목 **-7%** | Hard stop 3-layer 파라미터 |
| 감사 vs 속도 | **감사 최우선** | `broker_orders.trigger_snapshot` JSONB 상세 저장, 배포 신중 (dry-run 필수) |
| UX 대상 | **본인 (전문)** | 알림 수치 밀도 높음, UI 는 chart / metric 위주 |
| 초기 자본 | **10-20만원** | Real 전환 시. 슬리피지 미미 가정 유효, 심리 부담 낮음 |
| 검증 목적 | Paper 3개월 관측 후 real 전환 | 승산 게이트 통과 필수 (§6) |

### 1-1. Mandate 내부 상충 지점 (사전 문서화)

- **"자본 보존" + "단타"** — 이론적으로 상충 (단타는 손실 노출 빈도 큼). 본 시스템에서는 **단타 mandate 를 알파 검증 목적으로 해석**하고 자본 보존은 하드 손절 tight 로 달성.
- **"완전 자동" + "감내 -7% 개별 손실"** — Real 계좌에서는 10-20만원 소액 전제라 감내 크게. 자본 증액 시 감내 재조정 (§8 open questions).

---

## 2. 설계 세션 요약

Kim (Head of Systematic Trading, ex-JP Morgan Quant + Toss Invest) 과 Yoon (Principal Engineer, ex-JP Morgan Trade OMS + Toss 실시간 호가) 이 각 phase 를 검토했다. 상세 논의는 conversation history 참조. 본 절은 **개발자가 착수 전 반드시 인지해야 할 원칙 5개** 로 압축.

### 원칙 1. LLM 은 신호이지 실행자가 아니다

LLM 이 SELL 안 냈다는 이유로 손실을 방치하는 순간 이 시스템은 트레이딩 시스템이 아니다. Hard stop 은 LLM 의 판단과 무관하게 트리거된다.

### 원칙 2. 한국 시장 4대 제약

모든 룰 설계 시 다음을 인지: **T+2 결제**, **1주 단위 거래**, **상하한 30%**, **거래시간 09:00~15:30 KST**. 룰이 이 제약을 위반하면 폐기.

### 원칙 3. 3-layer audit tracing

모든 매도 결정은 **trigger event · pre-trade risk check · post-trade audit** 3층에서 재현 가능해야 한다. `broker_orders.trigger_source` + `trigger_snapshot` 두 컬럼이 이 원칙의 표현.

### 원칙 4. avg_fill_price 기준 계산

손절/익절 계산은 반드시 `avg_fill_price` 기준. `requested_price` 기준은 시장가 슬리피지가 실제 손절선을 왜곡한다.

### 원칙 5. 파라미터 튜닝은 데이터가 결정한다

Phase A~C 각 dry-run 30일 관측 후 실 활성. 3개월 후 데이터로 파라미터 재조정 (§6 승산 게이트).

---

## 3. Phase A — Hard Stop-Loss

### 3-1. 스코프

3-layer 구조. 하나라도 트리거 시 즉시 매도 발주.

| Layer | Trigger | Action | 우선순위 |
|---|---|---|---|
| **1** | 개별 종목 현재가 ≤ `avg_fill_price × 0.93` (**-7%**) | 해당 포지션 시장가 전량 매도 | 최고 |
| **2** | 포트 realized+unrealized drawdown ≤ **-8%** (전주 종가 대비) | 신규 매수 정지 + unrealized 최약체 2종목 시장가 매도 | 중 |
| **3** | 당일 realized 손실 ≤ **-3%** (전일 종가 대비) | 그날 모든 신규 주문 취소 + 다음 거래일까지 매매 lockout | 상 |

Layer 우선순위: Layer 3 가 Layer 1, 2 에 동시 발동하는 상황에서는 Layer 3 만 실행 (lockout 이 다른 매도도 정지).

### 3-2. 아키텍처

**Trigger 잡**: `hard_stop_loss_check`
- Interval: **10초** (KIS WebSocket tick 반영 지연 감안 상한)
- 잡 위치: `src/schedulers/unified_scheduler.py`
- 로직 위치: `src/services/hard_stop_loss.py` (신규)

**동시성 제어**:
```
Redis lock: `hard_stop_loss:{ticker}` TTL 25s
Client order ID: HSL_{ticker}_{yyyymmdd_hhmmss}
  → KIS 가 중복 감지 (동일 client_order_id reject)
```

**Pre-trade check**:
- KRX 거래 시간 확인 (09:00~15:30 밖이면 defer)
- 종목 거래정지/정리매매 상태 확인 (KIS API)
- 실패 시 매도 안 함 + Telegram 크리티컬 알림 (원칙 5 위반 회피 — safer to hold)

**Audit tracing (모든 hard stop 발주 시)**:
```
broker_orders.trigger_source = 'hard_stop'
broker_orders.trigger_snapshot = {
  layer: 1|2|3,
  avg_fill_price: ...,
  current_price: ...,
  stop_line: ...,
  portfolio_dd_pct: ...,
  daily_realized_pnl_pct: ...,
  triggered_at: ISO8601
}
```

### 3-3. 데이터 스키마

**신규 컬럼** (`broker_orders`):
```sql
ALTER TABLE broker_orders
    ADD COLUMN trigger_source VARCHAR(20) NULL,  -- 'llm_signal', 'hard_stop', 'time_exit', 'rebalance'
    ADD COLUMN trigger_snapshot JSONB NULL;

COMMENT ON COLUMN broker_orders.trigger_source IS 'Sell strategy phase A~D trigger origin';
COMMENT ON COLUMN broker_orders.trigger_snapshot IS 'JSONB — layer/pricing/state at trigger time. Audit reproducibility.';
```

### 3-4. Dry-run 프로토콜

Phase A 배포 후 **30일** dry-run:
- `HARD_STOP_LOSS_DRY_RUN=true` env → 실 매도 발주 X, 로그 + Telegram 알림만
- 관측 지표:
  - Layer 별 trigger 빈도 (Layer 1 하루 평균 몇 회)
  - Trigger 시점 vs LLM 이 SELL signal 낸 시점 delta
  - Trigger 이후 24h 반등 여부 (오탐 비율)
- **오탐 30% 초과 시 파라미터 재검토** (Layer 1 -7% → -10% 등)
- 실 활성 게이트: Layer 별 trigger 빈도 안정 + 오탐 30% 미만

### 3-5. 실패 시나리오

| 시나리오 | 대응 |
|---|---|
| KIS API timeout | 3회 재시도 (지수 backoff), 실패 시 Telegram 크리티컬 알림 |
| Redis lock 획득 실패 | 다음 10초 사이클 재시도 |
| 현재가 조회 실패 (Redis+DB 모두) | **매도 안 함** + Telegram 알림 |
| 매도 후 재트리거 | `broker_orders.status='FILLED'` 확인 후 skip |
| 상하한가 도달 | 상한가 미체결 위험 있으므로 지정가 매도로 fallback |

### 3-6. 파일 변경 목록 (착수 시)

- **신규**: `src/services/hard_stop_loss.py`
- **신규**: `test/test_hard_stop_loss.py`
- **수정**: `src/schedulers/unified_scheduler.py` (잡 등록)
- **수정**: `scripts/db/migrate_add_broker_orders_trigger_fields.py` (신규 python migration script — 기존 관행)
- **수정**: `src/api/routers/market.py` 또는 `system_health.py` — dry-run 상태 조회 endpoint (선택)

---

## 4. Phase B — Partial Exit (단타 특화 2-level)

### 4-1. 스코프

단타 mandate 상 3-level scaling out 은 오버엔지니어링. 2-level 만.

| Level | Trigger | Action |
|---|---|---|
| **익절 1** | 현재가 ≥ `avg_fill_price × 1.03` (**+3%**) | 보유 수량의 **50%** 시장가 매도 + 잔여 50% 의 stop_line 을 `avg_fill_price` 로 상향 (break-even lock) |
| **익절 2** | 현재가 ≥ `avg_fill_price × 1.05` (**+5%**) | 잔여 수량 **100%** 시장가 매도 (완전 청산) |

**한국 시장 특수 처리**:
- 1주 단위 거래 → 50% 계산 시 반올림 내림
- 잔량 1-2주 남으면 익절 2 트리거 시 함께 정리
- 최소 매도 단위 1주라 예: 10주 * 50% = 5주, 11주 * 50% = 5주

### 4-2. 상태 머신

포지션 라이프사이클:
```
ENTERED (매수 체결)
  ↓ +3% 도달
LEVEL_1_EXITED (50% 매도, remaining=50%, stop_line=avg_fill_price)
  ↓ +5% 도달
LEVEL_2_EXITED (완전 청산)

또는 stop 도달:
  ↓
STOP_HIT (전량 매도) ← Phase A hard stop 처리
```

### 4-3. 데이터 스키마

**신규 테이블**: `position_state` (포지션 라이프사이클 명시적 관리)
```sql
CREATE TABLE position_state (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    account_scope VARCHAR(10) NOT NULL,
    entry_order_id BIGINT NOT NULL REFERENCES broker_orders(id),
    original_shares INT NOT NULL,
    remaining_shares INT NOT NULL,
    avg_fill_price INT NOT NULL,
    lifecycle_state VARCHAR(20) NOT NULL,  -- ENTERED, LEVEL_1_EXITED, LEVEL_2_EXITED, STOP_HIT, TIME_EXITED
    current_stop_line INT NOT NULL,  -- 상향 조정 시 갱신
    entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_state_change_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ NULL,
    UNIQUE (ticker, account_scope, entry_order_id)
);

CREATE INDEX idx_position_state_lifecycle ON position_state(lifecycle_state)
    WHERE lifecycle_state IN ('ENTERED', 'LEVEL_1_EXITED');
```

### 4-4. 아키텍처

**Trigger 잡**: `partial_exit_check`
- Interval: **10초** (hard stop 과 동일 사이클, 그러나 별개 잡)
- Redis lock: `partial_exit:{ticker}:{entry_order_id}` TTL 25s
- 하드 손절과의 우선순위: **Hard stop 우선**. 동시 트리거 시 hard stop 만 실행.

### 4-5. Dry-run 프로토콜

Phase A 30일 관측 완료 후 착수. Phase B 도 30일 dry-run 후 실 활성.

관측 지표:
- Level 1 도달 후 Level 2 도달률 (%)
- Level 1 도달 후 stop 회귀 비율
- 완전 청산 (Level 2) 평균 수익률

---

## 5. Phase C — Time-based Exit

### 5-1. 스코프

단타 mandate 상 최대 보유 기간 **3 거래일** 초과 시 강제 청산.

| Rule | Trigger | Action |
|---|---|---|
| **T+3 청산** | `entered_at + 3 거래일 = today` AND 15:20 KST 도달 | 시장가 매도 (당일 종가 근접 청산) |
| **Overnight 방어** | 당일 진입 후 15:20 KST 미청산 | Level 1 도달 안 했어도 청산 (단타 원칙) |

`entered_at + 3 거래일` 계산 시:
- 주말 / 공휴일 skip
- 오늘 기준 D+3 = 다음 3번째 거래일

### 5-2. 아키텍처

**Trigger 잡**: `time_based_exit_check`
- Cron: **매일 15:20 KST** (장 마감 10분 전, 유동성 안정)
- 위치: `src/schedulers/unified_scheduler.py`

**Pre-trade check**:
- 상하한가 도달 여부 (상한가면 지정가로, 하한가면 hard stop 이 이미 처리)
- 거래정지 시 시장가 매도 불가 → 다음 거래일까지 defer + Telegram 알림

**주문 타입**:
- 15:20 → 시장가 (10분 안에 체결)
- 실패 시 15:25 지정가 (현재가 -1 tick) 재시도

### 5-3. 데이터 스키마

Phase B 의 `position_state.entered_at` 사용. 추가 컬럼 불필요.

### 5-4. Dry-run 프로토콜

Phase B 완료 후 착수. 30일 dry-run.

관측 지표:
- T+3 청산 시 손익 분포 (평균, median, min, max)
- Overnight 청산 비율 (당일 진입 종목의 15:20 미청산 %)

---

## 6. Phase D — Rebalancing (**SKIP**)

**결정: 스킵.**

**근거**: 단타 mandate 상 리밸런싱은 정의상 매일 clear 로 자동 달성. 별도 monthly / weekly 리밸런싱은 mandate 와 상충.

향후 mandate 를 "단타 + 중장기 혼합" 으로 변경 시 별도 세션에서 재검토.

---

## 7. 승산 검증 게이트 (Paper → Real)

Phase A~C 실 활성화 후 **3개월 관측** → 다음 게이트 **모두 통과** 시 real 전환 (초기 10-20만원):

| 지표 | 목표 | 근거 |
|---|---|---|
| **Sharpe ratio** | > 0.8 | 개인 단타 시장에서 실질적 알파의 하한 |
| **Win rate** | > 55% | 단타 승률 시장 통계 45~50% 대비 유의 |
| **Max drawdown** | < 10% | 감내 -8% 상에서 -10% 넘으면 시스템 재검토 |
| **월간 승률** | 12개월 중 5개월 이상 + | 계절성 편향 회피 |
| **Hard stop 빈도** | 하루 평균 < 5회 | 파라미터 안정성 (튜닝 초과 방지) |
| **Time exit 기대값** | 청산 시 손실 < 익절 시 이익 (양수) | 시간 기반 청산이 알파 훼손 안 함 |

**한 개라도 미달 시**:
- Mandate 재검토 (예: `max_holding_days` 3 → 5)
- 재검증 3개월

---

## 8. Open Questions (향후 결정)

우선순위 순.

1. **Real 전환 시 초기 자본 (10-20만원) 소진 시**: 자본 증액 방식 (수익 재투자 vs 외부 seed)? 감내 손실 재조정 방식?
2. **Phase A Layer 2 (포트 drawdown -8%)**: "최약체 2종목" 정의 — unrealized pnl 하위 vs Sharpe 하위 vs 매수 오래된 순?
3. **Phase B Level 1 트리거 (+3%)**: 시장 조건 (변동성) 반영해 동적 조정? 예: KOSPI VIX 유사 지표 상 상승 시 +5% 로.
4. **Real 계좌 잔고 조회**: 지금 UI 의 실계좌 응답이 flat shape 이라 아직 미완. Phase A 배포 전 실 계좌 authentication 이슈 해결 필요 (`docs/REAL_TRADING_GUIDE.md` 참조).
5. **하드 손절 vs 시장 gap**: 밤 사이 -15% gap down 시 hard stop 은 아침 09:00 시장가 매도 = 이미 -15% 실현. 이 상황 방어 룰 (선매도 조건 등)?
6. **KIS API rate limit**: Hard stop 10초 interval + 여러 종목 동시 트리거 시 rate limit 초과 위험. 우선순위 큐 필요?

---

## 9. Immediate Next Step (Phase A 착수)

### 착수 순서

1. 본 문서 PR merge (기획 base 확정)
2. Schema migration PR (`broker_orders` 에 `trigger_source`, `trigger_snapshot` 컬럼)
3. `src/services/hard_stop_loss.py` + 잡 등록 + dry-run 모드 + 테스트 PR
4. Deploy → 30일 dry-run 관측
5. 실 활성화 결정 (관측 지표 통과 시)

### 착수 시점 결정 필요 지점

- Real 계좌 잔고 조회 이슈 (§8-4) — Phase A 는 paper 계좌 대상이라 선진행 가능
- 30일 dry-run 시 실 매매 발생 안 함 → paper 계좌에 영향 없음
- **선행 필요 없음. 지금 착수 가능.**

---

## Appendix — Kim / Yoon 세션 인용 (설계 근거)

### A. 하드 손절 -7% 근거

> "-3% 는 프롬프트 가이드일 뿐 하드 아님. -7% = 일반적으로 대형주 daily σ 의 2.5배, 노이즈 아닌 트렌드." — Kim

### B. avg_fill_price 기준 계산

> "Yoon, 이거 반드시 `avg_fill_price` 기준으로 계산해. `requested_price` 아니야. 시장가 주문의 슬리피지가 곧 실제 손절 지점을 왜곡한다." — Kim

### C. 완전 자동 + 감사 우선 조합의 이상성

> "감사 최우선 + 소액 자본 + 3개월 검증 목적 = 완벽한 상황. 감사 로그 상세하게 남기는 오버헤드가 소액이라 성능 임팩트 미미. 3개월 후 데이터로 파라미터 재조정 = 우리가 Phase E 에서 예정한 튜닝 사이클과 정확히 맞음." — Yoon

### D. 단타 mandate 의 리밸런싱 관계

> "단타 mandate 하에서 monthly rebalancing 은 의미 없음. 매일 clear = 매일 자동 리밸런스. Phase D 는 mandate 상 스킵." — Kim

### E. Trailing stop 미도입 근거

> "3-level scaling out 하나만 우선. Trailing stop 로직은 별도 세션 필요. 심리 안전망은 Level 1 하나만 있어도 절반은 잡음." — Kim

---

## 문서 이력

- 2026-07-02: 초안. Mandate 확정 (§1). Phase A~D 스코프 확정.
