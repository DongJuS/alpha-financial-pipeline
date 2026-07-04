# Sell Strategy — Phase A~D 로드맵

> **작성일**: 2026-07-02 (초안), **최종 갱신**: 2026-07-04 (revision)
> **상태**: draft (Phase A 착수 대기)
> **관련 코드**: `src/agents/portfolio_manager.py` (`_check_rule_based_exits`, `_is_daily_loss_blocked`), `src/schedulers/unified_scheduler.py`, `src/schedulers/distributed_lock.py`, `src/services/trading_mode.py`, `portfolio_config` / `broker_orders` 테이블
> **선행 문서**: `docs/REAL_TRADING_GUIDE.md`, `docs/RL_TRADING.md`

---

## 0. TL;DR

### 시스템에 이미 있는 것 (실제 코드 조사 결과)

초안은 "LLM 프롬프트의 SELL 가이드만 있고 실 매도 룰은 없다" 로 시작했으나, 코드 재조사 결과 다음이 이미 살아 있음:

| 기능 | 위치 | 상태 |
|---|---|---|
| **LLM 무관 강제 매도 rule** | `PortfolioManagerAgent._check_rule_based_exits` | 활성. 단 파라미터 하드코딩 (`stop_loss_pct=-3.0`, `take_profit_pct=5.0`) — `portfolio_config` 에 컬럼 없음. |
| **일일 손실 회로 차단** | `PortfolioManagerAgent._is_daily_loss_blocked` | 활성. `portfolio_config.daily_loss_limit_pct=3` 소비. 초과 시 신규 주문 skip + `_publish_circuit_breaker`. |
| **분산 락 인프라** | `src/schedulers/distributed_lock.py` (`DistributedLock`) | 활성. Redis SET NX EX + Lua atomic. `unified_scheduler` 모든 잡에 자동 적용. |
| **Runtime flag 인프라** | `src/services/trading_mode.py` | Redis + env fallback 패턴. Dry-run flag 도 이 패턴 재사용 가능. |
| **포트폴리오 drawdown 감시** | 없음 (`aggregate_risk.py` 는 exposure 관리이지 drawdown 아님) | 신규 필요. |

### 로드맵 스코프

Phase A~D 는 위 기존 기반을 **파라미터화 + 감사 컬럼 추가 + 신규 잡 등록 + 신규 method 확장** 으로 구성. **신규 서비스 파일은 원칙적으로 없음** (원칙 6 참조).

1. **Phase A — Hard Stop-Loss** (3-layer 안전망 통합)
2. **Phase B — Partial Exit** (단타 특화 2-level scaling out)
3. **Phase C — Time-based Exit** (T+3 강제 청산 + overnight 방어)
4. **Phase D — Rebalancing** (**SKIP** — 단타 mandate 상)

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
| 검증 목적 | Paper 3개월 관측 후 real 전환 | 승산 게이트 통과 필수 (§7) |

### 1-1. Mandate 내부 상충 지점 (사전 문서화)

- **"자본 보존" + "단타"** — 이론적으로 상충 (단타는 손실 노출 빈도 큼). 본 시스템에서는 **단타 mandate 를 알파 검증 목적으로 해석**하고 자본 보존은 하드 손절 존재 + 파라미터 완화 (Layer 1 -3% → -7%) 로 승률 확보.
- **"완전 자동" + "감내 -7% 개별 손실"** — Real 계좌에서는 10-20만원 소액 전제라 감내 크게. 자본 증액 시 감내 재조정 (§8 open questions).

---

## 2. 설계 원칙

Kim (Head of Systematic Trading, ex-JP Morgan Quant + Toss Invest) 과 Yoon (Principal Engineer, ex-JP Morgan Trade OMS + Toss 실시간 호가) 이 각 phase 를 검토했다. 본 절은 **개발자가 착수 전 반드시 인지해야 할 원칙 6개** 로 압축. 원칙 6 은 revision 시 추가.

### 원칙 1. LLM 은 신호이지 실행자가 아니다

LLM 이 SELL 안 냈다는 이유로 손실을 방치하는 순간 이 시스템은 트레이딩 시스템이 아니다. Hard stop 은 LLM 의 판단과 무관하게 트리거된다.

**부분 구현 상태**: `_check_rule_based_exits` 가 이 원칙의 부분 구현이나 파라미터가 `portfolio_config` 밖 하드코딩이고 실행 사이클도 orchestrator 사이클 (30~60초) 에 묶여 있음. Phase A 는 이를 **파라미터화 (config 컬럼) + 별도 10초 잡** 으로 정착화.

### 원칙 2. 한국 시장 4대 제약

모든 룰 설계 시 다음을 인지: **T+2 결제**, **1주 단위 거래**, **상하한 30%**, **거래시간 09:00~15:30 KST**. 룰이 이 제약을 위반하면 폐기.

### 원칙 3. 3-layer audit tracing

모든 매도 결정은 **trigger event · pre-trade risk check · post-trade audit** 3층에서 재현 가능해야 한다. `broker_orders.trigger_source` + `trigger_snapshot` 두 컬럼이 이 원칙의 표현.

### 원칙 4. avg_fill_price 기준 계산

손절/익절 계산은 반드시 `avg_fill_price` (`broker_orders.avg_fill_price`) 기준. `requested_price` 기준은 시장가 슬리피지가 실제 손절선을 왜곡한다.

**기존 코드 갭**: `_check_rule_based_exits` 는 지금 `portfolio_positions.avg_price` (부분 매수 wavg) 사용. `broker_orders.avg_fill_price` 와 다를 수 있음. Phase A 구현 시 `avg_fill_price` 기반 조회로 통일 필요 (§8 open questions).

### 원칙 5. 파라미터 튜닝은 데이터가 결정한다

Phase A~C 각 dry-run 30일 관측 후 실 활성. 3개월 후 데이터로 파라미터 재조정 (§7 승산 게이트).

### 원칙 6. 기존 코드 재사용 최우선 (revision 추가)

이미 `_check_rule_based_exits`, `_is_daily_loss_blocked`, `portfolio_config`, `DistributedLock`, `trading_mode.py` 다 존재. **신규 파일 없이 확장이 mandate 정합** (감사 축 유지 + 기존 유지 anti-pattern 회피). 신규 서비스 파일 도입 시:
- 매도 발주 경로 이중화 → 우선순위 충돌
- 같은 로직 두 곳 유지 → 감사 흔적 분산
- 파라미터 두 곳 정의 → 조회/변경 실수

원칙: **잡 등록 + method 확장 + 컬럼 추가만 허용**. 신규 파일은 순수 계산 helper 정도 (optional, test 편의 목적).

---

## 3. Phase A — Hard Stop-Loss

### 3-1. 3-Layer 스코프

| Layer | Trigger | Action | 기존/신규 |
|---|---|---|---|
| **1** | 개별 종목 현재가 ≤ `avg_fill_price × (1 - individual_stop_loss_pct/100)` (**mandate -7%**) | 해당 포지션 시장가 전량 매도 | **기존 확장** — `_check_rule_based_exits` 의 `stop_loss_pct=-3.0` 하드코딩을 `portfolio_config.individual_stop_loss_pct` 소비로 변경하고 값 -7 로 완화 |
| **2** | 포트 realized+unrealized drawdown ≤ `-portfolio_drawdown_limit_pct` (**mandate -8%**, 전주 종가 대비) | 신규 매수 정지 + unrealized 최약체 2 종목 시장가 매도 | **신규 method** `_check_portfolio_drawdown` (aggregate_risk 는 exposure ≠ dd 라 재사용 불가) |
| **3** | 당일 realized 손실 ≤ `-daily_loss_limit_pct` (**mandate -3%**, 전일 종가 대비) | 그날 모든 신규 주문 취소 + 다음 거래일까지 매매 lockout | **기존 유지** — `_is_daily_loss_blocked` 이미 동작. Lockout 강화는 §8 별도 open question. |

**Layer 우선순위**: Layer 3 > Layer 1 > Layer 2. Layer 3 lockout 이 동시 발동 시 다른 매도도 정지.

### 3-1-1. Layer 1 파라미터 완화 근거 (-3% → -7%)

지금 `_check_rule_based_exits` 의 `stop_loss_pct=-3.0` 하드코딩은 시스템 초기 안전 default. Mandate 재해석 상 -7% 가 정합:

- **Kim (§A)**: "-3% 는 프롬프트 가이드 수준. -7% = 대형주 daily σ 의 2.5배 = 노이즈 아닌 트렌드."
- **Mandate §1-1 상충 해결**: "자본 보존 최우선" 은 hard stop 존재 자체로 확보. Tight 완화 (-3% → -7%) 로 단타 승률 확보 (normal noise 에서의 매도 튐 방지).
- **사후 검증 (dry-run 30일)**: 오탐률 30% 초과 시 -10% 등으로 재조정 (§3-4).

### 3-2. 아키텍처

**신규 서비스 파일: 없음.** 순수 계산 helper 는 optional (test 편의).

**변경 지점** (모두 기존 파일 확장):

| 파일 | 변화 |
|---|---|
| `src/schedulers/unified_scheduler.py` | `hard_stop_check` 잡 신규 등록 (10 초 cron, 09:00~15:30 KST). 잡 레벨 `DistributedLock` 자동 적용. |
| `src/agents/portfolio_manager.py` | ① `_hard_stop_scan(cfg, scope)` 신규 method (잡 entry) — Layer 3 → 1 → 2 순 판정 후 SELL signal 발주 파이프라인 위임<br>② `_check_rule_based_exits` 확장 — `portfolio_config` 파라미터 소비, exit signal 에 `trigger_source` / `trigger_snapshot` attach<br>③ `_check_portfolio_drawdown(cfg, scope)` 신규 method (Layer 2)<br>④ `_is_daily_loss_blocked` 그대로 재사용 (Layer 3) |
| `src/db/models.py` | `PredictionSignal` 에 `trigger_source: Optional[str]`, `trigger_snapshot: Optional[dict]` field 추가 (nullable) |
| `src/brokers/{kis,paper,virtual_broker}.py` | `execute_order` 안 `broker_orders` INSERT 시 signal 의 trigger 필드를 컬럼에 반영. Signal 인터페이스는 유지, order 객체에 필드 전파. |
| `src/services/trading_mode.py` (또는 새 얇은 helper) | `is_hard_stop_dry_run() -> bool` — Redis key `system:hard_stop_dry_run` + env `HARD_STOP_LOSS_DRY_RUN` fallback. **Default true.** |

**잡 흐름**:

```
hard_stop_check (cron 10s, 09:00~15:30 KST)
  ↓ (unified_scheduler 자동 scheduler:lock:hard_stop_check DistributedLock)
PortfolioManagerAgent._hard_stop_scan(cfg, scope)
  ↓
  [Layer 3] await self._is_daily_loss_blocked(scope, cfg)     ← 기존 재사용
      lockout 상태면 return early (모든 신규 매도도 정지)
  [Layer 1] await self._check_rule_based_exits(scope, cfg)    ← 기존 확장
      config 소비, exit signal 생성 (trigger_source='hard_stop_L1', snapshot attach)
  [Layer 2] await self._check_portfolio_drawdown(scope, cfg)  ← 신규
      dd 계산 → 최약체 2 종목 exit signal 생성 (trigger_source='hard_stop_L2')
  ↓
  for signal in exit_signals:
      async with DistributedLock(redis, f"hard_stop:{signal.ticker}", ttl=25, raise_on_fail=False) as lock:
          if not lock.acquired:
              continue  # 이전 사이클 or 다른 잡이 이미 처리 중
          if await is_hard_stop_dry_run():
              await log_dry_run_and_notify(signal)  # broker 발주 skip
              continue
          await self.process_signal(signal, ...)  ← 기존 파이프라인
              ↓
          broker.execute_order(order)  ← 기존 확장 (trigger 필드 반영)
              ↓
          broker_orders INSERT (trigger_source, trigger_snapshot, ...)
```

**동시성 제어**:
- **잡 레벨**: `scheduler:lock:hard_stop_check` (`unified_scheduler` 자동, 기존)
- **종목별**: `hard_stop:{ticker}` TTL 25 s (Phase A 신규 — 매도 발주 전 얇게)
- **주문 중복**: `broker_orders.client_order_id UNIQUE` (기존 스키마)

**Pre-trade check**:
- KRX 거래시간: `market_session_status()` 이미 있음. 잡 자체 cron 이 09:00~15:30 이지만 방어적 재확인.
- 거래정지/정리매매: `_resolve_name_and_price` 안 부분 처리. KIS API 확장 필요 시 별도 (open question).
- 상하한가 지정가 fallback: broker 확장 필요 (open question).
- 실패 시 `NotifierAgent` 크리티컬 알림 (원칙 5 위반 회피 — safer to hold).

**Client order ID** (선택):
- 기존 broker UUID 생성. Hard stop 발주 시 `HSL_{ticker}_{yyyymmdd_hhmmss}` prefix override 가능 (감사 시 구분). Phase A 필수 아님, 선택 도입.

### 3-3. 데이터 스키마

#### 3-3-1. `broker_orders` — 감사 컬럼 2 개 추가

```sql
ALTER TABLE broker_orders
    ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) NULL;
ALTER TABLE broker_orders
    ADD COLUMN IF NOT EXISTS trigger_snapshot JSONB NULL;

COMMENT ON COLUMN broker_orders.trigger_source IS
    'Sell strategy phase A~D trigger origin: llm_signal | hard_stop_L1 | hard_stop_L2 | take_profit | time_exit | rebalance';
COMMENT ON COLUMN broker_orders.trigger_snapshot IS
    'JSONB — layer/pricing/state at trigger time. Audit reproducibility.';
```

**`signal_source` (기존) 와 `trigger_source` (신규) 의 관계**:
- `signal_source` (A/B/BLEND/RL/S/L/EXIT/VIRTUAL) = **누가 냈나** (전략 or EXIT rule)
- `trigger_source` = **왜 매도가 나갔나 세부 원인** (LLM signal 인지 hard stop L1 인지)
- Hard stop 발주 시 두 축 병기 예: `signal_source='EXIT'`, `trigger_source='hard_stop_L1'`

**`trigger_snapshot` 예시**:
```json
{
  "layer": 1,
  "avg_fill_price": 68500,
  "current_price": 63700,
  "stop_line_pct": -7,
  "stop_line_price": 63705,
  "portfolio_dd_pct": null,
  "daily_realized_pnl_pct": -1.2,
  "triggered_at": "2026-07-05T10:23:15+09:00",
  "dry_run": false
}
```

#### 3-3-2. `portfolio_config` — 파라미터 컬럼 3 개 추가

```sql
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS individual_stop_loss_pct     INTEGER NOT NULL DEFAULT 7;
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS take_profit_pct              INTEGER NOT NULL DEFAULT 5;
ALTER TABLE portfolio_config
    ADD COLUMN IF NOT EXISTS portfolio_drawdown_limit_pct INTEGER NOT NULL DEFAULT 8;

COMMENT ON COLUMN portfolio_config.individual_stop_loss_pct IS
    'Layer 1 개별 종목 손절 임계 %. _check_rule_based_exits 가 소비. Mandate default 7.';
COMMENT ON COLUMN portfolio_config.take_profit_pct IS
    'Take profit 임계 %. _check_rule_based_exits (Phase A) + Phase B 부분 매도가 소비. Mandate default 5.';
COMMENT ON COLUMN portfolio_config.portfolio_drawdown_limit_pct IS
    'Layer 2 포트폴리오 drawdown 임계 %. _check_portfolio_drawdown 이 소비. Mandate default 8.';
```

- 기존 `daily_loss_limit_pct=3` 유지 (Layer 3 그대로 소비).
- 3 개 컬럼 값의 mandate 근거: §1 감내 손실 표 그대로.

### 3-4. Dry-run 프로토콜

**모드 전환 helper**:
- `is_hard_stop_dry_run() -> bool` (`trading_mode.py` 패턴 그대로 재활용)
- Redis key `system:hard_stop_dry_run` 우선 (즉시 반영, 재기동 불필요)
- env `HARD_STOP_LOSS_DRY_RUN` fallback
- **Default: `True`** (mandate 자본 보존 상 안전 default — 실 매매하려면 명시적으로 꺼야)

**Dry-run 시 동작**:
- Trigger 조건 도달 시 `broker.execute_order` **호출 X**
- `logger.info` + `NotifierAgent.send_hard_stop_dry_run_alert` (Telegram, 사후 관측)
- (선택) `operational_audits` 에 `audit_type='hard_stop_trigger_dryrun'`, `details=<snapshot dict>` 저장 (감사 강화 시)

**관측 지표 (30 일)**:
- Layer 별 trigger 빈도 (Layer 1 하루 평균 몇 회)
- Trigger 시점 vs LLM 이 SELL signal 낸 시점 delta
- Trigger 이후 24 h 반등 여부 (오탐 비율)

**실 활성 게이트**:
- Layer 별 trigger 빈도 안정 (하루 평균 < 5)
- 오탐 30% 미만
- 오탐 30% 초과 시 파라미터 재검토 (개별 -7% → -10% 등)

**해제 절차**:
- Redis: `SET system:hard_stop_dry_run false` (또는 UI/API 토글)
- 관측 지표 리포트 첨부 후 사용자 승인 (자본 보존 mandate 상 사용자 게이트)

### 3-5. 실패 시나리오

| 시나리오 | 대응 |
|---|---|
| KIS API timeout | 기존 broker 3 회 재시도 (지수 backoff), 실패 시 Telegram 크리티컬 알림 |
| Redis lock 획득 실패 | 다음 10 초 사이클 재시도 (raise_on_fail=False, silent skip) |
| 현재가 조회 실패 (Redis+DB 모두) | **매도 안 함** + Telegram 알림 (원칙 5 위반 회피) |
| 매도 후 재트리거 | `broker_orders.status='FILLED'` 확인 후 skip. Position quantity 감소 후 자연 해소. |
| 상하한가 도달 | 상한가 미체결 위험 있으므로 지정가 매도로 fallback (broker 확장, §8 open) |
| Overnight gap down -15% | 아침 09:00 시장가 매도 = 이미 -15% 실현. Phase A 스코프 밖 (§8 open) |
| Hard stop 잡 크래시 | APScheduler 자동 재기동. `scheduler:lock:hard_stop_check` TTL 이내 재획득. |

### 3-6. 파일 변경 목록 (revision 반영)

| 상태 | 파일 | 변화 |
|---|---|---|
| 확장 | `src/schedulers/unified_scheduler.py` | `hard_stop_check` 잡 등록 (cron 10 s, 09:00~15:30 KST) |
| 확장 | `src/agents/portfolio_manager.py` | `_hard_stop_scan`, `_check_portfolio_drawdown` 신규 method + `_check_rule_based_exits` 파라미터화 |
| 확장 | `src/db/models.py` | `PredictionSignal` 에 `trigger_source`, `trigger_snapshot` field |
| 확장 | `src/brokers/kis.py` · `paper.py` · `virtual_broker.py` | `execute_order` 안 `broker_orders` INSERT 확장 (trigger 필드) |
| 확장 | `src/services/trading_mode.py` (또는 신규 얇은 helper) | `is_hard_stop_dry_run()` |
| 신규 (선택) | `src/utils/hard_stop_calc.py` | Layer 1/2 순수 판정 helper (test 편의, 없어도 됨) |
| 신규 | `test/test_hard_stop_loss.py` | Layer 1/2/3 판정 + lock + dry-run + broker 발주 흐름 test |
| 신규 | `scripts/db/migrate_add_broker_orders_trigger_fields.py` | `broker_orders` 컬럼 마이그 (idempotent) |
| 신규 | `scripts/db/migrate_add_portfolio_config_stop_loss_fields.py` | `portfolio_config` 3 컬럼 마이그 (idempotent) |
| 수정 | `scripts/db/init_db.py` | 두 테이블 확장 반영 (fresh install) |
| 수정 | `docs/db/pg_broker_orders.md` | 새 컬럼 문서화 |
| 수정 | `docs/db/pg_portfolio_config.md` | 새 컬럼 문서화 |

**신규 서비스 파일: 없음.** 초안의 `src/services/hard_stop_loss.py` 는 폐기 (원칙 6 상 신규 파일 요구 근거 소멸).

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
- 최소 매도 단위 1 주라 예: 10 주 × 50% = 5 주, 11 주 × 50% = 5 주

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

**잡**: `partial_exit_check` (Phase A 와 동일 파일 · 동일 패턴)
- Interval: **10 초** (hard stop 과 동일 사이클, 그러나 별개 잡)
- Redis lock: `partial_exit:{ticker}:{entry_order_id}` TTL 25 s
- 하드 손절과의 우선순위: **Hard stop 우선**. 동시 트리거 시 hard stop 만 실행.
- `PortfolioManagerAgent._partial_exit_scan(cfg, scope)` — Phase A 패턴 그대로 (신규 파일 X)

### 4-5. Dry-run 프로토콜

Phase A 30 일 관측 완료 후 착수. Phase B 도 30 일 dry-run 후 실 활성.

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
- 오늘 기준 D+3 = 다음 3 번째 거래일

### 5-2. 아키텍처

**잡**: `time_based_exit_check`
- Cron: **매일 15:20 KST** (장 마감 10 분 전, 유동성 안정)
- 위치: `src/schedulers/unified_scheduler.py`
- `PortfolioManagerAgent._time_exit_scan(cfg, scope)` — Phase A/B 패턴 그대로

**Pre-trade check**:
- 상하한가 도달 여부 (상한가면 지정가로, 하한가면 hard stop 이 이미 처리)
- 거래정지 시 시장가 매도 불가 → 다음 거래일까지 defer + Telegram 알림

**주문 타입**:
- 15:20 → 시장가 (10 분 안에 체결)
- 실패 시 15:25 지정가 (현재가 -1 tick) 재시도

### 5-3. 데이터 스키마

Phase B 의 `position_state.entered_at` 사용. 추가 컬럼 불필요.

### 5-4. Dry-run 프로토콜

Phase B 완료 후 착수. 30 일 dry-run.

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

Phase A~C 실 활성화 후 **3 개월 관측** → 다음 게이트 **모두 통과** 시 real 전환 (초기 10-20만원):

| 지표 | 목표 | 근거 |
|---|---|---|
| **Sharpe ratio** | > 0.8 | 개인 단타 시장에서 실질적 알파의 하한 |
| **Win rate** | > 55% | 단타 승률 시장 통계 45~50% 대비 유의 |
| **Max drawdown** | < 10% | 감내 -8% 상에서 -10% 넘으면 시스템 재검토 |
| **월간 승률** | 12 개월 중 5 개월 이상 + | 계절성 편향 회피 |
| **Hard stop 빈도** | 하루 평균 < 5 회 | 파라미터 안정성 (튜닝 초과 방지) |
| **Time exit 기대값** | 청산 시 손실 < 익절 시 이익 (양수) | 시간 기반 청산이 알파 훼손 안 함 |

**한 개라도 미달 시**:
- Mandate 재검토 (예: `max_holding_days` 3 → 5)
- 재검증 3 개월

---

## 8. Open Questions (향후 결정)

우선순위 순.

1. **Real 전환 시 초기 자본 (10-20만원) 소진 시**: 자본 증액 방식 (수익 재투자 vs 외부 seed)? 감내 손실 재조정 방식?
2. **Phase A Layer 2 최약체 정의**: unrealized pnl 하위 vs Sharpe 하위 vs 매수 오래된 순? — 초기 default 는 unrealized pnl 하위.
3. **Phase B Level 1 트리거 (+3%)**: 시장 조건 (변동성) 반영해 동적 조정? 예: KOSPI VIX 유사 지표 상 상승 시 +5% 로.
4. **Real 계좌 잔고 조회**: 지금 UI 의 실계좌 응답이 flat shape 이라 아직 미완. Phase A 는 paper 대상이라 선행 필요 없지만 real 전환 전 해결 필요 (`docs/REAL_TRADING_GUIDE.md`).
5. **하드 손절 vs 시장 gap**: 밤 사이 -15% gap down 시 hard stop 은 아침 09:00 시장가 매도 = 이미 -15% 실현. 이 상황 방어 룰 (선매도 조건 등)?
6. **KIS API rate limit**: Hard stop 10 초 interval + 여러 종목 동시 트리거 시 rate limit 초과 위험. 우선순위 큐 필요?
7. **`avg_price` vs `avg_fill_price` 통일** (revision 추가): 지금 `_check_rule_based_exits` 는 `portfolio_positions.avg_price` (부분 매수 wavg) 사용. 원칙 4 는 `broker_orders.avg_fill_price` 요구. Phase A 구현 시 어느 소스가 옳은지 확정 (`avg_fill_price` 우세, 다만 부분 매수 시 wavg 재계산 로직 필요).
8. **Layer 3 lockout 강화** (revision 추가): 현재 `_is_daily_loss_blocked` 는 매 사이클 당일 pnl 만 체크 = 자정 지나면 자동 해제. "다음 거래일까지 lockout" 은 별도 flag (Redis with expiry, 다음 거래일 09:00 auto-clear) 필요. Phase A 스코프 밖 → 별도 세션.
9. **HSL_ client order ID prefix** (revision 추가): KIS 감사 시 hard stop 구분 용도. 필수 아니며 선택 도입 (broker 확장 시 함께).

---

## 9. Immediate Next Step (Phase A 착수)

### 착수 순서 (revision 반영)

1. ✅ **PR #233** — SELL_STRATEGY_PHASES.md 초안 (완료)
2. **PR-A (본 revision)** — 기존 코드 실체 반영, 신규 파일 요구 삭제, 파라미터 완화 (-3% → -7%), portfolio_config 파라미터 확장 추가, hybrid 확장 방식 확정.
3. **PR-B (스키마)** — `portfolio_config` 3 컬럼 + `broker_orders` 2 컬럼 마이그 + init_db.py + docs/db/ 갱신.
4. **PR-C (로직)** — `_hard_stop_scan`, `_check_portfolio_drawdown`, `_check_rule_based_exits` 확장, `hard_stop_check` 잡 등록, broker 확장, `is_hard_stop_dry_run` helper, tests.
5. Deploy → 30 일 dry-run 관측 (`system:hard_stop_dry_run=true` default).
6. 실 활성화 결정 (관측 지표 통과 시 사용자 승인 게이트).

### 착수 시점 결정 필요 지점

- Real 계좌 잔고 조회 이슈 (§8-4) — Phase A 는 paper 계좌 대상이라 선진행 가능.
- 30 일 dry-run 시 실 매매 발생 안 함 → paper 계좌에도 영향 없음.
- **선행 필요 없음. 지금 착수 가능.**

---

## Appendix — Kim / Yoon 세션 인용 (설계 근거)

### A. 하드 손절 -7% 근거

> "-3% 는 프롬프트 가이드일 뿐 하드 아님. -7% = 일반적으로 대형주 daily σ 의 2.5배, 노이즈 아닌 트렌드." — Kim

### B. avg_fill_price 기준 계산

> "Yoon, 이거 반드시 `avg_fill_price` 기준으로 계산해. `requested_price` 아니야. 시장가 주문의 슬리피지가 곧 실제 손절 지점을 왜곡한다." — Kim

### C. 완전 자동 + 감사 우선 조합의 이상성

> "감사 최우선 + 소액 자본 + 3 개월 검증 목적 = 완벽한 상황. 감사 로그 상세하게 남기는 오버헤드가 소액이라 성능 임팩트 미미. 3 개월 후 데이터로 파라미터 재조정 = 우리가 Phase E 에서 예정한 튜닝 사이클과 정확히 맞음." — Yoon

### D. 단타 mandate 의 리밸런싱 관계

> "단타 mandate 하에서 monthly rebalancing 은 의미 없음. 매일 clear = 매일 자동 리밸런스. Phase D 는 mandate 상 스킵." — Kim

### E. Trailing stop 미도입 근거

> "3-level scaling out 하나만 우선. Trailing stop 로직은 별도 세션 필요. 심리 안전망은 Level 1 하나만 있어도 절반은 잡음." — Kim

### F. Revision 결정 근거 (2026-07-04)

> "SELL_STRATEGY_PHASES v1 초안이 시스템의 `_check_rule_based_exits` 존재를 놓쳐 신규 파일 요구했었음. Alpha 코드베이스 조사 결과 Layer 3 은 `_is_daily_loss_blocked` 이미 있고, Layer 1 은 `_check_rule_based_exits` 확장이 가능함. `DistributedLock`, `trading_mode.py` 등 인프라도 완비. Phase A 는 신규 서비스 파일 없이 기존 코드 확장으로 mandate 정합. 파라미터 -3% 는 시스템 초기 default, mandate -7% 로 완화하되 dry-run 30 일 사후 검증." — 본 revision 결정

---

## 문서 이력

- 2026-07-02: 초안. Mandate 확정 (§1). Phase A~D 스코프 확정.
- 2026-07-04: revision.
  - §0 재작성 (`_check_rule_based_exits`, `_is_daily_loss_blocked`, `portfolio_config`, `DistributedLock`, `trading_mode.py` 존재 반영)
  - §2 원칙 6 추가 (기존 코드 재사용 최우선)
  - §3-1 Layer 표 재작성 (기존/신규 구분)
  - §3-1-1 Layer 1 파라미터 -3% → -7% 완화 근거
  - §3-2 아키텍처 완전 재작성 (신규 서비스 파일 요구 삭제, 기존 파일 확장 방식)
  - §3-3 `portfolio_config` 3 컬럼 추가 (individual_stop_loss_pct, take_profit_pct, portfolio_drawdown_limit_pct)
  - §3-4 dry-run `trading_mode.py` 패턴 재활용 명시
  - §3-6 파일 변경 목록 재작성 (신규 서비스 파일 0)
  - §8 open questions #7-9 추가 (avg_price/avg_fill_price 통일, Layer 3 lockout 강화, HSL_ client order id)
  - §9 PR 순서 A/B/C 로 재편
  - Appendix F 추가 (revision 결정 근거)
