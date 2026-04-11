# RL 종목 레지스트리 자동 동기화

status: open
created_at: 2026-04-11
topic_slug: rl-registry-auto-sync
related_files:
- src/schedulers/unified_scheduler.py
- src/agents/rl_continuous_improver.py
- src/agents/rl_policy_registry.py
- src/agents/rl_policy_store_v2.py
- scripts/rl_bootstrap.py
- scripts/run_orchestrator_worker.py
- src/agents/orchestrator.py
- src/db/queries.py
- artifacts/rl/models/registry.json

## 1. 핵심 질문

RL 학습 대상 종목을 어떻게 관리해야 종목 추가 시 수동 작업 없이 자동으로 학습이 시작되는가?

## 2. 배경

현재 RL 학습이 0건인 원인: `registry.json`에 종목이 등록되어 있지 않으면 학습 자체가 실행되지 않음.

종목 목록이 3곳에 분산되어 있고 자동 동기화가 없다:

| 컴포넌트 | 종목 소스 | 방식 |
|----------|----------|------|
| Orchestrator | `_DEFAULT_TICKERS` 하드코딩 / `ORCH_TICKERS` 환경변수 | 수동 |
| Strategy A/B | Orchestrator에서 전달받음 | 상속 |
| RL bootstrap/retrain | `registry.list_all_tickers()` | registry.json 의존 |
| RL bootstrap 스크립트 | `DEFAULT_TICKERS` 하드코딩 | 수동 |

추가 문제:
- ticker 정규화 불일치: `259960`(접미사 없음)과 `259960.KS`가 registry에 공존
- `instruments` 테이블에 `is_active` 플래그와 `list_tickers()` 쿼리가 이미 구현돼 있으나 Orchestrator/RL이 사용하지 않음

## 3. 제약 조건

- 종목 수 30개 미만의 소규모 프로젝트 — 과도한 설계 금지
- 코드에 종목 하드코딩 금지 — `_DEFAULT_TICKERS` 같은 패턴 전면 제거
- ticker 포맷은 `{종목}.{시장}` 형식 유지 (예: `005930.KS`, `EURUSD_TRUEFX`)
- RL approval gate 등 기존 안전장치는 유지
- registry.json의 학습 이력/정책 메타데이터 저장 역할은 유지

## 4. 선택지 비교

| 선택지 | 장점 | 단점 | 비용/복잡도 |
|--------|------|------|------------|
| A. DB 중심 (instruments SoT) | 기존 인프라 재활용, 변경 최소, 런타임 종목 추가 가능 | RL 메타데이터는 별도 저장 필요 | 낮음 |
| B. Config 파일 단일화 (YAML) | git 추적 가능 | 종목 추가마다 재배포 필요, 런타임 유연성 없음 | 낮음 |
| C. RL registry 자동 sync 레이어 | 기존 코드 변경 최소 | sync 실패 시 원점, 불필요한 간접층 추가 | 중간 |

## 5. 결정 사항

### 5.1 결정

**선택지 A: instruments 테이블을 종목 SoT로 채택** (하이브리드)

- **종목 발견**: 모든 컴포넌트가 `instruments` 테이블 (`is_active=True`)에서 종목을 읽음
- **학습 기록**: registry.json은 학습 이력/정책 메타데이터 저장소로 역할 축소
- **하드코딩 전면 제거**: `_DEFAULT_TICKERS`, `DEFAULT_TICKERS` 등 코드 내 종목 목록 삭제
- **override**: `ORCH_TICKERS` 환경변수가 설정된 경우에만 DB 대신 해당 값 사용 (비상용)

3축 평가:
- **확장성**: instruments 테이블에 INSERT 한 줄이면 전체 시스템이 자동 반영
- **안전**: RL approval gate가 잘못된 종목의 실거래 진입을 차단
- **관리 수월함**: 종목 추가/제거가 DB 한 곳에서 완결

### 5.2 트레이드오프

- DB에 잘못된 종목이 추가되면 RL이 의미 없는 학습을 시도함 (다만 approval gate가 active 승격을 차단하므로 실거래 영향 없음)
- DB 장애 시 종목 목록을 못 읽음 → `ORCH_TICKERS` 환경변수 override로 대응
- registry.json에 없는 종목이 DB에 추가되면 첫 bootstrap에서 빈 엔트리가 생성되고, 학습은 다음 retrain 사이클에서 시작 (최대 1일 지연)

## 6. 실행 계획

| 순서 | 항목 | 변경 대상 파일 | 완료 기준 |
|------|------|---------------|----------|
| 1 | Orchestrator 하드코딩 제거 → DB 조회 | `scripts/run_orchestrator_worker.py`, `src/agents/orchestrator.py` | `_DEFAULT_TICKERS` 삭제, `list_tickers()` 호출로 교체, `ORCH_TICKERS` 있으면 override |
| 2 | RL bootstrap 하드코딩 제거 → DB 조회 | `scripts/rl_bootstrap.py` | `DEFAULT_TICKERS` 삭제, `list_tickers()` 호출로 교체 |
| 3 | RL 스케줄러 자동 등록 | `src/schedulers/unified_scheduler.py` | `_run_rl_bootstrap()` 시작 시 instruments 조회 → registry에 없는 종목 자동 등록 |
| 4 | ticker 정규화 정리 | `artifacts/rl/models/registry.json` | 접미사 없는 `259960` 엔트리를 `259960.KS`로 병합 (정책 이력 보존) |
| 5 | bootstrap 로그 개선 | `src/schedulers/unified_scheduler.py` | `INFO: RL bootstrap: {n} tickers from instruments, {m} already in registry` 로그 추가 |
| 6 | 테스트 작성 | `test/` | 자동 등록 로직, fallback 체인, 정규화 검증 |

## 7. 참조

### 7.1 참고 파일

- `src/schedulers/unified_scheduler.py:121-171` — `_run_rl_bootstrap()` 현재 로직, registry에서만 종목 조회
- `src/schedulers/unified_scheduler.py:235-246` — `_run_rl_retrain()` 현재 로직
- `src/agents/rl_continuous_improver.py:253-255` — `list_target_tickers()`, registry 전용
- `scripts/run_orchestrator_worker.py:70` — `_DEFAULT_TICKERS` 하드코딩
- `scripts/rl_bootstrap.py:56` — `DEFAULT_TICKERS` 하드코딩
- `src/agents/orchestrator.py:828` — CLI 기본 종목 하드코딩
- `src/db/queries.py:151-162` — `list_tickers()` 함수, 이미 구현돼 있으나 미사용
- `src/api/routers/rl.py:661-700` — `PUT /rl/tickers` 수동 등록 엔드포인트
- `artifacts/rl/models/registry.json` — 현재 registry 상태 (4개 종목, 정규화 불일치)

### 7.2 참고 소스

없음.

### 7.3 영향받는 파일

- `scripts/run_orchestrator_worker.py` — 하드코딩 제거, DB 조회로 교체
- `src/agents/orchestrator.py` — CLI 기본값 하드코딩 제거
- `scripts/rl_bootstrap.py` — 하드코딩 제거, DB 조회로 교체
- `src/schedulers/unified_scheduler.py` — 자동 등록 로직 + 로그 추가
- `artifacts/rl/models/registry.json` — 정규화 정리

## 8. Archive Migration

> 구현 완료 후 아카이브 시 아래 내용을 `MEMORY-archive.md`에 기록한다.
> 200자(한글 기준) 이내, 배경지식 없이 이해 가능하게 작성.

```
(구현 완료 후 작성)
```

## 9. Closure Checklist

- [x] 구조/장기 방향 변경 → `.agent/roadmap.md` 반영
- [x] 이번 세션 할 일 → `progress.md` 반영
- [ ] 운영 규칙 → `MEMORY.md` 반영
- [ ] 섹션 8의 Archive Migration 초안 작성
- [ ] `/discussion --archive <이 파일>` 실행
