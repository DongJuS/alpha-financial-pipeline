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

### 제출 (3/30)
이력서 DE 언어 전환 → 제출

### Step 4 잔여 — K3s 실배포
1. Bitnami 인프라 설치 스크립트 + deploy.sh 수정
2. K3s 클러스터 실배포 검증

### 보류
- SearchAgent (SearXNG 통합)
