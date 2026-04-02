# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
기존 Strategy A/B 기반 자동 투자 시스템을 유지한 채, RL Trading과 Search/Scraping pipeline을 어떤 순서로 편입할지 정리합니다.
이 파일은 마일스톤 수준의 방향과 원칙만 작성합니다. 구체적인 체크리스트, 서브태스크, 이슈 등은 progress.md를 참조합니다.
완료된 이력은 roadmap-archive.md를 참조하세요.

---

## 현재 상태 (2026-03-29)

- **코어 트레이딩**: Phase 1~13 구현 완료, 유지보수 단계
- **Step 3 완료**: RL 부트스트랩 + 3전략 동시 블렌딩
- **Step 4 대부분 완료**: Helm chart + CI/CD + Dockerfile. 모니터링/실배포만 잔여
- **Step 5 완료**: Alpha 안정화 (e2e 검증, smoke test, Collector→Orchestrator 1사이클 재현, README, Airflow 비교 문서)
- **Step 6 완료**: 테스트 557 passed, 0 failed
- **다음 목표**: 제출(3/30) → 모니터링 → K3s 실배포

---

## 완료된 마일스톤

### Step 3 — RL 부트스트랩 + 3전략 동시 블렌딩 ✅

PR #32/#33/#34. 장 전(학습) → 장 중(블렌딩) → 장 후(재학습) 운영 흐름 완성.

### Step 5 — Alpha 안정화 + 제출 준비 ✅

PR #48/#49/#51/#52/#53/#54. docker compose 클린 기동 → 8서비스 healthy → smoke test 통과 → Collector→Orchestrator 1사이클 재현(수집 24건→3전략 병렬→블렌딩 fallback→S3 저장, 16초) → README 정량 지표 → Airflow 비교 문서.

### Step 6 — 테스트 스위트 완전 정비 ✅

PR #44/#45/#50. 462 → 557 passed (+95). event loop 오염 해결, 인터페이스 불일치 수정, DB 테스트 integration 마킹.

### Step 4 — K3s 프로덕션 배포 (대부분 완료)

PR #38/#39/#41/#51. Helm chart + Kustomize + CI/CD(4단계 게이트) + Dockerfile multi-stage.

---

## 진행 중 마일스톤

### Step 4 — K3s 프로덕션 배포 (잔여)

#### 배포 전략: Helm(인프라) + Kustomize(앱) 병행

**인프라(Stateful) → Helm (Bitnami chart)**: PostgreSQL, Redis, MinIO
**앱(Stateless) → Kustomize (base + overlay)**: api, worker, ui
**배포 순서**: helm install → kubectl apply -k
**롤백**: 인프라 `helm rollback` / 앱 `git revert` → `kubectl apply -k`

**완료된 액션 아이템:**
1. ~~커스텀 StatefulSet 삭제 → Bitnami chart values 작성~~ — PR #63 완료 (Helm 레이어)
2. ~~`k8s/base/`에서 postgres/redis/minio 삭제~~ — PR #64 완료 (Kustomize 레이어)
3. ~~Kustomize overlays dev/prod 보강~~ — PR #64 완료 (storage, ingress TLS, UI 리소스 패치)
4. ~~configmap/secrets Bitnami 서비스명 정합~~ — PR #63/#64 완료

**남은 액션 아이템:**
1. `k8s/scripts/deploy.sh`를 Helm(인프라) → Kustomize(앱) 순서로 수정
2. K3s 클러스터 실배포 검증

#### K8s 로컬 환경: Colima

`colima start --kubernetes --cpu 4 --memory 8 --disk 40` (K3s v1.35.0, 구동 확인 완료)

---

### Phase 10 — 확장 통합 운영 (잔여)

SearchAgent 잠정 중단 상태. Step 4 완료 후 재개 검토.

### Phase 12 — 전략별 독립 포트폴리오 + 가상 트레이딩 (잔여)

Docker 환경 통합 테스트, 대시보드 UI, 백테스트 시뮬레이션 모드가 남아 있다.

---

## 다음 단계

### Step 7 — Airflow 비교 스파이크

> 브랜치: `feature/airflow-workflow-spike` (main에서 분기, main은 건드리지 않음)
> 목적: "Airflow를 직접 띄워서 DAG를 돌려봤다"고 면접에서 말할 수 있는 상태 만들기
> 범위: 장 전 수집 파이프라인 1개 DAG (5 태스크). 전체 마이그레이션 아님.

#### CTO/DevOps/DataEngineer 회의 결정 (2026-03-30)

**원칙:**
- 프로덕션 도입이 아님. 학습/비교 환경으로만 사용.
- `docker-compose.airflow.yml` 별도 파일로 분리. 메인 `docker-compose.yml`은 건드리지 않음.
- Alpha 소스(`src/`)를 DAG에서 읽기 전용 import. 코드 수정 없음.
- Alpha(`docker compose up`)와 Airflow(`docker compose -f docker-compose.airflow.yml up`)를 동시에 띄움.

**기술 결정:**
- Airflow 이미지: `apache/airflow:2.10-python3.11`
- Executor: `LocalExecutor` (1인 개발, Celery 불필요)
- 메타데이터 DB: 자체 postgres (기존 alpha_db와 분리, 충돌 방지)
- Alpha 소스 마운트: `./src:/opt/airflow/src:ro`, `./scripts:/opt/airflow/scripts:ro`
- DAG 폴더: `./dags:/opt/airflow/dags`
- 포트: Airflow webserver `8080` (기존 API `8000`과 충돌 없음)

**DAG 설계:**
```
pre_market_collection (08:10 KST, 월~금)
│
├── collect_stock_master
│       ↓
├── collect_macro ──────┐
│                        ├──→ collect_daily_bars
├── collect_index_warmup ┘
│       ↓
├── validate_collection (Alpha에 없는 품질 게이트 — Airflow 부가가치)
│       ↓
└── log_completion (XCom으로 수집 건수 전달)
```

- `retries=3, retry_delay=30s` — Alpha `job_wrapper.py`와 동일 패턴을 선언적으로
- `execution_timeout=10m` — Alpha TTL과 동일 개념을 SLA로
- `validate_collection` — 수집 건수 검증. "Airflow 도입 시 이런 걸 추가할 수 있다"는 증거

**실행 계획:**

| 단계 | 시간 | 산출물 |
|------|------|--------|
| 1. 환경 구축 | 30분 | `docker-compose.airflow.yml` + Airflow UI 접속 |
| 2. DAG 구현 | 45분 | `dags/pre_market_collection.py` (5 태스크) |
| 3. 실행 + 검증 | 15분 | DAG Graph View, Gantt Chart 스크린샷 |
| 4. 비교 기록 | 30분 | Obsidian `work/` 문서 + 면접 답변 |

**면접 답변:**
> "Alpha의 수집 파이프라인을 Airflow DAG로 이식해봤습니다. retry와 backfill이 선언적으로 되는 건 확실히 편했고, 실행 이력 UI는 압도적이었습니다. 하지만 30초 인터벌 실시간 수집은 Airflow가 지원하지 않아서, 배치 파이프라인만 선별 도입하고 실시간은 기존 구조를 유지하는 게 맞다고 판단했습니다."

---

### 제출 (3/30)
이력서 DE 언어 전환 → 제출

### Step 4 잔여 — K3s 실배포
1. deploy.sh Helm→Kustomize 순서 수정 — PR #68 완료
2. K3s 6 Pod Running 검증 완료 — PR #68

### Step 7 — 글로벌 데이터 레이크 확장

KR(2,772종목) + US(6,591종목) 전 종목의 FDR 최대 12년 일봉을 수집한다.

**배경 (2026-03-30 회의):**
기존 `market_data` 테이블은 KR 전용(int 가격, KST 고정, interval 혼재)으로 글로벌 확장에 부적합.
미장 추가, 실시간 분봉/틱 대응, 장기 데이터 축적을 위해 테이블을 재설계한다.

**신규 테이블 구조:**
1. `markets` — 시장 메타 (KOSPI/KOSDAQ/NYSE/NASDAQ, timezone, currency)
2. `instruments` — 종목 마스터 (글로벌 유니크 ID: 005930.KS, AAPL.US)
3. `ohlcv_daily` — 일봉 (NUMERIC(15,4) 가격, 연도별 파티셔닝 2010~2027)
4. (미래) `ohlcv_minute` — 분봉, `ticks` — 틱 (S3 전용)

**핵심 설계 결정:**
- 가격: `int` → `NUMERIC(15,4)` (KRW 정수 + USD 소수점 통합)
- instrument_id에 시장 접미사 (.KS, .KQ, .US) → 코드 충돌 방지
- 일봉/분봉/틱 테이블 분리 → 행 수 차이 1000배, 쿼리 패턴 다름
- ohlcv_daily 연도별 파티셔닝 → 오래된 데이터 DROP PARTITION으로 정리

**예상 규모:** ~9,363종목, ~2,800만 행, ~5GB (PostgreSQL)

### 보류
- SearchAgent (SearXNG 통합)

### 미정 — Hot/Cold 데이터 Lifecycle 자동화

현재 PostgreSQL과 S3에 동일 데이터가 이중 저장(dual write)되고 있으며, 수명 관리가 없어 양쪽 모두 무한히 쌓이는 구조.

**목표:**
- Hot (최근 N일): PostgreSQL에서 실시간 조회
- Cold (N일 이후): S3 Parquet에만 보존, PostgreSQL에서 삭제
- 배치 분석(RL 재학습, 백테스트)은 S3에서 직접 수행

**필요한 것:**
1. PostgreSQL → S3 이관 확인 후 오래된 행 삭제하는 스케줄 잡
2. 이관 대상: market_data(일봉/틱), predictions, trade_history
3. ohlcv_daily 연도별 파티셔닝 활용 → DROP PARTITION으로 정리
4. S3 Glacier 또는 lifecycle rule로 장기 보존 비용 절감

**시기:** 미정. 데이터 규모가 PostgreSQL 성능에 영향을 줄 때 착수.

### 미정 — 멀티 타임프레임 데이터 파이프라인 (KIS 실시간 + RL 학습 확장)

FDR 일봉 + KIS 분봉/틱을 통합하여 RL과 에이전트가 멀티 타임프레임으로 학습·추론할 수 있게 한다.

**배경 (2026-03-31 회의):**
현재 RL은 일봉(ohlcv_daily)만 학습에 사용한다. 장중 모멘텀(분봉), 체결 강도(틱)를 추가하면 state vector가 풍부해지고 전략 정밀도가 올라간다.

**저장 계층:**
```
PostgreSQL (쿼리용):
  ohlcv_daily    — 일봉 (이미 있음, FDR/KIS 장 마감 후 확정)
  ohlcv_minute   — 분봉 (신규, KIS REST, 장중 1분/5분, 월별 파티셔닝)
  tick_summary   — 틱 요약 (신규, 일별 VWAP/매수비율/스프레드)

Redis (실시간):
  latest_ticks      — 최신 체결가 TTL 60초 (이미 있음)
  realtime_series   — 최근 300틱 시계열 (이미 있음)

S3 Parquet (학습용 아카이브):
  daily/    — 일봉 (이미 있음)
  minute/   — 분봉 (신규)
  ticks/    — 틱 원본 (신규, PostgreSQL에 안 넣음)
  features/ — 전처리된 멀티 타임프레임 feature 벡터 (신규)
```

**RL state vector 확장:**
```
현재 (일봉만):
  [sma_5, sma_20, rsi, volatility, volume_ratio, returns_1d]

확장 (멀티 타임프레임):
  일봉: [sma_5, sma_20, rsi, volatility, volume_ratio]
  분봉: [vwap_deviation, intraday_momentum, volume_surge_5min]
  틱:   [buy_ratio, spread_pct, tick_intensity]
```

**구현 4단계:**

| 단계 | 내용 | 신규 파일 | 기존 수정 | 난이도 |
|------|------|-----------|-----------|--------|
| 1단계 | `ohlcv_minute` 테이블 + KIS 분봉 수집 | create_market_tables.py DDL, queries.py 함수, collector.py 메서드, scheduler 잡 | 없음 | 낮~중 |
| 2단계 | RL state vector에 분봉 feature 추가 | — | rl_dataset_builder_v2.py, rl_trading_v2.py | 중간 |
| 3단계 | `tick_summary` + S3 틱 아카이브 | datalake.py 함수, queries.py 함수 | 없음 | 낮음 |
| 4단계 | `features/` 전처리 파이프라인 | feature_builder.py (신규) | rl_dataset_builder_v2.py 연결 | 높음 |

**기존 API 수정: 0건.** 전부 신규 추가.

**용량 추정 (20종목, 연간):**
| 데이터 | PostgreSQL | S3 |
|--------|------------|-----|
| 분봉 (ohlcv_minute) | ~25MB/년 | ~5MB/년 |
| 틱 요약 (tick_summary) | ~1MB/년 | — |
| 틱 원본 | — | ~50GB/년 |
| feature 벡터 | — | ~1GB/년 |

**시기:** 미정. KIS 모의투자 안정화 후 1단계부터 순차 착수. 각 단계는 독립 배포 가능.
