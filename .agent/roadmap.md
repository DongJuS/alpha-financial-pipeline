# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
기존 Strategy A/B 기반 자동 투자 시스템을 유지한 채, RL Trading과 Search/Scraping pipeline을 어떤 순서로 편입할지 정리합니다.
이 파일은 마일스톤 수준의 방향과 원칙만 작성합니다. 구체적인 체크리스트, 서브태스크, 이슈 등은 progress.md를 참조합니다.
완료된 이력은 roadmap-archive.md를 참조하세요.

---

## 현재 상태 (2026-03-29)

- **코어 트레이딩**: Phase 1~13 구현 완료, 유지보수 단계
- **Step 3 완료**: RL 부트스트랩 + 3전략 동시 블렌딩 (PR #32/#33/#34)
- **다음 목표**: Step 4 (K3s 프로덕션 배포)

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

### Phase 10 — 확장 통합 운영 (잔여)

Search 추출 결과를 Strategy B prompt와 RL feature에 연결하는 작업이 남아 있다.
SearchAgent는 잠정 중단 상태 (Step 4 완료 후 재개 검토).

### Phase 12 — 전략별 독립 포트폴리오 + 가상 트레이딩 (잔여)

Docker 환경 통합 테스트, 대시보드 UI, 백테스트 시뮬레이션 모드가 남아 있다.

---

## 다음 단계

### Step 4 — K3s 프로덕션 배포

경량 Kubernetes(K3s) 클러스터에 전체 시스템을 배포한다.
자동 복구, 롤링 업데이트, 리소스 관리를 갖춘 운영 환경을 구성한다.
실거래 전환 체크리스트를 완료한 후 배포를 승격한다.
