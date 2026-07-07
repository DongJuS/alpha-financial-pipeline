# RL 정책 학습 곡선 시각화 — 3인 5라운드 토론

status: open
created_at: 2026-07-07
topic_slug: rl-training-visualization-roundtable
related_files:
- artifacts/rl/models/registry.json
- src/agents/rl_trading.py
- src/agents/rl_dreamer.py
- src/agents/rl_walk_forward.py
- src/agents/rl_policy_store_v2.py
- src/api/routers/rl.py
- ui/web/package.json
- scripts/rl_bootstrap.py

## 1. 핵심 질문

RL 학습 결과(정책별 시간축 수익률 궤적)를 트레이더가 30초 안에 "어느 알고리즘/종목 조합이 매매 후보인지" 판단할 수 있게 시각화하려면, **어떤 데이터를 저장하고 · 어떤 API/UI 구조로 노출하며 · 어디까지를 V0 스코프로 정할 것인가?**

## 2. 배경

현재 상태:
- `artifacts/rl/models/registry.json` 에는 **최종 metric만** 저장 (`return_pct`, `max_drawdown_pct`, `win_rate`, `trades`, `approved`). 시간축 궤적 없음.
- Walk-forward 학습(`rl_walk_forward.py`)이 fold 별로 성능을 뽑지만, 폴드별 equity curve는 dispose 되고 요약 metric만 남김.
- `src/api/routers/rl.py` 는 정책 목록/승격 조작만 노출. 성능 곡선 엔드포인트 없음.
- 웹 UI (`ui/web`) 에는 `recharts@^2.12.2` 가 이미 dependency 로 있음 (다른 화면에서 사용 중). 별도 라이브러리 도입 불필요.
- 트레이더(사용자 본인)가 "종목별 승률/수익성 파악" + "알고리즘 대비 비교" 를 원한다는 요구가 명확 (2026-07-07 대화).

이 논의가 왜 필요한가:
- Excel 리포트만으로는 시계열 진화 · MDD 밴드 · baseline 대비 궤적을 한 눈에 못 봄.
- 알고리즘이 여러 개 도입될 때 (Dreamer, DQN, PPO, tabular Q) 비교 프레임이 지금부터 있어야 축적됨.
- 승격 게이트 판단(수익률 ≥ 5%, MDD ≥ -15%)의 근거를 시각적으로 재현 가능해야 감사(audit) 정책과 정합.

---

## 3. 제약 조건

- **감사 우선 정책** (`docs/interests/projects/alpha-financial-pipeline.md` §1): 시각화 데이터도 재현 가능해야 함. UI 값과 DB/artifact 값이 반드시 일치.
- **UX 대상 = 본인 (전문)**: 대중 친화보다 정보 밀도 우선. 트레이더 익숙 뷰(equity curve, drawdown band) 그대로.
- **단일 노드 k3s, GPU 없음**: 시계열 계산은 학습 시 pre-compute 하고 UI 조회는 read-only. 실시간 계산 금지.
- **월 운영비 5,000~10,000원 목표**: 새 저장소 도입 금지 (Postgres 안에서 해결). 컬럼 추가는 허용.
- **과도한 설계 금지**: 20종목 × 몇 개 알고리즘 규모. 대규모 timeseries DB (TimescaleDB, InfluxDB) 도입 불필요.

---

## 4. 3인 5라운드 토론

**참여자**:
- 🧭 **매니저** (Product/Engineering Manager) — 스코프/우선순위/사용자 가치 판단
- 📊 **금융 트레이드 전문가** (Quant/Trader) — 트레이더 실사용 관점, 리스크/성과 지표
- 🔧 **Backend 엔지니어** (Systems Engineer) — 스키마/API/성능/유지보수 관점

---

### Round 1 — 문제 정의와 목표 정렬

**🧭 매니저**: 사용자가 요청한 건 "x=시간, y=수익률, label=종목, 알고리즘 별로 그래프". 이걸 그대로 구현하면 순진한 line chart 하나로 끝나는데, 그게 진짜 목표인가? 우리가 답할 실제 질문은 "**이 알고리즘/종목 조합이 매매 가능한가?**" 아닌가.

**📊 금융**: 정확히 그거다. 트레이더가 궤적 하나 보고 판단할 때 실제로 눈에 담는 건 세 가지 — (a) 누적 수익률이 우상향인가, (b) drawdown 크기와 회복 시간이 견딜만한가, (c) baseline(buy-and-hold) 대비 초과수익이 있나. **baseline overlay 없는 equity curve 는 "수익률"이 아니라 "그냥 시장 랠리"를 보고 있는 셈**이다. 무조건 넣어야 한다.

**🔧 Backend**: 문제는 그 데이터가 지금 없다는 것. `registry.json` 에는 정책마다 최종 스칼라 하나(`return_pct`) 만 있고 궤적 없다. 궤적을 만들려면 학습 파이프라인이 walk-forward evaluation 시 스텝별 portfolio value 와 baseline value 를 **저장하도록 스키마부터 확장**해야 한다. 지금 저장 안 하면 그래프 만들 원본이 없다.

**결론 (Round 1)**:
- 목표는 "정책의 매매 가능성 판단"이지 "차트 예쁘게 그리기"가 아님.
- 필수 궤적 3종: **portfolio_value / baseline_value / drawdown_pct** (모두 step 축).
- V0 진입 조건 = 학습 파이프라인에서 궤적을 실제로 저장하는 스키마 변경이 선행되어야 함.

---

### Round 2 — 사용자 시나리오와 시각화 요구

**📊 금융**: 트레이더가 실제로 하는 워크플로우는:
1. **훑기(scan)**: 알고리즘 하나 골라 20종목 승률/수익률 히트맵 → 후보 3-5개 좁힘.
2. **판독(read)**: 후보 각각의 equity curve + drawdown band 확인 → 매매 가능 정책 결정.
3. **비교(compare)**: 같은 종목에서 알고리즘 A vs B → 어느 정책을 활성화할지 결정.

이 셋이 다 필요하다. 근데 V0에 세 개 다 넣으면 스코프 폭발.

**🧭 매니저**: 우선순위 매기자. (2) 판독이 사용자가 요청한 것 자체이고 승격 판단에 직접 근거가 됨 → **V0**. (1) 훑기는 후보 좁히기 용도로 유용하지만 표 뷰만 있어도 대체 가능 → **V1**. (3) 비교는 알고리즘이 2개 이상 approved 되어야 의미 있음 → 지금은 아직 dreamer 만 실험 중이니 **V1 이후**.

**🔧 Backend**: V0 판독 뷰만 하면 API 는 하나로 충분 (`GET /rl/policies/{policy_id}/equity_curve`). V1 훑기는 이미 있는 `GET /rl/policies` 를 필터 확장하면 됨. V1.5 비교는 클라이언트에서 여러 curve 를 겹쳐 그리는 걸로 API 재사용 가능. **각 단계가 이전 API 를 확장하는 구조라 재작업 없다** — V0 부터 이 방향으로 잡자.

**결론 (Round 2)**:
- V0 = **판독 뷰** (정책 하나의 equity + baseline + drawdown 궤적).
- V1 = 훑기(히트맵/표), V1.5 = 비교(overlay).
- API 는 V0 부터 확장 가능한 형태로 설계 (재작업 방지).

---

### Round 3 — 데이터 모델과 저장 스키마

**🔧 Backend**: 스키마 옵션 두 개.

| 옵션 | 저장 위치 | 장점 | 단점 |
|---|---|---|---|
| A | Postgres 신규 테이블 `rl_policy_equity_curves(policy_id, step_idx, ts, portfolio_value, baseline_value, drawdown_pct)` | SQL 필터/조인 편함. Grafana 등 재사용 가능. 파티션(연도별) 가능. | 마이그레이션 필요. write 부하 (정책당 수백 row). |
| B | `artifacts/rl/models/<algo>/<ticker>/<policy_id>_curve.parquet` | 파일 시스템에 격리. DB 부하 0. 큰 사이즈에 강함. | UI 조회 시 파일 로드/파싱 필요. read 지연. filter 어려움. |

**📊 금융**: DB 안에 있는 게 훨씬 편하다. drawdown 임계 조회 (`WHERE drawdown_pct < -15`) 같은 걸 SQL로 바로 짤 수 있고, 리포트/알림 확장할 때 재사용 폭이 크다. **감사 정책상 재현 가능성 관점에서도 DB 가 우위** — 파일은 삭제/누락 실수 여지가 있다.

**🔧 Backend**: 동의. 20종목 × 3-5 알고리즘 × 720스텝 ≈ 4만 row/사이클. 전혀 부담 없음. Postgres 로 간다. 스키마:

```sql
CREATE TABLE rl_policy_equity_curves (
    policy_id       TEXT        NOT NULL,
    step_idx        INTEGER     NOT NULL,
    ts              TIMESTAMPTZ,           -- 원본 시장 데이터 timestamp (nullable, tabular 는 스텝만)
    portfolio_value NUMERIC(18,6) NOT NULL,
    baseline_value  NUMERIC(18,6) NOT NULL,
    drawdown_pct    NUMERIC(10,4) NOT NULL,
    PRIMARY KEY (policy_id, step_idx)
);
CREATE INDEX rl_policy_equity_curves_policy_idx ON rl_policy_equity_curves(policy_id);
```

**🧭 매니저**: 재학습 없이 기존 정책 궤적을 볼 수 없는 문제. 백필(backfill) 스크립트 있어야 한다. 없으면 사용자가 "왜 예전 정책은 그래프가 안 나오냐"고 물을 것.

**🔧 Backend**: 백필은 어려움. 궤적은 학습 시 evaluate 스텝을 재현해야 나오는데, 학습 결과가 seed/데이터 스냅샷에 의존적이라 정확 재현 못 함. **정직한 처리 = 기존 정책은 "궤적 없음" 뱃지로 UI 에 표시**. 재학습 시 자동으로 채워짐. 명시적으로 밀고 나가자.

**결론 (Round 3)**:
- **옵션 A (Postgres 신규 테이블)** 채택. 감사 정합성 + SQL 활용도.
- 백필은 시도하지 않음. 기존 정책은 "궤적 없음"을 UI 에서 명시. 재학습 시부터 자동 채움.
- 스키마 마이그레이션: `scripts/db/migrate_rl_policy_equity_curves.py` 신설.

---

### Round 4 — API와 UI 아키텍처

**🔧 Backend**: API 는 다음 3개면 충분:

```
GET  /api/v1/rl/policies?algorithm=dreamer_v3&ticker=005930&approved=true
     → 정책 리스트 + 요약 metric (기존 확장)

GET  /api/v1/rl/policies/{policy_id}/equity_curve
     → { steps: [...], portfolio: [...], baseline: [...], drawdown_pct: [...] }
     → Redis 5분 캐시 (policy_id 는 immutable, 캐시 안전)

GET  /api/v1/rl/algorithms/{algorithm}/summary
     → 종목별 approved 정책 요약 (V1 히트맵용, V0 은 정의만)
```

**📊 금융**: `equity_curve` 응답에 지표 몇 개 미리 계산해서 넣자 — Sharpe 유사값, MDD 최고점 시점, baseline 대비 excess return 시계열. 클라이언트가 재계산 안 하도록. **UI 는 답을 렌더링하는 곳이지 계산하는 곳이 아니다**.

**🔧 Backend**: 좋다. 응답 스키마에 `metrics_derived` 필드 추가:

```json
{
  "policy_id": "rl_005930_20260707T...",
  "steps": [...],
  "portfolio_value": [...],
  "baseline_value": [...],
  "drawdown_pct": [...],
  "metrics_derived": {
    "sharpe_like": 0.87,
    "mdd_step_idx": 342,
    "excess_return_pct": [...],
    "recovery_bars_after_mdd": 47
  }
}
```

**🧭 매니저**: UI 화면. React 새 페이지 `RLPolicyDetail.tsx` 하나 + 서브컴포넌트:

```
/ui/web/src/pages/rl/
├── RLPolicyList.tsx       # /rl/policies — 목록 (알고리즘 tab + 필터)
├── RLPolicyDetail.tsx     # /rl/policies/:policyId — 판독 뷰 (V0 스코프)
└── components/
    ├── EquityCurveChart.tsx     # recharts LineChart, portfolio + baseline overlay
    ├── DrawdownBandChart.tsx    # recharts AreaChart, 붉은 밴드
    └── PolicyMetricsPanel.tsx   # 우측 metric 요약 (Sharpe, MDD, trades 등)
```

**📊 금융**: 차트 요구사항 확정 — 색: portfolio = **파랑**, baseline = **회색 점선**, drawdown = **적색 반투명 area**. 축: x = step_idx (label 은 `ts` 로 매핑), y_left = value (log 스케일 옵션), y_right = drawdown %. 이 세팅이 표준 트레이더 뷰다.

**🔧 Backend**: recharts 이미 있으니 새 dep 없음. React Query 로 캐싱, 라우팅은 이미 프로젝트에 있는 react-router-dom 사용.

**결론 (Round 4)**:
- API 3종 (list / equity_curve / summary), V0 는 앞 2개 구현. `metrics_derived` 서버에서 pre-compute.
- UI: `RLPolicyDetail` 페이지 + 3 하위 컴포넌트. recharts 재사용.
- 차트 스펙 표준화 (색/축) — 트레이더 익숙 뷰.

---

### Round 5 — 실행 계획, 리스크, 성공 지표

**🧭 매니저**: V0 마일스톤 3개:

| M | 내용 | 산출물 | 검증 |
|---|---|---|---|
| M1 | Postgres 스키마 + rl_bootstrap 저장 로직 | 마이그레이션 스크립트, `rl_walk_forward.py` 확장 (평가 시 curve 저장) | 신규 학습 1건 실행 후 `SELECT COUNT(*) FROM rl_policy_equity_curves WHERE policy_id=...` > 0 |
| M2 | FastAPI 라우터 + `metrics_derived` | `src/api/routers/rl.py` 확장, unit test | `GET /rl/policies/{id}/equity_curve` 응답 스키마 정합, 5분 캐시 hit 확인 |
| M3 | React 페이지 + 3 컴포넌트 | `ui/web/src/pages/rl/*` | 브라우저에서 policy_id 선택 → 궤적 렌더, baseline overlay 확인 |

**🔧 Backend**: 리스크 두 개.

1. **`rl_walk_forward.py` 가 tabular Q / SB3 / Dreamer 각각 다른 evaluate 인터페이스** — 통일된 hook 필요. 이 부분 수정 범위가 커질 수 있음.
2. **테이블 크기 무한 증가** — 정책이 삭제(soft delete) 되어도 curve 는 남음. 정책 hard-purge 시 cascade 필요.

**📊 금융**: 성공 지표 = "이 UI 만 보고 30초 안에 매매 가능/불가 판정 가능한가". 스스로 dogfooding.
- 3주 후 정책 5개 중 몇 개를 이 뷰만으로 승격/거절 판단했는지 셀 것.

**🧭 매니저**: 3주는 optimistic. **실제 캘린더 4주** 로 잡음 (M1 = 1주, M2 = 1주, M3 = 2주).
사용자가 서버 CPU 로 Dreamer 학습을 방금 시작한 상태 (2026-07-07). Dreamer 학습 결과를 이 V0 로 볼 수 있으려면 M1 이 그 학습 완료 전에 스키마만 준비 되어야 다음 사이클부터 자동 저장.

**🔧 Backend**: 지금 도는 Dreamer 학습은 이 스키마 없이 완료될 것 → 그 결과는 curve 없이 registry 만 채워짐. 그건 감수. M1 완료 후 재학습 or 다음 사이클부터 곡선 저장. **첫 사이클 데이터는 Excel 리포트만으로 판단**.

**결론 (Round 5)**:
- 마일스톤 3개, 캘린더 4주.
- 리스크 완화 = trainer/evaluator 공통 hook (`emit_step_metric()`) 도입으로 알고리즘 3종 흡수.
- 성공 지표 = 3주 후 정책 5개 이상을 이 UI 만으로 승격/거절 판단.
- 지금 도는 Dreamer 결과는 스키마 없이 완료 → 첫 사이클은 Excel 리포트만. M1 이후 사이클부터 자동 저장.

---

### Round 6 — 사용자 이의 제기와 스키마 결정 정정 (2026-07-07 후속)

**사용자 이의 제기**:
> "저장 스키마? 이미 기존에 있는 스키마를 그대로 사용하면 되는 거 아니야? 테이블을 왜 새로 만들어. 어차피 experiments 할 때 저장하는 스키마에 저장하면 상관없는데. 무차별적으로 스키마 만드는 것은 의미가 없어. 기존과 동일한 작업이면 그대로 사용해. 필터를 조정하면 되는 거라서."

**🧭 매니저**: 정당한 지적. Round 3 결정은 조사 부족이었다. 기존 RL DB 마이그레이션 파일 세 개(`migrate_rl_registry.py` / `migrate_rl_targets.py` / `migrate_rl_training.py`) 를 R3 에서 확인하지 않고 "신규 테이블" 로 넘어갔다. 재검토한다.

**🔧 Backend**: 사실 확인. `scripts/db/migrate_rl_training.py` 를 다시 읽어보니 이미 `rl_experiments` 테이블이 존재한다:

```
rl_experiments(
  run_id, job_id, instrument_id, policy_id, profile_id, algorithm,
  return_pct, baseline_return_pct, excess_return_pct, max_drawdown_pct,
  trades, win_rate, holdout_steps,
  walk_forward_passed, walk_forward_consistency,
  approved, deployed, created_at
)
```

즉 **experiments 자체의 스칼라 metric 은 이미 여기 다 있다**. `rl_experiments.approved`, `walk_forward_passed`, `algorithm` 로 필터도 이미 된다. 사용자 말대로 새 테이블 필요 없다. 다만 이 테이블에도 **시계열 컬럼은 없음** — `return_pct` 는 최종값 하나. 그러니 "그대로 사용"은 안 되고, **컬럼 하나 추가**가 필요.

세 옵션:

| 옵션 | 스키마 변경 | 조회 편의성 | 마이그레이션 부담 |
|---|---|---|---|
| A. `rl_experiments.equity_curve_json JSONB NULL` 컬럼 추가 | `ALTER TABLE ADD COLUMN` 하나 | 기존 row 는 NULL, 새 row 는 JSONB 조회 (1회 SELECT) | 최소 |
| B. `rl_experiments` 에 배열 컬럼 3개 (`portfolio_series NUMERIC[]`, `baseline_series NUMERIC[]`, `drawdown_series NUMERIC[]`) | ALTER 3회 | 배열 index 접근 편함 | 최소 |
| C. 자식 테이블 (R3 원안) | `CREATE TABLE` 하나 | 정규화, 조인 필요 | 중간 |

**📊 금융**: 시계열 조회는 항상 "정책 하나" 기준 (판독 뷰). 즉 조인 필요 없음. A 가 조회 로직 가장 단순. 배열보다 JSONB 가 스키마 변경 유연성 있음 (나중에 필드 추가 편함). **필터는 기존 rl_experiments 컬럼 그대로**. 사용자 지적 정확히 반영.

**🧭 매니저**: 트레이드오프. JSONB 는 SQL 로 세부 시계열 필터하기 어려움 (`WHERE curve.drawdown[100] < -15%` 같은 쿼리 어색). 하지만 우리는 그런 필터 요구가 없다 (필터는 정책 단위 스칼라로 하고, 시계열은 UI 렌더링만). A 로 간다.

**🔧 Backend**: 확정. 마이그레이션 = 한 줄:
```sql
ALTER TABLE rl_experiments
  ADD COLUMN equity_curve_json JSONB;
```
GIN index 는 필요 시 나중에 (지금은 read pattern 이 policy_id 로만 조회). 백필 여전히 안 함 — 기존 row 는 NULL, UI 는 "궤적 저장 전" 뱃지.

**결론 (Round 6, R3 정정)**:
- ❌ 신규 테이블 `rl_policy_equity_curves` 폐기.
- ✅ 기존 `rl_experiments` 에 **`equity_curve_json JSONB NULL` 컬럼 하나** 추가.
- 필터는 기존 `rl_experiments` 스칼라 컬럼(algorithm, instrument_id, walk_forward_passed, approved) 그대로 사용.
- API/UI 결정 (R4)/실행 계획 (R5) 은 유효, 하지만 저장/조회 대상 테이블만 변경.
- **정책 정합**: 무차별적 스키마 확장 금지 (사용자 원칙). 컬럼 추가 1건 = 마이그레이션 최소.

---

## 5. 결정 사항

### 5.1 결정

**RL 정책 학습 곡선 시각화 V0 를 R1~R5 합의 + R6 정정대로 구현**한다.

- **스키마 (R6 정정)**: 기존 `rl_experiments` 테이블에 `equity_curve_json JSONB NULL` 컬럼 하나 추가. 신규 테이블 생성하지 않음.
- **저장 시점**: `rl_walk_forward.py` 의 holdout evaluation 스텝. 알고리즘 3종 공통 hook 이 완료 시 JSONB 를 UPDATE.
- **필터**: 기존 `rl_experiments` 스칼라 컬럼(algorithm, instrument_id, walk_forward_passed, approved, created_at) 그대로 사용.
- **API**: `GET /api/v1/rl/policies` 확장, `GET /api/v1/rl/policies/{id}/equity_curve` 신규. Redis 5분 캐시. `metrics_derived` 서버 pre-compute.
- **UI**: `RLPolicyDetail` 페이지 (V0). 파랑 portfolio + 회색 점선 baseline + 적색 drawdown band. recharts 재사용.
- **백필 없음**: 기존 experiments row 는 `equity_curve_json = NULL`, UI 에서 "궤적 저장 전" 뱃지. 재학습 시부터 자동 채움.
- **스코프 격리**: V1(히트맵), V1.5(알고리즘 비교) 는 별도 라운드테이블에서 결정.

3축 평가:
- **확장성**: SQL 기반이라 알림/리포트/외부 툴 재사용 여지 큼. API 는 V1 확장 시 재작업 없음.
- **안전**: 감사 정합 (UI 값 = DB 값). Redis 캐시는 immutable key 라 stale 위험 없음. 궤적 없는 정책은 UI 에서 명시적 처리.
- **관리 수월함**: 신규 dep 0 (recharts 재사용). 스키마 1개 + 라우터 1개 + 페이지 1개. 4주 스코프.

### 5.2 트레이드오프

- **기존 정책 궤적 없음**: 백필 포기. 사용자가 "왜 옛날 건 없나" 문의 예상 → UI 에서 "이 정책은 학습 시점 궤적 저장 전이라 요약 metric 만 표시" 문구 명시.
- **Dreamer 첫 사이클(2026-07-07 진행 중)은 곡선 없음**: 감수. 첫 사이클은 Excel 리포트, 다음 사이클부터 시각화.
- **v0 는 판독 뷰만**: 훑기(히트맵) 는 별도 사이클. 사용자가 요청 시 우선순위 재조정 가능.

---

## 6. 실행 계획

| 순서 | 항목 | 변경 대상 파일 | 완료 기준 |
|------|------|---------------|----------|
| M1.1 | `rl_experiments.equity_curve_json JSONB NULL` 컬럼 추가 마이그레이션 (R6 정정) | `scripts/db/migrate_rl_experiments_equity_curve_column.py` (신규, ALTER TABLE 한 줄) | dev DB 에 컬럼 존재 확인, 기존 row NULL |
| M1.2 | Trainer/Evaluator 공통 curve emit hook | `src/agents/rl_trading.py`, `src/agents/rl_dreamer.py`, `src/agents/rl_walk_forward.py` | 3 알고리즘 모두 학습 완료 시 `rl_experiments.equity_curve_json` UPDATE |
| M1.3 | rl_bootstrap 저장 연동 | `scripts/rl_bootstrap.py` | 새 학습 사이클 1건 실행 시 `SELECT equity_curve_json FROM rl_experiments WHERE run_id=...` non-null |
| M2.1 | `GET /rl/policies` 확장 (algorithm, ticker, approved 필터) | `src/api/routers/rl.py` | 필터별 응답 스키마 unit test 통과 |
| M2.2 | `GET /rl/policies/{id}/equity_curve` 신규 + `metrics_derived` | `src/api/routers/rl.py`, `src/services/rl_curve_metrics.py` (신규) | 응답 스키마 검증 + Redis 캐시 hit 로그 확인 |
| M3.1 | `EquityCurveChart`, `DrawdownBandChart`, `PolicyMetricsPanel` | `ui/web/src/pages/rl/components/*` | Storybook or 개발자 UI 에서 mock 데이터 렌더링 확인 |
| M3.2 | `RLPolicyDetail` 페이지 라우팅 | `ui/web/src/pages/rl/RLPolicyDetail.tsx`, `ui/web/src/App.tsx` | 브라우저에서 실제 policy_id 로 진입 → 3 차트 표시 |
| M3.3 | 궤적 없는 정책 안내 UI | 위 페이지 | "궤적 저장 전 정책" 뱃지 표시 확인 |

---

## 7. 참조

### 7.1 참고 파일

- `artifacts/rl/models/registry.json` — 현재 저장 스키마 (최종 metric only). 신규 테이블은 여기서 커버 안 되는 시계열을 채움.
- `src/agents/rl_walk_forward.py` — walk-forward evaluation 진입점. curve emit hook 이 여기에 붙어야 함.
- `src/agents/rl_dreamer.py:170,651` — device autodetect PR 반영 위치 (다른 트레이너/에바 개편의 참고 패턴).
- `src/api/routers/rl.py` — 라우터 확장 기점.
- `ui/web/package.json:recharts@^2.12.2` — 이미 있는 차트 라이브러리, 재사용.
- `.agent/discussions/20260412-unified-market-data-architecture.md` — 유사한 데이터 레이어 결정 패턴 (Postgres 안 격리 · 파일 안 벌림) 참고.

### 7.2 참고 소스

- `docs/interests/projects/alpha-financial-pipeline.md` §1 (Investment Mandate — 감사 최우선, UX 대상 = 본인 전문) — 시각화 정책 정합 근거.
- `docs/RL_EVALUATION.md` — 승격 게이트 정의. 시각화가 승격 판단 근거로 쓰이려면 여기 지표와 일치해야 함.

### 7.3 영향받는 파일 (R6 정정)

- 신규: `scripts/db/migrate_rl_experiments_equity_curve_column.py` (ALTER TABLE 한 줄)
- 신규: `src/services/rl_curve_metrics.py`
- 신규: `ui/web/src/pages/rl/RLPolicyDetail.tsx`, `.../components/EquityCurveChart.tsx`, `.../DrawdownBandChart.tsx`, `.../PolicyMetricsPanel.tsx`
- 확장: `src/agents/rl_walk_forward.py`, `src/agents/rl_trading.py`, `src/agents/rl_dreamer.py`, `scripts/rl_bootstrap.py`, `src/api/routers/rl.py`, `ui/web/src/App.tsx`
- ~~폐기~~: `scripts/db/migrate_rl_policy_equity_curves.py` (R3 원안, R6 에서 폐기)
