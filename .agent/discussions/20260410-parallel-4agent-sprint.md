status: open
created_at: 2026-04-10
topic_slug: parallel-4agent-sprint
owner: user
related_files:
- src/backtest/signal_source.py
- src/backtest/cli.py
- src/backtest/repository.py
- src/backtest/engine.py
- src/api/main.py
- src/api/routers/
- src/agents/orchestrator.py
- src/agents/notifier.py
- src/utils/redis_client.py
- ui/web/src/

## 1. Question

Step 8a 머지 후, 4에이전트가 병렬로 착수할 태스크 4개의 상세 실행 계획은 무엇인가?

## 2. Background

- Step 8a (PR #124) 머지 완료 — heartbeat Hash 확장, Docker/K8s healthcheck 연동
- 로드맵상 다음: Signal Replay → 대시보드 UI → Orchestrator 모니터링 → Backtest API
- Step 9 Phase 1에서 4에이전트 병렬 작업 선례 있음 (PR #107~110, 3시간→1시간)
- 현재 752 tests passed, Docker 8서비스 healthy

## 3. Constraints

- 4에이전트 간 파일 수정 충돌 금지 (독립 디렉터리/파일에서 작업)
- `.agent/tech_stack.md`에 명시된 패키지만 사용
- 각 에이전트는 작업 완료 후 개별 PR 생성
- 테스트 포함 필수 (단위 + 통합)

## 4. Options

N/A — 팀 토론에서 4개 태스크 합의 완료.

## 5. AI Opinions

N/A — 팀 토론 결과를 기반으로 상세 계획 작성.

## 6. Interim Conclusion

N/A

## 7. Final Decision

4에이전트 병렬 스프린트. 아래 상세 계획대로 동시 착수.

---

# Agent 1 — Step 10 Signal Replay (Strategy A/B 백테스트)

## 목표
predictions 테이블의 과거 시그널을 재생하여 Strategy A/B 백테스트를 완성한다.
RL 백테스트는 이미 동작하므로, 동일 엔진에 ReplaySignalSource 통합 테스트만 추가.

## 현재 상태
- `ReplaySignalSource` 클래스: `src/backtest/signal_source.py:128-139` — **이미 구현됨**
- `_build_replay_signal_source()`: `src/backtest/cli.py:101-117` — **이미 구현됨**
- `fetch_predictions_for_replay()`: `src/backtest/repository.py:103-128` — **이미 구현됨**
- CLI에서 `--strategy A` 또는 `--strategy B` 지정 시 ReplaySignalSource 사용 — **이미 연결됨**
- **부족한 것**: 통합 테스트가 없다. RL 백테스트는 E2E 테스트(test_backtest_engine.py)가 있지만 Replay 경로는 미검증.

## 작업 항목

### 1. Replay 통합 테스트 작성
**파일:** `test/test_backtest_replay.py` (신규)

```python
# 테스트 1: ReplaySignalSource 단위 테스트
# - 시그널 dict → get_signal() 정상 반환
# - 시그널 없는 날짜 → HOLD 반환
# - 빈 dict → 모든 날짜 HOLD

# 테스트 2: ReplaySignalSource + BacktestEngine 통합 테스트
# - fixture CSV (005930 테스트 데이터) + 하드코딩된 시그널 dict
# - engine.run() → BacktestResult 반환 확인
# - trades 수, metrics 범위 검증

# 테스트 3: _build_replay_signal_source() 통합 (DB mock)
# - fetch_predictions_for_replay를 mock → ReplaySignalSource 생성 확인
# - 빈 predictions → 빈 signals dict → HOLD only 확인
```

### 2. Fixture 데이터 준비
**파일:** `test/fixtures/replay_signals.json` (신규)

```json
{
  "ticker": "005930",
  "strategy": "A",
  "signals": {
    "2025-07-01": "BUY",
    "2025-07-15": "SELL",
    "2025-08-01": "BUY",
    "2025-08-20": "SELL"
  }
}
```

기존 `test/fixtures/backtest_005930.csv`의 가격 데이터를 재사용한다.

### 3. CLI 동작 검증 (수동)
```bash
# predictions 데이터가 있으면:
python -m src.backtest run --ticker 005930 --strategy A \
    --train-start 2024-01-01 --train-end 2025-06-30 \
    --test-start 2025-07-01 --test-end 2025-12-31

# predictions 데이터가 없으면 (모두 HOLD → 매매 0건):
# 이 경우는 테스트에서 fixture로 검증
```

## 수정 파일
| 파일 | 작업 | 신규/수정 |
|------|------|----------|
| `test/test_backtest_replay.py` | 통합 테스트 3개 | 신규 |
| `test/fixtures/replay_signals.json` | 테스트 fixture | 신규 |

## 건드리지 않는 파일
- `src/backtest/signal_source.py` — 이미 완성
- `src/backtest/cli.py` — 이미 연결
- `src/backtest/engine.py` — 변경 불필요
- `src/backtest/repository.py` — 변경 불필요

## 완료 기준
- `pytest test/test_backtest_replay.py` — 3+ passed
- 기존 `pytest test/` 회귀 없음

## PR
- 브랜치: `feat/step10-signal-replay-test`
- 제목: `test(step10): Strategy A/B Signal Replay 통합 테스트`

---

# Agent 2 — Step 12 대시보드 UI (Backtest 결과 페이지)

## 목표
기존 React 앱에 Backtest 결과 시각화 페이지를 추가한다.
UI 프로젝트는 이미 성숙한 상태(22개 라우트, 10개 훅, Recharts/TanStack Query/Zustand 세팅 완료).

## 현재 상태
- `ui/web/` — React 18 + Vite + TypeScript + TailwindCSS
- 의존성: `@tanstack/react-query ^5.28.0`, `zustand ^4.5.2`, `recharts ^2.12.2`, `axios ^1.6.7`
- API 클라이언트: `ui/web/src/utils/api.ts` — `baseURL: "/api/v1"`, JWT 자동 주입
- 기존 페이지: Dashboard, Portfolio, Strategy, RLTrading, Market 등 17+ 페이지
- 라우팅: `ui/web/src/App.tsx` — lazy import + RequireAuth wrapper
- **부족한 것**: Backtest 전용 페이지가 없다.

## 작업 항목

### 1. Backtest 훅 생성
**파일:** `ui/web/src/hooks/useBacktest.ts` (신규)

```typescript
// --- API 타입 ---
interface BacktestRunSummary {
  id: number;
  ticker: string;
  strategy: string;
  test_start: string;
  test_end: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  total_trades: number;
  created_at: string;
}

interface BacktestRunDetail extends BacktestRunSummary {
  train_start: string;
  train_end: string;
  initial_capital: number;
  commission_rate_pct: number;
  tax_rate_pct: number;
  slippage_bps: number;
  annual_return_pct: number;
  avg_holding_days: number;
  baseline_return_pct: number;
  excess_return_pct: number;
}

interface BacktestDaily {
  date: string;
  close_price: number;
  portfolio_value: number;
  daily_return_pct: number;
  position_qty: number;
}

// --- 훅 ---
// useBacktestRuns(page, perPage) — 목록 조회
//   GET /api/v1/backtest/runs?page=1&per_page=20
//   returns { data: BacktestRunSummary[], meta: { page, per_page, total } }

// useBacktestDetail(runId) — 상세 조회
//   GET /api/v1/backtest/runs/{runId}
//   returns BacktestRunDetail

// useBacktestDaily(runId) — 일별 스냅샷 조회
//   GET /api/v1/backtest/runs/{runId}/daily
//   returns BacktestDaily[]
```

### 2. Backtest 목록 페이지
**파일:** `ui/web/src/pages/Backtest.tsx` (신규)

- 테이블: 전략별 백테스트 실행 목록 (ticker, strategy, 수익률, 샤프, MDD, 승률)
- 필터: strategy 드롭다운 (All/RL/A/B/BLEND)
- 정렬: 생성일 DESC (기본), 수익률/샤프 클릭 정렬
- 행 클릭 → 상세 페이지 이동
- 페이지네이션: page/per_page 쿼리 파라미터

### 3. Backtest 상세 페이지
**파일:** `ui/web/src/pages/BacktestDetail.tsx` (신규)

- 상단: 설정 요약 카드 (ticker, strategy, 기간, 초기자본, 비용)
- 성과 지표 카드: 수익률, 연환산, 샤프, MDD, 승률, 매매횟수, Buy&Hold 비교
- 차트 (Recharts):
  - 포트폴리오 가치 곡선 (LineChart, portfolio_value over date)
  - 일별 수익률 바차트 (BarChart, daily_return_pct)
- 데이터: `useBacktestDaily(runId)` 활용

### 4. 라우트 등록
**파일:** `ui/web/src/App.tsx` (수정 — 2줄 추가)

```typescript
const Backtest = lazy(() => import("./pages/Backtest"));
const BacktestDetail = lazy(() => import("./pages/BacktestDetail"));

// Routes 내부:
<Route path="backtest" element={<Backtest />} />
<Route path="backtest/:runId" element={<BacktestDetail />} />
```

### 5. 사이드바 네비게이션 추가
**파일:** `ui/web/src/App.tsx` (수정 — navItems 배열에 1항목 추가)

```typescript
{ path: "/backtest", icon: BarChart3, label: "백테스트", description: "전략 시뮬레이션 결과" }
```

## 수정 파일
| 파일 | 작업 | 신규/수정 |
|------|------|----------|
| `ui/web/src/hooks/useBacktest.ts` | API 훅 3개 | 신규 |
| `ui/web/src/pages/Backtest.tsx` | 목록 페이지 | 신규 |
| `ui/web/src/pages/BacktestDetail.tsx` | 상세 페이지 + 차트 | 신규 |
| `ui/web/src/App.tsx` | 라우트 + 네비 추가 | 수정 |

## 건드리지 않는 파일
- `ui/web/src/utils/api.ts` — 기존 axios 인스턴스 그대로 사용
- `ui/web/src/stores/` — 서버 상태는 React Query, Zustand 추가 불필요
- `ui/web/package.json` — 새 패키지 설치 없음 (recharts 이미 있음)
- `src/` 백엔드 코드 일체

## API 의존 (Agent 4와 인터페이스 합의)

Agent 4가 구현할 API 응답 스키마:

```
GET /api/v1/backtest/runs?page=1&per_page=20&strategy=RL
→ { "data": [BacktestRunSummary...], "meta": { "page", "per_page", "total" } }

GET /api/v1/backtest/runs/{id}
→ BacktestRunDetail (backtest_runs 전체 컬럼)

GET /api/v1/backtest/runs/{id}/daily
→ [BacktestDaily...] (backtest_daily 전체 컬럼)
```

API가 아직 없으면 목록/상세 페이지는 로딩/에러 상태를 표시하고, 데이터가 오면 자연스럽게 렌더링된다 (React Query의 기본 동작).

## 완료 기준
- `cd ui/web && npm run build` — 빌드 성공
- `cd ui/web && npm run lint` — 에러 없음
- 브라우저에서 `/backtest` 접근 → 목록 페이지 렌더링 (API 404여도 에러 상태 표시)
- `/backtest/:id` 접근 → 상세 페이지 렌더링

## PR
- 브랜치: `feat/step12-backtest-ui`
- 제목: `feat(step12): 백테스트 결과 시각화 UI 페이지`

---

# Agent 3 — Orchestrator heartbeat 모니터링 + Telegram 알림

## 목표
Orchestrator가 매 사이클에서 전체 에이전트의 heartbeat 상태를 점검하고,
이상(degraded/error/offline) 감지 시 NotifierAgent를 통해 Telegram 알림을 발송한다.

## 현재 상태
- `set_heartbeat(agent_id, status="ok", **metadata)`: `src/utils/redis_client.py:93-119`
- `get_heartbeat_detail(agent_id) -> dict | None`: `src/utils/redis_client.py:139-144`
- `check_heartbeat(agent_id) -> bool`: `src/utils/redis_client.py:132-136`
- `OrchestratorAgent.run_cycle()`: `src/agents/orchestrator.py:155-473`
  - 성공 시 heartbeat 기록: line 382, 396-406
  - 실패 시 error heartbeat: line 464-470
- `NotifierAgent.send(event_type, message) -> bool`: `src/agents/notifier.py:43-93`
  - 기존 알림: `send_cycle_summary()`, `send_promotion_alert()`, `send_paper_daily_report()`
  - placeholder secret이면 `db_only` 모드로 DB만 기록
- `docs/HEARTBEAT.md` — Orchestrator 모니터링은 "계획" 상태로 미구현 명시

## 작업 항목

### 1. NotifierAgent에 heartbeat 알림 메서드 추가
**파일:** `src/agents/notifier.py` (수정)

```python
async def send_agent_health_alert(
    self,
    agent_id: str,
    status: str,          # "degraded" | "error" | "offline"
    mode: str = "",
    error_count: int = 0,
) -> bool:
    """에이전트 건강 이상 감지 시 Telegram 알림."""
    emoji = {"degraded": "⚠️", "error": "🔴", "offline": "⚫"}.get(status, "❓")
    mode_label = f"\n- 모드: {mode}" if mode else ""
    error_label = f"\n- 에러 횟수: {error_count}" if error_count else ""
    text = (
        f"{emoji} 에이전트 상태 이상\n"
        f"- 에이전트: {agent_id}\n"
        f"- 상태: {status}"
        f"{mode_label}"
        f"{error_label}\n"
        f"- 시각(UTC): {datetime.utcnow().isoformat()}Z"
    )
    return await self.send("agent_health_alert", text)
```

### 2. Orchestrator에 heartbeat 점검 메서드 추가
**파일:** `src/agents/orchestrator.py` (수정)

```python
async def _check_agent_health(self) -> list[dict]:
    """전체 에이전트 heartbeat 상태를 점검하고 이상 목록을 반환한다."""
    from src.utils.redis_client import get_heartbeat_detail

    agent_ids = [
        "collector_agent",
        "portfolio_manager_agent",
        "notifier_agent",
    ]
    issues = []
    for aid in agent_ids:
        detail = await get_heartbeat_detail(aid)
        if detail is None:
            issues.append({"agent_id": aid, "status": "offline"})
        elif detail.get("status") == "error":
            issues.append({
                "agent_id": aid,
                "status": "error",
                "mode": detail.get("mode", ""),
                "error_count": int(detail.get("error_count", 0)),
            })
        elif detail.get("status") == "degraded":
            issues.append({
                "agent_id": aid,
                "status": "degraded",
                "mode": detail.get("mode", ""),
                "error_count": int(detail.get("error_count", 0)),
            })
    return issues
```

### 3. run_cycle()에 health check 호출 삽입
**파일:** `src/agents/orchestrator.py` (수정 — run_cycle 내부)

```python
# run_cycle 성공 후 (line ~407 근처), 기존 heartbeat 기록 이후에 삽입:
issues = await self._check_agent_health()
if issues:
    notifier = NotifierAgent()
    for issue in issues:
        await notifier.send_agent_health_alert(**issue)
    logger.warning("에이전트 상태 이상 감지: %s", issues)
```

### 4. 단위 테스트
**파일:** `test/test_orchestrator_monitoring.py` (신규)

```python
# 테스트 1: _check_agent_health — 모든 에이전트 ok → 빈 리스트
# 테스트 2: _check_agent_health — collector가 error → issues에 포함
# 테스트 3: _check_agent_health — heartbeat 없음(offline) → issues에 포함
# 테스트 4: send_agent_health_alert — 메시지 포맷 검증 (emoji, 필드)
# 테스트 5: send_agent_health_alert — placeholder secret → db_only 모드
# 테스트 6: run_cycle에서 health check 호출 확인 (mock)
```

### 5. HEARTBEAT.md 업데이트
**파일:** `docs/HEARTBEAT.md` (수정)

- "Orchestrator 모니터링 (계획)" → "Orchestrator 모니터링" (계획 태그 제거)
- 실제 구현과 일치하도록 행동 테이블 업데이트

## 수정 파일
| 파일 | 작업 | 신규/수정 |
|------|------|----------|
| `src/agents/notifier.py` | `send_agent_health_alert()` 추가 | 수정 |
| `src/agents/orchestrator.py` | `_check_agent_health()` + run_cycle 연동 | 수정 |
| `docs/HEARTBEAT.md` | 계획 → 구현 반영 | 수정 |
| `test/test_orchestrator_monitoring.py` | 단위 테스트 6개 | 신규 |

## 건드리지 않는 파일
- `src/utils/redis_client.py` — 기존 get_heartbeat_detail() 그대로 사용
- `src/agents/collector.py` — 변경 불필요
- `scripts/` — 변경 불필요

## 완료 기준
- `pytest test/test_orchestrator_monitoring.py` — 6 passed
- 기존 `pytest test/` 회귀 없음

## PR
- 브랜치: `feat/step8a-orchestrator-monitoring`
- 제목: `feat(step8a): Orchestrator heartbeat 모니터링 + Telegram 알림`

---

# Agent 4 — Backtest API GET 엔드포인트

## 목표
백테스트 결과를 조회하는 REST API 3개를 추가한다.
대시보드 UI(Agent 2)가 이 API를 소비한다.

## 현재 상태
- DB 테이블: `backtest_runs` (메타+지표), `backtest_daily` (일별 스냅샷) — DDL은 `scripts/db/init_db.py`에 존재
- repository: `save_backtest()`, `fetch_backtest_run()` — `src/backtest/repository.py`
- 기존 API 패턴:
  - 라우터 등록: `src/api/main.py:180-195` — `app.include_router()`
  - 인증: `Depends(get_current_user)` — `src/api/deps.py`
  - 페이지네이션: `page/per_page` Query → `{ "data": [...], "meta": {...} }`
  - DB 조회: `fetch()` / `fetchrow()` — `src/utils/db_client.py`
  - 에러: `HTTPException(status_code=404, detail="...")`

## 작업 항목

### 1. Backtest 라우터 생성
**파일:** `src/api/routers/backtest.py` (신규)

```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from typing import Annotated, Optional
from src.api.deps import get_current_user
from src.utils.db_client import fetch, fetchrow, fetchval

router = APIRouter()

# ── Response Models ──

class BacktestRunSummary(BaseModel):
    id: int
    ticker: str
    strategy: str
    test_start: str
    test_end: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    created_at: str

class BacktestRunDetail(BaseModel):
    # BacktestRunSummary 전체 + 추가 필드
    id: int
    ticker: str
    strategy: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    initial_capital: int
    commission_rate_pct: float
    tax_rate_pct: float
    slippage_bps: int
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    avg_holding_days: float
    baseline_return_pct: float
    excess_return_pct: float
    created_at: str

class BacktestDailyItem(BaseModel):
    date: str
    close_price: float
    cash: float
    position_qty: int
    position_value: float
    portfolio_value: float
    daily_return_pct: float


# ── Endpoints ──

@router.get("/runs")
async def list_backtest_runs(
    _: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    strategy: Optional[str] = Query(default=None, pattern="^(RL|A|B|BLEND)$"),
) -> dict:
    """백테스트 실행 목록 조회."""
    # 동적 WHERE 절 (strategy 필터 선택)
    # ORDER BY created_at DESC
    # LIMIT per_page OFFSET (page-1)*per_page
    # total count는 별도 fetchval
    ...

@router.get("/runs/{run_id}")
async def get_backtest_run(
    run_id: int,
    _: Annotated[dict, Depends(get_current_user)],
) -> BacktestRunDetail:
    """백테스트 실행 상세 조회."""
    # fetchrow("SELECT * FROM backtest_runs WHERE id = $1", run_id)
    # 없으면 404
    ...

@router.get("/runs/{run_id}/daily")
async def get_backtest_daily(
    run_id: int,
    _: Annotated[dict, Depends(get_current_user)],
) -> list[BacktestDailyItem]:
    """백테스트 일별 스냅샷 조회."""
    # 먼저 run_id 존재 확인 (없으면 404)
    # fetch("SELECT ... FROM backtest_daily WHERE run_id = $1 ORDER BY date", run_id)
    ...
```

### 2. 라우터 등록
**파일:** `src/api/main.py` (수정 — 2줄 추가)

```python
from src.api.routers import backtest  # import 추가

app.include_router(backtest.router, prefix=f"{API_PREFIX}/backtest", tags=["backtest"])
```

### 3. 단위 테스트
**파일:** `test/test_api_backtest.py` (신규)

```python
# 테스트 1: GET /runs — 빈 테이블 → { "data": [], "meta": { "total": 0 } }
# 테스트 2: GET /runs — strategy 필터 동작 확인
# 테스트 3: GET /runs — 페이지네이션 (page=2, per_page=5)
# 테스트 4: GET /runs/{id} — 존재하는 run → 200 + 전체 필드
# 테스트 5: GET /runs/{id} — 존재하지 않는 run → 404
# 테스트 6: GET /runs/{id}/daily — 일별 스냅샷 반환 확인
# 테스트 7: GET /runs/{id}/daily — 존재하지 않는 run → 404
# 테스트 8: 인증 없이 호출 → 401 (또는 403)
```

DB mock 방식: `fetch`/`fetchrow`/`fetchval`을 patch하여 하드코딩 결과 반환.

## 수정 파일
| 파일 | 작업 | 신규/수정 |
|------|------|----------|
| `src/api/routers/backtest.py` | 라우터 3개 엔드포인트 | 신규 |
| `src/api/main.py` | 라우터 등록 (2줄) | 수정 |
| `test/test_api_backtest.py` | 단위 테스트 8개 | 신규 |

## 건드리지 않는 파일
- `src/backtest/` — repository.py의 기존 함수 사용 가능하나, 직접 SQL이 더 유연
- `src/api/deps.py` — 기존 `get_current_user` 그대로 사용
- `src/utils/db_client.py` — 기존 `fetch`/`fetchrow`/`fetchval` 그대로 사용

## Agent 2와의 인터페이스 합의

| Endpoint | Response | 비고 |
|----------|----------|------|
| `GET /api/v1/backtest/runs` | `{ "data": [BacktestRunSummary], "meta": { "page", "per_page", "total" } }` | 기존 페이지네이션 패턴 동일 |
| `GET /api/v1/backtest/runs/{id}` | `BacktestRunDetail` | backtest_runs 전체 컬럼 |
| `GET /api/v1/backtest/runs/{id}/daily` | `[BacktestDailyItem]` | backtest_daily 전체 컬럼, date ASC |

날짜 필드는 ISO 문자열 (`YYYY-MM-DD` 또는 `YYYY-MM-DDTHH:MM:SSZ`).

## 완료 기준
- `pytest test/test_api_backtest.py` — 8 passed
- 기존 `pytest test/` 회귀 없음

## PR
- 브랜치: `feat/step10-backtest-api`
- 제목: `feat(step10): Backtest API GET 엔드포인트 (runs/detail/daily)`

---

# 파일 충돌 검증 매트릭스

| 파일 | Agent 1 | Agent 2 | Agent 3 | Agent 4 |
|------|:-------:|:-------:|:-------:|:-------:|
| `src/backtest/signal_source.py` | - | - | - | - |
| `src/backtest/engine.py` | - | - | - | - |
| `src/backtest/repository.py` | - | - | - | - |
| `test/test_backtest_replay.py` | **신규** | - | - | - |
| `test/fixtures/replay_signals.json` | **신규** | - | - | - |
| `ui/web/src/hooks/useBacktest.ts` | - | **신규** | - | - |
| `ui/web/src/pages/Backtest.tsx` | - | **신규** | - | - |
| `ui/web/src/pages/BacktestDetail.tsx` | - | **신규** | - | - |
| `ui/web/src/App.tsx` | - | **수정** | - | - |
| `src/agents/orchestrator.py` | - | - | **수정** | - |
| `src/agents/notifier.py` | - | - | **수정** | - |
| `docs/HEARTBEAT.md` | - | - | **수정** | - |
| `test/test_orchestrator_monitoring.py` | - | - | **신규** | - |
| `src/api/routers/backtest.py` | - | - | - | **신규** |
| `src/api/main.py` | - | - | - | **수정** |
| `test/test_api_backtest.py` | - | - | - | **신규** |

**충돌: 0건** — 4에이전트 간 수정 파일 겹침 없음.

## 8. Follow-up Actions

- [x] 4에이전트 동시 착수 → 각 PR 생성
- [x] 4개 PR 머지 후 통합 회귀 테스트 — 778 passed
- [x] progress.md + roadmap.md 업데이트

## 9. 클라우드 전환 + 데이터 압축 (2026-04-10 추가 논의)

### 인프라 결정
- Mac Mini 구매 취소 → **AWS Lightsail 서울 리전** (2 vCPU / 4GB / 80GB SSD, $24/월)
- MinIO → **AWS S3** 전환 (코드 변경 0줄, `.env`만 수정)
- K3s + Kustomize 자산 100% 재사용
- 월 총 비용: ~$27 (약 3.7만원)

### 데이터 압축 적용
- S3 Parquet: Snappy → **zstd** (저장 30~40% 감소) — `datalake.py` 1줄 변경
- PostgreSQL: 대형 TEXT 컬럼 (debate_transcripts, predictions) **lz4 TOAST 압축** — `init_db.py` DDL 추가
- S3 Lifecycle Policy: 30일 → IA, 90일 → Glacier (클라우드 전환 시 설정)
- DB 데이터 아카이브 (90일/1년 → S3 퍼지): Step 8b에서 구현

## 10. Closure Checklist

- [x] 구조/장기 방향 변경 사항을 `.agent/roadmap.md`에 반영
- [x] 이번 세션의 할 일을 `progress.md`에 반영
- [ ] 계속 유지되어야 하는 운영 규칙을 `MEMORY.md`에 반영
- [ ] 필요한 영구 문서 반영 후 이 논의 문서를 삭제
