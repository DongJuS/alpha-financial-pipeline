# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
기존 Strategy A/B 기반 자동 투자 시스템을 유지한 채, RL Trading과 Search/Scraping pipeline을 어떤 순서로 편입할지 정리합니다.
이 파일은 마일스톤 수준의 방향과 원칙만 작성합니다. 구체적인 체크리스트, 서브태스크, 이슈 등은 progress.md를 참조합니다.
완료된 이력은 roadmap-archive.md를 참조하세요.

---

## 현재 상태 (2026-03-29)

- **코어 트레이딩**: Phase 1~13 구현 완료, 유지보수 단계
- **Step 3 완료**: RL 부트스트랩 + 3전략 동시 블렌딩 (PR #32/#33/#34)
- **Step 4 진행 중**: K3s 프로덕션 배포 — Colima + K3s 구동 완료, 배포 전략 확정, 실배포만 남음
- **테스트 정비 완료**: 557 passed, 0 failed (PR #44/#45/#50)
- **문서 정비 완료**: README 정량 지표 + Airflow 비교 문서 (PR #53)
- **smoke test 통과**: DB/Redis/API/FDR 전체 정상 (2026-03-29)

---

## 완료된 마일스톤

### Step 3 — RL 부트스트랩 + 3전략 동시 블렌딩 ✅

3개 전략(A/B/RL)이 동일한 모드에서 동작한다는 핵심 원칙 달성.

**구현 완료:**
1. **장 시작 전:** `scripts/rl_bootstrap.py`로 FDR 720일 데이터 시딩→학습→활성 정책 등록. 스케줄러가 08:00에 자동 실행.
2. **장 시간:** `orchestrator.py`에서 A/B/RL 3전략 병렬 실행 + N-way 블렌딩. RL 활성 정책 없으면 A/B 2전략으로 graceful fallback.
3. **장 마감 후:** `unified_scheduler.py`에서 RL 재학습 + 블렌딩 가중치 동적 조정 스케줄 실행.

---

## 진행 중 마일스톤

### Step 4 — K3s 프로덕션 배포

#### 배포 전략: Helm(인프라) + Kustomize(앱) 병행

CTO/DevOps/DataEngineer 회의(2026-03-29)에서 결정한 원칙:

**인프라(Stateful, 남이 만든 것) → Helm (Bitnami chart)**
- PostgreSQL: 자동 백업, HA, 버전 업그레이드가 검증된 Bitnami chart 사용
- Redis: sentinel, persistence 설정 내장
- MinIO: 버킷 정책, TLS 설정 내장
- 이유: 실거래 시스템이므로 데이터 유실이 가장 위험. DB/캐시/스토리지는 커뮤니티가 검증한 Helm chart가 직접 작성한 YAML보다 안전하다.

**앱(Stateless, 내가 만든 것) → Kustomize (base + overlay)**
- api, worker, ui
- dev/prod 환경 분리는 Kustomize overlay로 처리
- 이유: 자주 바뀌는 앱 코드에 Helm 템플릿 문법(`{{ .Values.x }}`)은 과잉. 순수 YAML + 패치가 빠르고 직관적.

**배포 순서:**
1. `helm install` — 인프라(PostgreSQL, Redis, MinIO) 먼저
2. `kubectl apply -k` — 앱(api, worker, ui) 나중에

**롤백:**
- 인프라: `helm rollback` 한 줄
- 앱: `git revert` → `kubectl apply -k`

**완료:**
- README 정량 지표 섹션 추가 + Airflow 비교 문서 신규 작성 (PR #53)
- README 빠른 시작 minio 누락 수정 (PR #53)
- smoke test 전체 통과: DB/Redis/FastAPI/FDR (2026-03-29)
- 테스트 스위트 완전 정비: 462→557 passed, 47→0 failed (PR #44/#45/#50)
  - event loop 오염 근본 해결 (conftest.py deprecated fixture 제거)
  - `asyncio.run()` → `IsolatedAsyncioTestCase` 전환 (5개 파일)
  - SearchAgent 인터페이스 변경 반영 (test_search_pipeline.py 재작성)
  - DB 의존 테스트 `@pytest.mark.integration` 마킹

**남은 액션 아이템:**
1. `k8s/base/`에서 postgres.yaml, redis.yaml, minio.yaml 삭제 (Bitnami chart로 교체)
2. Bitnami Helm repo 추가 + 인프라 설치 스크립트 작성
3. Kustomize base는 앱(api, worker, ui)만 유지
4. `k8s/scripts/deploy.sh`를 Helm → Kustomize 순서로 수정

#### K8s 로컬 환경: Colima

macOS에서 K3s를 실행하기 위해 Colima를 선택(2026-03-29).

- 27.5k GitHub stars, 무료 오픈소스
- K3s 내장 → 프로덕션 K3s와 호환
- Docker runtime 포함 → `docker build` 그대로 사용
- Apple Silicon 네이티브 성능 92%, 메모리 400MB
- Minikube(무겁고 K3s와 다른 런타임), OrbStack(유료 $8/mo) 대비 1인 개발에 최적

현재 구동 중: `colima start --kubernetes --cpu 4 --memory 8 --disk 40`

---

### Phase 10 — 확장 통합 운영 (잔여)

Search 추출 결과를 Strategy B prompt와 RL feature에 연결하는 작업이 남아 있다.
SearchAgent는 잠정 중단 상태 (Step 4 완료 후 재개 검토).

### Phase 12 — 전략별 독립 포트폴리오 + 가상 트레이딩 (잔여)

Docker 환경 통합 테스트, 대시보드 UI, 백테스트 시뮬레이션 모드가 남아 있다.
