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
```

---

## 🔄 미완료 / 진행 중

### Step 5: Alpha 안정화 + 제출 준비 (🔴 최우선, 3/30 마감)
- [ ] `docker compose up -d --build` 전체 서비스 기동 확인
- [ ] API / UI / worker 기본 헬스체크 통과
- [ ] Collector → Orchestrator 1사이클 재현 + 로그/스크린샷 캡처
- [ ] smoke test 통과 (`python3.11 scripts/smoke_test.py --skip-telegram`)
- [ ] README 정량 지표 추가: 512 tests, 9 scheduled jobs, 720일 백필, 3전략 블렌딩
- [ ] Airflow 비교 문서 작성 (`docs/airflow-comparison.md`) — LangGraph vs Airflow 비교표 + "왜 스파이크인가"
- [ ] 이력서 DE 언어 전환 (Obsidian Phase4-합격전략.md 번역 매핑표 참조)
- [ ] 제출

### Step 4: K3s 프로덕션 배포 (잔여)
- [x] Helm chart 기본 구조 (PR #38)
- [ ] CI/CD 파이프라인 (`.github/workflows/`)
- [ ] Dockerfile multi-stage 프로덕션 빌드
- [ ] 모니터링 (Prometheus + Grafana)
- [ ] Helm chart 실배포 검증 (K3s 클러스터 필요)

### Step 6: 테스트 스위트 완전 정비
- [x] Python 3.9 문법 호환 — `from __future__ import annotations` 4개 파일 (PR #45)
- [x] 인터페이스 불일치 17건 수정 (PR #45)
- [x] conftest.py 환경변수 자동 주입 (PR #45)
- [x] strategy_promotion deepcopy 버그 수정 (PR #45)
- [ ] event loop 오염 32건 — `asyncio.run()` → `IsolatedAsyncioTestCase` 전환
- [ ] DB 미연결 3건 — `@pytest.mark.integration` 마킹
- [ ] llm_docker 3건 — Docker 내 LLM 인증 경로 수정

### 보류
- [ ] SearchAgent — Step 4 완료 후 재개
- [ ] RL 에피소드 S3 저장 — `store_rl_episodes()` 구현
- [ ] LLM 프로바이더 Docker 실패 — Claude CLI / Gemini OAuth 컨테이너 인증

---

## ⚠️ 미해결 구조적 이슈

- **테스트 event loop 오염** — `asyncio.run()`이 loop를 파괴하여 전체 실행 시 32건 실패. 독립 실행 시 전부 통과. `troubleshooting/test-suite-event-loop-pollution.md` 참조

---

*Last updated: 2026-03-29*
