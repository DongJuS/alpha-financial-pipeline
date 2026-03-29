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
- **Step 5 완료**: Alpha 안정화 (e2e 검증, smoke test, README, Airflow 비교 문서)
- **Step 6 완료**: 테스트 557 passed, 0 failed
- **다음 목표**: 제출(3/30) → 모니터링 → K3s 실배포

---

## 완료된 마일스톤

### Step 3 — RL 부트스트랩 + 3전략 동시 블렌딩 ✅

PR #32/#33/#34. 장 전(학습) → 장 중(블렌딩) → 장 후(재학습) 운영 흐름 완성.

### Step 5 — Alpha 안정화 + 제출 준비 ✅

PR #48/#49/#51/#52/#54. docker compose 클린 기동 → 8서비스 healthy → smoke test 통과 → gen 모드 주말 1사이클 완주 → README 정량 지표 → Airflow 비교 문서.

### Step 6 — 테스트 스위트 완전 정비 ✅

PR #45/#50. 462 → 557 passed (+95). event loop 오염 해결, 인터페이스 불일치 수정, deepcopy 버그 수정.

### Step 4 — K3s 프로덕션 배포 (대부분 완료)

PR #38/#39/#51. Helm chart + CI/CD(4단계 게이트) + Dockerfile multi-stage.

---

## 진행 중 마일스톤

### Phase 10 — 확장 통합 운영 (잔여)

SearchAgent 잠정 중단 상태. Step 4 완료 후 재개 검토.

### Phase 12 — 전략별 독립 포트폴리오 + 가상 트레이딩 (잔여)

Docker 환경 통합 테스트, 대시보드 UI, 백테스트 시뮬레이션 모드가 남아 있다.

---

## 다음 단계

### 제출 (3/30)
이력서 DE 언어 전환 → 제출

### Step 4 잔여 — 모니터링 + K3s 실배포
1. 모니터링: Prometheus scrape config + Grafana 대시보드
2. K3s 클러스터 구축 + Helm 실배포 검증

### 보류
- SearchAgent (SearXNG 통합)
- RL 에피소드 S3 저장
