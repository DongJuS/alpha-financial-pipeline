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

- [ ] **SearXNG 로컬 검색 엔진 통합** — SearchAgent가 외부 검색 API 없이 자체 SearXNG 인스턴스 사용
- [ ] **SearchAgent 모델 호환성 테스트** — `model_used` 필드로 추적, 일부 LLM 모델에서 지원 안 될 수 있음
- [x] **Claude Docker bind mount 적용 + Gemini API key 제거 (OAuth 유지)** — Claude: `${HOME}/.claude:/root/.claude:ro` bind mount, Gemini: API key 모드 제거, OAuth(gcloud ADC) 모드만 유지
- [ ] **LLM 프로바이더 Docker 내 실패 해결** — Claude CLI / Gemini OAuth가 Docker 내에서 동작하지 않음. `docker compose logs worker` 확인 필요
- [ ] **프로덕션 환경 배포 및 모니터링** — 전략 실거래 전환 체크리스트 완료 후 배포
- [ ] **블렌딩 가중치 최적화** — 현재 A:0.3/B:0.3/S:0.2/RL:0.2 고정, 성과 기반 동적 조정 검토
- [ ] **QA 잔여 이슈 (C3, H1~H4, M1~M4)** — 코드 리뷰 체크리스트 미처리 항목
- [ ] **RL 에피소드 S3 저장 구현** — `DataType.RL_EPISODES` enum만 존재, 저장 함수 미구현

---

## ⚠️ 미해결 구조적 이슈

- **스케줄러가 IndexCollector만 가동** — `main.py` lifespan에서 `start_index_scheduler()`만 호출. 일봉/매크로/종목마스터 수집은 수동 CLI 실행에 의존
- **RLRunner 활성 정책 없으면 0건 반환** — 학습→정책 활성화 파이프라인 미실행 시 Strategy RL은 항상 빈 시그널. 운영 시작 전 활성 정책 등록 필요

---

*Last updated: 2026-03-29*
