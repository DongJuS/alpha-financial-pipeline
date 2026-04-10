# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
기존 Strategy A/B 기반 자동 투자 시스템을 유지한 채, RL Trading과 Search/Scraping pipeline을 어떤 순서로 편입할지 정리합니다.
이 파일은 마일스톤 수준의 방향과 원칙만 작성합니다. 구체적인 체크리스트, 서브태스크, 이슈 등은 progress.md를 참조합니다.
완료된 이력은 roadmap-archive.md를 참조하세요.

---

## 현재 상태 (2026-04-10)

- **코어 트레이딩**: Phase 1~13 구현 완료, 유지보수 단계
- **Step 3~7 완료**: RL 블렌딩, K3s 배포, 안정화, 테스트 정비, 글로벌 데이터 레이크 (11.5M행, ohlcv_daily src 전환 완료)
- **Step 8a 완료**: heartbeat Hash 확장 + Docker/K8s healthcheck + Orchestrator 모니터링 + Telegram 알림 (PR #123~#127)
- **Step 9 Phase 1 완료**: constants.py + 매직 넘버 교체 + Settings 단일화 (PR #107~110)
- **Step 10 완료**: RL 백테스트 + Signal Replay 테스트 + API 3개 + 안정화 (PR #111~#127)
- **Step 12 백테스트 UI 완료**: 목록/상세 페이지 + 포트폴리오 가치 곡선 + 일별 수익률 차트 (PR #126)
- **다음 목표**: Step 8 WebSocket 모듈 분리 + 다중 연결 + 재연결 강화 → Step 8b 틱 전용 DB + 멀티 타임프레임 → Step 9 Phase 2(모델 교체 시)

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

### Step 8a — WebSocket heartbeat + health_check + 모니터링 ✅

PR #123~#127. heartbeat String→Hash 확장 → Docker/K8s healthcheck 교체 → Orchestrator 모니터링 → Telegram 알림.
WS 끊김 → heartbeat status 반영 → healthcheck 감지 → Orchestrator 감지 → Telegram 알림 전체 체인 완성.

### Step 9 Phase 1 — 상수 + Settings 단일화 ✅

PR #107~110. 4에이전트 병렬 실행으로 3시간 분량을 1시간에 완료.
- `src/constants.py` 신규: `PAPER_TRADING_INITIAL_CAPITAL`, `DEFAULT_*_MODEL`
- 18곳+ 매직 넘버 → 상수 교체 (7파일)
- `os.environ.get()` 6건 → `get_settings()` 전환 + config.py 5개 필드 추가

### Step 10 — 백테스트 시뮬레이션 ✅

PR #111~#127. 전략 A/B/RL 모두 과거 데이터 검증 가능.
- RL 백테스트 엔진 + CLI + DB 저장 (backtest_runs/backtest_daily)
- Signal Replay: predictions DB 재생으로 Strategy A/B 백테스트
- API 3개: GET runs 목록, GET runs/{id} 상세, GET runs/{id}/daily 일별 스냅샷
- 성과 지표: 수익률, 연환산, 샤프, MDD, 승률, Buy&Hold 초과수익률
- 안정화: E2E 9/9 passed, Docker healthy, gen 격리 정상

### Step 12 — 백테스트 대시보드 UI ✅

PR #126. React 18 + Recharts 기반 백테스트 결과 시각화.
- 목록 페이지: 전략 필터(RL/A/B/BLEND), 수익률·샤프·MDD 테이블, 페이지네이션
- 상세 페이지: 성과 지표 8개 카드, 포트폴리오 가치 곡선(LineChart), 일별 수익률(BarChart)
- React Query 훅 3개 + 라우트/네비게이션 등록

### 안정화 스프린트 ✅

PR #115~#121. E2E 9/9 passed, Docker 8서비스 healthy, gen 격리 정상. 746 tests passed.

---

## 진행 중 마일스톤

### Step 7b — Airflow 비교 스파이크

DAG 6/6 SUCCESS + 비교 문서 완료. Airflow UI 스크린샷만 잔여.

### Step 8 — KIS WebSocket 실시간 (다음 작업)

**왜 필요한가:** 이 시스템은 주식 자동 매매를 한다. 현재는 하루에 한 번 종가(일봉)를 가져와서 전략을 실행하지만,
초 단위로 들어오는 실시간 시세(틱 데이터)를 기반으로 더 빠르게 매매 판단을 내리는 **틱 전략**이 필수적이다.
틱 전략에서는 데이터가 1초라도 끊기면 잘못된 매매 신호가 나올 수 있으므로, 안정적인 실시간 수집 인프라가 핵심이다.

**현재 상태:** KIS(한국투자증권) WebSocket으로 실시간 시세를 받는 기본 코드는 있다.
그러나 모든 수집 로직(일봉/Yahoo/분봉/실시간)이 `collector.py` 한 파일 1128줄에 섞여 있어서,
실시간 로직을 수정하면 일봉 수집이 깨질 위험이 있다. 또한 종목 40개 초과 시 연결을 분할하는 기능과,
끊김 시 자동 복구를 강화하는 작업이 남아있다.

**이번 Step 8 범위 (팀 토론 결정 2026-04-10):**

1. **collector.py 모듈 분리** — 1128줄 단일 파일을 역할별로 쪼갠다
   - `_base.py`: 공통 (heartbeat, 종목 조회, Redis 캐시)
   - `_realtime.py`: WebSocket 실시간 수집 전담
   - `_daily.py`: FDR/Yahoo 일봉 수집
   - `_historical.py`: 과거 데이터 대량 수집
   - `__init__.py`: 기존 import 호환 유지하는 외부 인터페이스
2. **다중 WebSocket 연결** — KIS는 연결 1개당 종목 40개 제한. 종목이 늘면 여러 연결을 동시에 열어 병렬 수집 (`asyncio.gather`)
3. **재연결 강화** — 끊김 시 랜덤 지연(jitter) + 최대 30초 대기. 한 연결이 죽어도 다른 연결은 계속 수집
4. **TickData 전용 모델** — 현재 틱 데이터를 일봉 스키마(`MarketDataPoint`)에 억지로 끼워넣고 있다. 틱 전용 DTO를 만들어 틱 전략이 직접 소비할 수 있게 한다
5. **K8s 환경변수 + 테스트** — 운영 설정 4개를 환경변수로 관리 + WebSocket 코드의 mock 테스트

**실행 순서:** 1(뼈대) → 2+3(병렬, 로직 이동) → 4(인프라+테스트)

### Step 8b — 틱 전용 저장소 + 멀티 타임프레임 (Step 8 이후)

**왜 필요한가:** Step 8에서 틱 데이터를 안정적으로 수집할 수 있게 되면,
그 데이터를 효율적으로 저장하고, 다양한 시간 단위(분봉, 시간봉 등)로 가공해서
RL 학습이나 전략 판단에 활용해야 한다.

**범위:**
- 틱 전용 DB 테이블 (또는 TimescaleDB hypertable) — 하루 수십~수백만 건 처리
- 데이터 계층화: Hot(Redis, 실시간) → Warm(DB, 3일) → Cold(S3, 장기)
- 멀티 타임프레임 파이프라인: 틱 → 분봉 집계 → RL feature vector 확장
- 데이터 갭 자동 백필: WebSocket 끊김 구간을 REST API로 복구

### Step 9 Phase 2 — LLM Factory (후순위)

`src/llm/factory.py` 신규 생성. predictor, strategy_b_consensus에서 Factory 사용.
후순위 이유: constants.py에 모델명 상수가 이미 있어 변경 어렵지 않고, 모델 교체 계획 없음.

### Phase 10 — 확장 통합 운영 (잔여)

SearchAgent 잠정 중단 상태.

---

## 미정 — Hot/Cold 데이터 Lifecycle 자동화

PostgreSQL + S3 이중 저장 수명 관리. Hot(최근 N일) PostgreSQL → Cold(N일 후) S3만 보존.
시기: 데이터 규모가 PostgreSQL 성능에 영향을 줄 때 착수. (현재 1.94GB, 성능 이슈 없음)

---

### 하지 않는 것 (오버엔지니어링 방지)
- Builder 패턴, DI 컨테이너 — 현재 규모에서 불필요
- 사전 최적화 (리소스 튜닝 등) — 실측 후 조정

### 설계 원칙
- **관심사 분리는 항상 고려한다** — 코드가 길어지면 역할별로 모듈을 분리한다. 클린 코드는 후순위가 아니라 기본이다
- **틱 전략은 필수** — 일봉 전략만으로는 한계가 있으며, 실시간 데이터 기반 전략 확장을 전제로 인프라를 설계한다

### 장기 로드맵 (트리거 조건 충족 시)
- Strategy 패턴 — 종목 100개 이상 시
- Helm values → constants 연동 — 멀티 클러스터 시

### 보류
- SearchAgent (SearXNG 통합)
- RL 하이퍼파라미터 자동 탐색 (Optuna)
- Pre-commit Lint 자동화 (ruff --fix)
