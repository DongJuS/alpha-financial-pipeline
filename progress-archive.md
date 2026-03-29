# 🗄️ progress-archive.md — 완료된 작업 이력

> **이 파일은 progress.md에서 분리된 아카이브입니다.**
> 활성 스프린트와 미완료 항목은 `progress.md`를 참조하세요.

---

## Step 3 — RL 부트스트랩 + 3전략 동시 블렌딩 (2026-03-29)

PR #32/#33/#34. 장 전(RL 학습) → 장 중(A/B/RL 블렌딩) → 장 후(재학습+가중치 조정) 운영 흐름 완성.
- `scripts/rl_bootstrap.py` — FDR 720일 시딩→학습→활성 정책 등록
- `orchestrator.py` — 3전략 병렬 실행 + graceful fallback
- `unified_scheduler.py` — 장 전/중/후 9개 잡 스케줄

## Step 5 — Alpha 안정화 + e2e 검증 (2026-03-29)

PR #48/#49/#51/#52/#53/#54.
- docker compose 8서비스 전부 healthy
- Collector → Orchestrator 1사이클 재현: 수집 24건 → 3전략 병렬 → 블렌딩 fallback → S3 Parquet 저장 (16초)
- LLM 미설정 시 graceful degradation 확인
- `docker-compose.yml` — `db-init` 서비스 추가, worker healthcheck 수정, worker `GEN_API_URL` 추가
- `CLAUDE.md` — e2e 테스트 기준 섹션 추가
- `.github/workflows/ci.yml` — DB init 스텝, helm-lint 잡 추가

## Step 6 — 테스트 스위트 완전 정비 (2026-03-29)

PR #44/#45/#50. 462 → 557 passed (+95건). 0 failed.
- event loop 오염 근본 해결: conftest.py deprecated `event_loop` fixture 제거
- `asyncio.run()` → `IsolatedAsyncioTestCase` + `await` 전환
- `strategy_promotion.py` shallow copy → deepcopy 버그 수정
- `test_search_pipeline.py` 전면 재작성
- DB 의존 테스트 3건 `@pytest.mark.integration` 마킹
- Python 3.11.15 환경 전환

## Step 4 — K3s 프로덕션 배포 (2026-03-29, 대부분 완료)

PR #38/#39/#41/#51. 잔여: K3s 실배포.
- `k8s/helm/alpha-trading/` — Helm chart 13개 파일
- `Dockerfile` — multi-stage (base/dev/prod), non-root user
- `.github/workflows/ci.yml` — lint → test → helm-lint → build 4단계
- `.github/workflows/deploy.yml` — SSH → helm upgrade
- `k8s/scripts/deploy.sh`, `k8s/scripts/teardown.sh`
- 모니터링 Prometheus + Grafana (PR #36)
- Helm chart lint/template 검증 + readiness 정합 (PR #42)

---

## Phase 12 — 블로그 자동 포스팅 (2026-03-28)

| 파일 | 내용 |
|------|------|
| `src/utils/blog_client.py` | BloggerClient (OAuth refresh, publish/update/find_by_title, BaseBlogClient Protocol) |
| `src/utils/discussion_renderer.py` | MD→HTML 변환, 프론트매터 파싱, 프로젝트 컨텍스트 헤더 삽입 |
| `scripts/post_discussion_to_blog.py` | CLI `--draft`/`--dry-run`, 중복 감지 후 업데이트 |
| `scripts/setup_blogger_oauth.py` | 로컬 HTTP 서버 OAuth 콜백, `.env` 자동 기록 |

---

## Phase 11 — N-way 블렌딩 + StrategyRunner Registry (2026-03-16)

- `src/agents/strategy_runner.py` — StrategyRunner Protocol + StrategyRegistry
- `src/agents/blending.py` — BlendInput + blend_signals() N-way 일반화
- N+1 쿼리 배치 최적화 (executemany): 2,400 RTT → 1 RTT

---

## Phase 10 — 피드백 루프 파이프라인 (2026-03-16)

- S3 Parquet 읽기, predictions+outcomes 매칭, 오류 패턴 분석, RL 재학습 파이프라인

---

## Phase 9 — RL Trading Lane (2026-03-15)

- RL V2 (상태공간 1350개, 4-action, 멀티시드), Gymnasium TradingEnv, walk-forward, shadow inference

---

## Phase 8 — Search Foundation (2026-03-15)

- SearXNG → Claude 감성 분석, SearchRunner, ResearchPortfolioManager

---

## Phase 7 — S3 Data Lake (2026-03-15)

- MinIO + Parquet, 7 DataType, Hive 파티셔닝

---

## Phase 6 — 독립 포트폴리오 인프라 (2026-03-15)

- VirtualBroker, 전략 승격, 합산 리스크

---

## Phase 1~5 — 인프라·에이전트·전략·UI (2026-03-12~13)

인프라 → 코어 에이전트 → Strategy A/B → 대시보드 → 운용 검증
