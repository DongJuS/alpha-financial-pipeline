# LangGraph + APScheduler vs Airflow — 비교 분석

> **목적:** 현재 Alpha 시스템의 스케줄링/오케스트레이션 아키텍처를 Airflow와 비교하여,
> 전체 마이그레이션이 아닌 "비교 스파이크"로 접근하는 이유를 문서화한다.

---

## 왜 전체 마이그레이션이 아니라 비교 스파이크인가

Alpha는 **실시간 트레이딩 시스템**이다. Airflow는 배치 ETL/ML 파이프라인에 최적화되어 있고,
장중 30초 간격 실시간 수집이나 이벤트 드리븐 블렌딩 같은 패턴에는 부적합하다.

현재 시스템은 APScheduler + Redis 분산락 + LangGraph 상태 기계로 충분히 동작하며,
Airflow 도입 시 오히려 복잡도가 증가한다. 따라서 전면 교체가 아닌,
**Airflow가 제공하는 기능 중 Alpha에 부족한 부분만 선별 도입**하는 전략을 취한다.

### Airflow가 우위인 영역 (도입 검토 대상)

- **실행 이력 UI**: Airflow는 태스크별 실행 시각, 소요 시간, 로그를 웹 UI로 제공. Alpha는 Redis 리스트(50건)로 제한적.
- **Backfill CLI**: `airflow dags backfill --start-date` 한 줄로 과거 날짜 재실행. Alpha는 수동 스크립트.
- **DAG 시각화**: 태스크 의존 관계를 시각적으로 파악 가능. Alpha는 코드 레벨에서만 추적.

### Alpha가 우위인 영역 (마이그레이션 불필요)

- **실시간 스케줄링**: 30초 인터벌, 밀리초 단위 misfire grace — Airflow 최소 스케줄 간격은 1분.
- **이벤트 드리븐**: Redis Pub/Sub 기반 에이전트 간 비동기 통신. Airflow는 폴링 기반.
- **경량 배포**: 단일 Python 프로세스. Airflow는 Scheduler + Webserver + Worker + DB 최소 4컴포넌트.
- **상태 기계**: LangGraph StateGraph로 전략 간 복잡한 흐름 제어. Airflow DAG는 단방향.

---

## 기능 비교표

| 기능 | Alpha (현재) | Airflow |
|------|-------------|---------|
| **스케줄러** | APScheduler `AsyncIOScheduler` (in-process) | 독립 Scheduler 프로세스 + Executor |
| **스케줄 정의** | `scheduler.add_job(fn, CronTrigger(...))` | `@dag` + `@task` 데코레이터 |
| **최소 간격** | 밀리초 (인터벌 30s 운용 중) | 1분 (권장 5분+) |
| **재시도** | `with_retry()` — 3회, 지수 백오프 | `retries=3`, `retry_delay=timedelta(...)` |
| **분산 락** | Redis `SET NX EX` + Lua 릴리스 | ZooKeeper / DB 락 (HA Scheduler) |
| **Backfill** | 수동 스크립트 (CollectorAgent 720일 시드) | `airflow dags backfill` CLI |
| **실행 이력** | Redis 리스트 (`scheduler:history:{job_id}`, 50건) | PostgreSQL `task_instance` 테이블 (무제한) |
| **이력 UI** | 없음 (로그 + Redis CLI) | 내장 웹 UI (Gantt, Tree, Graph View) |
| **병렬 실행** | `asyncio.gather()` (StrategyRegistry) | CeleryExecutor / KubernetesExecutor |
| **상태 기계** | LangGraph StateGraph (양방향 전이) | DAG (단방향 비순환) |
| **이벤트 드리븐** | Redis Pub/Sub | Sensor (폴링) 또는 외부 트리거 |
| **헬스 모니터링** | Redis heartbeat (TTL 90s) | Worker heartbeat → metadata DB |
| **동적 설정** | `Config` 클래스 + Redis 캐시 | `Variable` + `Connection` |
| **배포 복잡도** | 단일 프로세스 (worker 컨테이너) | Scheduler + Webserver + Worker + DB (최소 4개) |
| **의존성** | APScheduler, Redis | Airflow 패키지 (100+ 의존성) |

---

## Alpha 구현체 ↔ Airflow 개념 매핑

| Alpha 구현체 | 파일 | Airflow 대응 개념 |
|-------------|------|-------------------|
| `unified_scheduler` | `src/schedulers/unified_scheduler.py` | **Scheduler** — 전체 잡 등록/트리거 |
| `job_wrapper.with_retry()` | `src/schedulers/job_wrapper.py` | **Task retry** — `retries` + `retry_delay` |
| `DistributedLock` | `src/schedulers/distributed_lock.py` | **HA Scheduler lock** — 중복 실행 방지 |
| `StrategyRegistry.run_all()` | `src/agents/strategy_runner.py` | **TaskGroup** — 병렬 태스크 그룹 |
| `OrchestratorAgent.run_cycle()` | `src/agents/orchestrator.py` | **DAG run** — 1회 파이프라인 실행 |
| `blend_signals()` | `src/agents/blending.py` | **downstream task** — 상위 태스크 결과 집계 |
| `BlendWeightOptimizer` | `src/utils/blend_weight_optimizer.py` | **Variable** — 런타임 동적 설정 |
| Redis `scheduler:history:*` | `src/schedulers/job_wrapper.py` | **XCom + task_instance** — 실행 이력/메타 |
| `run_orchestrator_worker.py` | `scripts/run_orchestrator_worker.py` | **Celery Worker** — 태스크 실행기 |

---

## 9개 스케줄 잡 → Airflow DAG 매핑

| # | Job ID | 시간 (KST) | Alpha 구현 | Airflow DAG 구성 시 |
|---|--------|-----------|-----------|-------------------|
| 1 | `rl_bootstrap` | 08:00 월~금 | CronTrigger, 락 TTL 30분 | `@daily` pre-market DAG, Task 1 |
| 2 | `predictor_warmup` | 08:05 월~금 | CronTrigger, 락 TTL 3분 | 같은 DAG, Task 2 (depends on #1) |
| 3 | `stock_master_daily` | 08:10 월~금 | CronTrigger, 락 TTL 5분 | 같은 DAG, Task 3 (parallel with #2) |
| 4 | `macro_daily` | 08:20 월~금 | CronTrigger, 락 TTL 5분 | 같은 DAG, Task 4 |
| 5 | `collector_daily` | 08:30 월~금 | CronTrigger, 락 TTL 10분 | 같은 DAG, Task 5 (depends on #3,#4) |
| 6 | `index_warmup` | 08:55 월~금 | CronTrigger, 락 TTL 1분 | 같은 DAG, Task 6 |
| 7 | `index_collection` | 30초 간격 | IntervalTrigger, 락 TTL 25초 | **별도 DAG** — Airflow 부적합 (Sensor 대체) |
| 8 | `rl_retrain` | 16:00 월~금 | CronTrigger, 락 TTL 60분 | post-market DAG, Task 1 |
| 9 | `blend_weight_adjust` | 16:30 월~금 | CronTrigger, 락 TTL 2분 | 같은 DAG, Task 2 (depends on #8) |

> **핵심 문제점:** Job #7 `index_collection`은 30초 인터벌로 동작하며, Airflow의 최소 스케줄 간격(1분)보다 짧다.
> Airflow로 마이그레이션 시 이 잡은 Sensor나 외부 프로세스로 분리해야 한다.

---

## 결론 및 권장 사항

### 현재 아키텍처 유지 (권장)

Alpha의 스케줄링 요구사항(실시간 30초 인터벌, 이벤트 드리븐, 경량 배포)은
APScheduler + Redis 분산락 조합이 Airflow보다 적합하다.

### 선별 도입 검토 항목

1. **실행 이력 영속화**: Redis 리스트(50건) → PostgreSQL 테이블로 확장 검토
2. **실행 이력 UI**: React 대시보드에 스케줄 잡 실행 현황 페이지 추가 검토
3. **Backfill CLI**: `scripts/backfill.py --date YYYY-MM-DD` 유틸리티 작성 검토

*Last updated: 2026-03-29*
