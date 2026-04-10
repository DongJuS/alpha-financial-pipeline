# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
기존 Strategy A/B 기반 자동 투자 시스템을 유지한 채, RL Trading과 Search/Scraping pipeline을 어떤 순서로 편입할지 정리합니다.
이 파일은 마일스톤 수준의 방향과 원칙만 작성합니다. 구체적인 체크리스트, 서브태스크, 이슈 등은 progress.md를 참조합니다.
완료된 이력은 roadmap-archive.md를 참조하세요.

---

## 현재 상태 (2026-04-10)

- **코어 트레이딩**: Phase 1~13 구현 완료, 유지보수 단계
- **Step 3~7 완료**: RL 블렌딩, K3s 배포, 안정화, 테스트 정비, 글로벌 데이터 레이크 (11.5M행, ohlcv_daily src 전환 완료)
- **Step 7b 거의 완료**: Airflow DAG 6개 SUCCESS + 비교 문서. UI 스크린샷만 잔여
- **Step 8 구현됨**: KIS WebSocket 실시간 수집 코드 존재. 다중 연결 확장/안정화 잔여
- **Step 9 Phase 1 완료**: constants.py + 매직 넘버 교체 + Settings 단일화 (PR #107~110)
- **안정화 스프린트 90%**: PR #115~#119 완료, 735 tests. E2E 1건 실패(SELL 미생성) + Docker/gen 검증 잔여
- **다음 목표**: E2E 실패 해결 → Docker/gen 검증 → Step 8 안정화 → Step 9 Phase 2

---

## 완료된 마일스톤

### Step 3 — RL 부트스트랩 + 3전략 동시 블렌딩 ✅

PR #32/#33/#34. 장 전(학습) → 장 중(블렌딩) → 장 후(재학습) 운영 흐름 완성.

### Step 4 — K3s 프로덕션 배포 ✅

PR #38/#39/#41/#51/#63/#64/#68. Helm(인프라) + Kustomize(앱) 병행 전략.
deploy.sh Helm→Kustomize 순서 정상. K3s 6 Pod Running 검증 완료.

### Step 5 — Alpha 안정화 + 제출 준비 ✅

PR #48/#49/#51/#52/#53/#54. docker compose 클린 기동 → 8서비스 healthy → smoke test 통과 → 1사이클 재현.

### Step 6 — 테스트 스위트 완전 정비 ✅

PR #44/#45/#50. 462 → 612 passed. event loop 오염 해결, 인터페이스 불일치 수정.

### Step 7 — 글로벌 데이터 레이크 ✅

KR 2,771 + US 6,595 종목, 11.5M행 수집 완료. ohlcv_daily 파티셔닝.
src/ 코드 전체 ohlcv_daily 전환 완료 (queries/models/collector/API/RL).

### Step 9 Phase 1 — 상수 + Settings 단일화 ✅

PR #107~110. 4에이전트 병렬 실행으로 3시간 분량을 1시간에 완료.
- `src/constants.py` 신규: `PAPER_TRADING_INITIAL_CAPITAL`, `DEFAULT_*_MODEL`
- 18곳+ 매직 넘버 → 상수 교체 (7파일)
- LLM 모델명 12곳 → 상수 교체 (6파일)
- `os.environ.get()` 6건 → `get_settings()` 전환 + config.py 5개 필드 추가

---

## 안정화 스프린트 (2026-04-10 ~) ← 현재

Step 10 백테스트 코드 4개 PR(#111~#114) 병렬 머지 후, PR #115~#119로 통합 검증 거의 완료.

**완료 (PR #115~#119):**
1. ✅ integration test CI 분리 (`pytest.ini --ignore=test/integration`)
2. ✅ backtest DDL 확인 + gymnasium 의존성 추가 (PR #116)
3. ✅ CLI 기동 + 4-PR 인터페이스 불일치 수정 (PR #115)
4. ✅ engine ↔ signal_source ↔ cost_model 통합 테스트 2개 (PR #117)
5. ✅ `fetch_ohlcv_range()` + RL position state mismatch fix (PR #118)
6. ✅ CLI `_load_ohlcv()` → `fetch_ohlcv_range` 전환 + fixture CSV (PR #119)
7. ✅ E2E 테스트 작성 (`test/test_backtest_e2e_rl.py`)
8. ✅ 735 tests passed, 1 failed

**완료 조건 달성:** E2E 9 tests passed + 737 tests passed (PR #121)

---

## 진행 중 마일스톤

### Step 7b — Airflow 비교 스파이크

DAG 6/6 SUCCESS + 비교 문서 완료. Airflow UI 스크린샷만 잔여.

### Step 8 — KIS WebSocket 실시간

WebSocket 연결 + 틱 수집 → Redis + DB 저장 구현 완료.
잔여: 다중 연결 확장 (20→40종목), 재연결/장애 복구 안정화.

### Step 9 Phase 2 — LLM Factory (후순위)

`src/llm/factory.py` 신규 생성. predictor, strategy_b_consensus에서 Factory 사용.
LLM 모델명 중복 제거 (6파일 → 1곳 관리). 시기: LLM 모델 변경 시 착수.
후순위 이유: constants.py에 모델명 상수가 이미 있어 변경 어렵지 않고, 모델 교체 계획 없음.

### Step 10 — 백테스트 시뮬레이션 (코드 머지 완료, 통합 검증 중)

전략의 실제 유효성을 과거 데이터로 검증한다. ohlcv_daily 11.5M행 활용.
백테스트 결과에 따라 이후 전략 집중 방향, Step 8/9 P2 착수 시점이 결정된다.

**현재 상태 (2026-04-10):** PR #111~#121로 코드 + 안정화 완료. 746 tests passed.

**(fix) 결정 사항:**
- RL 백테스트를 먼저 구현 (gymnasium 환경 재사용, LLM 비용 없음)
- 성과 지표: 수익률, 샤프 비율, MDD, 승률
- 수수료 0.015% + 세금 0.18% 반영
- train/test 기간 반드시 분리 (과적합 방지)
- Strategy A/B: Signal Replay (predictions DB 재생), 룰 기반 Proxy는 데이터 부족 시에만
- 구현 구조: `src/backtest/` 신규 디렉터리 (engine, metrics, models, signal_source, cli)
- 저장: DB 2테이블 (backtest_runs 메타 + backtest_daily 상세)
- 인터페이스: CLI 먼저 (`python -m src.backtest`), API는 결과 조회 GET만 이후
- 체결 시뮬: BacktestEngine 내 인메모리 포지션 추적, 고정 슬리피지 3bps (재현성)
- 가중치 최적화: 그리드 서치 0.05 단위 (231조합), 샤프 비율 기준 + MDD 제약
- 구현 순서: P0(RL백테스트+구조+DB+테스트+CLI) → P1(ReplaySource) → P2(가중치최적화) → P3(API+K8s)

### Phase 10 — 확장 통합 운영 (잔여)

SearchAgent 잠정 중단 상태.

### Step 12 — 대시보드 UI

백테스트 결과 시각화 + 포트폴리오 모니터링 대시보드. Step 10 완료 후 착수.

---

## 미정 — Hot/Cold 데이터 Lifecycle 자동화

PostgreSQL + S3 이중 저장 수명 관리. Hot(최근 N일) PostgreSQL → Cold(N일 후) S3만 보존.
시기: 데이터 규모가 PostgreSQL 성능에 영향을 줄 때 착수. (현재 1.94GB, 성능 이슈 없음)

### 미정 — 멀티 타임프레임 데이터 파이프라인

FDR 일봉 + KIS 분봉/틱 통합. RL state vector를 멀티 타임프레임으로 확장.
4단계 구현: ohlcv_minute → RL feature → tick_summary → feature 전처리.
시기: Step 8 WebSocket 안정화 후. Step 8은 Step 10 백테스트 이후 재검토.

---

### 하지 않는 것 (오버엔지니어링 방지)
- Builder 패턴, DI 컨테이너, ABC 추상 클래스 — 현재 규모에서 불필요
- "추상화가 없어서 버그가 2번 발생한 후에 하라" 원칙

### 장기 로드맵 (문제 발생 시)
- Strategy 패턴 — 종목 100개 이상 시
- BaseCollector ABC — 새 데이터 소스 추가 시
- Helm values → constants 연동 — 멀티 클러스터 시

### 보류
- SearchAgent (SearXNG 통합)
- RL 하이퍼파라미터 자동 탐색 (Optuna)
- Pre-commit Lint 자동화 (ruff --fix)
