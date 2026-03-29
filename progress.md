# 📝 progress.md — 현재 세션 진척도

> 에이전트와 "현재 어디까지 했는지" 맞추는 단기 기억 파일입니다.
> 완료된 이력은 `progress-archive.md`를 참조하세요.
> **정리 정책**: 150줄 초과 시 완료+코드 유추 가능 항목 삭제. 200줄 초과 시 오래된 완료 항목 강제 삭제.

---

## 📊 Phase 진행 현황

```
Phase 1  인프라 기반 구축        ██████████  100% ✅
Phase 2  코어 에이전트           ██████████  100% ✅
Phase 3  Strategy A Tournament  ██████████  100% ✅
Phase 4  Strategy B Consensus   ██████████  100% ✅
Phase 5  대시보드 + 운용 검증    ██████████  100% ✅
Phase 6  독립 포트폴리오 인프라  ██████████  100% ✅
Phase 7  S3 Data Lake (MinIO)   ██████████  100% ✅
Phase 8  Search Foundation      ██████████  100% ✅
Phase 9  RL Trading Lane        ██████████  100% ✅
Phase 10 피드백 루프 파이프라인  ██████████  100% ✅
Phase 11 N-way 블렌딩 + Registry ██████████  100% ✅
Phase 12 블로그 자동 포스팅      ██████████  100% ✅
Step 3   RL 부트스트랩 + 블렌딩  ██████████  100% ✅
Step 4   K3s 프로덕션 배포       ████████░░   80% 🔧
테스트   스위트 정비             ██████████  100% ✅
```

---

## 🔄 미완료 / 진행 중

### Step 5: Alpha 안정화 + 제출 준비 (🔴 최우선, 3/30 마감)
- [ ] `docker compose up -d --build` 전체 서비스 기동 확인
- [ ] API / UI / worker 기본 헬스체크 통과
- [ ] Collector → Orchestrator 1사이클 재현 + 로그/스크린샷 캡처
- [x] smoke test 통과 (`python3.11 scripts/smoke_test.py --skip-telegram`) — DB/Redis/API/FDR 전체 ✅
- [x] README 정량 지표 추가 — PR #53
- [x] Airflow 비교 문서 작성 (`docs/airflow-comparison.md`) — PR #53
- [ ] 이력서 DE 언어 전환 (Obsidian Phase4-합격전략.md 번역 매핑표 참조)
- [ ] 제출

### Step 4: K3s 프로덕션 배포

#### 완료된 항목

| 항목 | PR | 상태 |
|------|-----|------|
| Helm Chart (k8s/helm/) | #38 | ✅ |
| Kustomize 매니페스트 (k8s/base + overlays) | #41 | ✅ |
| CI/CD + Dockerfile 프로덕션화 | #36 | ✅ |
| 모니터링 (Prometheus + Grafana) | #36 | ✅ |
| LLM Docker 인증 (Claude CLI + Gemini OAuth) | #25 | ✅ |
| RL 에피소드 S3 저장 (store_rl_episodes) | #37 | ✅ |
| K8s readiness 체크 + Helm 정합 | #42 | ✅ |
| 런타임 검증 (S3 round-trip, 스케줄러 TTL) | #43 | ✅ |
| Colima + K3s 설치 | — | ✅ |
| README 정량 지표 + Airflow 비교 문서 | #53 | ✅ |
| 테스트 스위트 완전 정비 (557 passed, 0 failed) | #44/#45/#50 | ✅ |

#### 남은 액션 아이템

- [ ] `k8s/base/`에서 postgres.yaml, redis.yaml, minio.yaml **삭제** (Bitnami chart로 교체)
- [ ] Bitnami Helm repo 추가 + 인프라 설치 스크립트 작성
- [ ] `k8s/scripts/deploy.sh`를 Helm → Kustomize 순서로 수정
- [ ] 실제 배포 실행 (`helm install` → `kubectl apply -k`)
- [ ] 실거래 전환 체크리스트 통과

### 보류

- [ ] **SearchAgent** — SearXNG 통합 보류. Step 4 완료 후 재개 검토

---

*Last updated: 2026-03-29*
