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

- [x] **Step 3: RL 부트스트랩 + 3전략 동시 블렌딩** — PR #32/#33/#34로 완료 (2026-03-29)
  - RL 부트스트랩 파이프라인 (`scripts/rl_bootstrap.py`) — FDR 720일 시딩→학습→활성 정책 등록
  - A/B/RL 3전략 동시 블렌딩 + graceful fallback (`orchestrator.py`)
  - 장 전/중/후 운영 흐름 스케줄 (`unified_scheduler.py`)
- [ ] **Step 4: K3s 프로덕션 배포** — Helm chart, 자동 복구, 롤링 업데이트, 실거래 전환 체크리스트
- [ ] **SearchAgent 잠정 중단** — SearXNG 로컬 검색 엔진 통합 + 모델 호환성 테스트 보류. Step 4 완료 후 재개 검토
- [ ] **LLM 프로바이더 Docker 내 실패 해결** — Claude CLI / Gemini OAuth가 Docker 내에서 동작하지 않음
- [ ] **RL 에피소드 S3 저장 구현** — `DataType.RL_EPISODES` enum만 존재, 저장 함수 미구현

---

## ⚠️ 미해결 구조적 이슈

- ~~**RLRunner 활성 정책 없으면 0건 반환**~~ → 2026-03-29 해결: `scripts/rl_bootstrap.py`로 FDR 720일 데이터 시딩→학습→활성 정책 등록. 장 시작 전 스케줄러가 자동 실행. 활성 정책 없을 때 2전략(A/B) 블렌딩으로 graceful fallback

---

*Last updated: 2026-03-29*
