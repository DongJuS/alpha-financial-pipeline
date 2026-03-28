# 🗄️ progress-archive.md — 완료된 작업 이력

> **이 파일은 progress.md에서 분리된 아카이브입니다.**
> 활성 스프린트와 미완료 항목은 `progress.md`를 참조하세요.

---

## Phase 12 — 블로그 자동 포스팅 (2026-03-28)

| 파일 | 내용 |
|------|------|
| `src/utils/blog_client.py` | BloggerClient (OAuth refresh, publish/update/find_by_title, BaseBlogClient Protocol) |
| `src/utils/discussion_renderer.py` | MD→HTML 변환, 프론트매터 파싱, 프로젝트 컨텍스트 헤더 삽입 |
| `scripts/post_discussion_to_blog.py` | CLI `--draft`/`--dry-run`, 중복 감지 후 업데이트 |
| `scripts/setup_blogger_oauth.py` | 로컬 HTTP 서버 OAuth 콜백, `.env` 자동 기록 |
| `skills/post-discussion/SKILL.md` | `/post-discussion` 슬래시 커맨드 스킬 |
| `.claude/hooks/post-discussion-to-blog.sh` | PostToolUse 훅 (discussions/*.md Write/Edit → draft 자동 포스팅) |
| `.claude/settings.local.json` | PostToolUse 훅 설정 추가 |
| `test/unit/test_blog_client.py` | 11개 테스트 (토큰 갱신, 401 재시도, draft 모드) |
| `test/unit/test_discussion_renderer.py` | 14개 테스트 (프론트매터, HTML, 컨텍스트 삽입) |
| `.env.example` | BLOGGER_* 4개 변수 추가 |
| `src/utils/config.py` | Settings에 Blogger 필드 4개 추가 |
| `.agent/tech_stack.md` | `markdown` 패키지 승인 |
| `requirements.txt` | `markdown>=3.6,<4.0` 추가 |
| `MEMORY.md` | 291줄 → 87줄 축약 (활성 규칙만 유지) |
| `MEMORY-archive.md` | 신규 생성 — Phase 1~11 기술적 결정 이력 전체 보존 |
| `CLAUDE.md` | MEMORY-archive.md 참조, 블로그 규칙, skills/ 디렉터리 반영 |
| `architecture.md` | 블로그 포스팅 파이프라인 + 아카이브 시스템 섹션 추가 |

완료된 논의 문서 (Blogger에 포스팅 후 삭제):
- `20260314-rl-experiment-management.md`
- `20260314-searxng-pipeline.md`
- `20260314-strategy-ab-rl-extension.md`
- `20260315-independent-portfolio-per-strategy.md`
- `20260315-marketplace-sector-expansion.md`

---

## Phase 11 — N-way 블렌딩 + StrategyRunner Registry (2026-03-16)

- `src/agents/strategy_runner.py` — StrategyRunner Protocol + StrategyRegistry
- `src/agents/blending.py` — BlendInput + blend_signals() N-way 일반화
- `src/agents/orchestrator.py` — Registry 기반 병렬 실행 + --strategies CLI
- `src/agents/rl_trading_v2.py` — map_v2_action_to_signal + normalize_q_confidence
- `src/db/models.py` — strategy S/L 추가, is_shadow, blend_meta
- `scripts/db/init_db.py` — is_shadow, blend_meta JSONB, strategy CHECK 확장
- `src/utils/config.py` — strategy_blend_weights (A:0.3/B:0.3/S:0.2/RL:0.2)
- `test/test_blend_nway.py` — 통합 테스트 전체 통과
- N+1 쿼리 배치 최적화 (executemany): db_client.py, queries.py, marketplace_queries.py, collector.py
- Copilot 리뷰 코드 품질 수정: risk_summary.warnings, StrategyPromoter 파라미터, readiness.ready 필드명

---

## Phase 10 — 피드백 루프 파이프라인 (2026-03-16)

- `src/services/datalake_reader.py` — S3 Parquet 읽기, predictions+outcomes 매칭
- `src/services/llm_feedback.py` — 오류 패턴 분석 5가지, Redis 캐시
- `src/services/rl_retrain_pipeline.py` — S3 daily_bars→RL 재학습→walk-forward→자동 배포
- `src/services/backtest_engine.py` — 시그널 기반 가상 포트폴리오 시뮬레이션
- `src/services/feedback_orchestrator.py` — 일일 배치 통합 실행
- `src/api/routers/feedback.py` — REST API 7개 엔드포인트
- `test/test_feedback_pipeline.py` — 7개 클래스 20+ 테스트

---

## Phase 9 — RL Trading Lane (2026-03-15)

- `src/agents/rl_dataset_builder_v2.py` — SMA/RSI/변동성/매크로 컨텍스트 확장 데이터셋
- `src/agents/rl_environment.py` — Gymnasium 호환 TradingEnv, 4-action
- `src/agents/rl_walk_forward.py` — N-fold expanding/sliding 교차검증
- `src/agents/rl_shadow_inference.py` — ShadowInferenceEngine + 승격 게이트 2종
- `src/api/routers/rl.py` — 17개 REST 엔드포인트
- `test/test_phase9_rl.py` — 통합 테스트 5개 클래스
- RL 모델 관리: RLPolicyStoreV2, PolicyRegistry, 알고리즘 네임스페이스
- RL 실험 관리: RLExperimentManager, profiles/experiments 디렉토리 기반

---

## Phase 8 — Search Foundation + SearXNG (2026-03-15)

- `src/utils/searxng_client.py` — SearXNG JSON API 클라이언트, rate limiting
- `src/utils/reasoning_client.py` — Claude CLI/SDK thin adapter
- `src/agents/search_agent.py` — SearchAgent hybrid pipeline (SearXNG → Claude 감성 분석)
- `src/agents/search_runner.py` — SearchRunner (Strategy S StrategyRunner 구현)
- `src/agents/research_portfolio_manager.py` — ResearchPortfolioManager + sentiment→signal 매핑
- `src/agents/index_collector.py` — IndexCollector (KOSPI/KOSDAQ)
- `src/schedulers/index_scheduler.py` — APScheduler 지수 수집 자동화
- `scripts/db/init_db.py` — search_queries/search_results/page_extractions/research_outputs 4-테이블
- `docs/research_contract.json` — Research Contract JSON 스키마
- `docker/searxng/` — SearXNG Docker 설정

---

## Phase 7 — S3 Data Lake (MinIO + Parquet) (2026-03-15)

- `docker-compose.yml` — MinIO 서비스 + S3 env
- `src/utils/s3_client.py` — boto3 싱글턴, CRUD 유틸
- `src/services/datalake.py` — 7 DataType enum, PyArrow 스키마, Parquet 직렬화, Hive 파티셔닝
- collector.py, predictor.py, paper.py — S3 저장 연동
- 끊어진 파이프라인 8건 수정 (2026-03-18): Critical 3건 + Warning 4건 + Notice 1건

---

## Phase 6 — 독립 포트폴리오 인프라 (2026-03-15)

- `src/brokers/virtual_broker.py` — VirtualBroker (슬리피지/부분체결/체결지연)
- `src/utils/strategy_promotion.py` — virtual→paper→real 승격 파이프라인
- `src/utils/aggregate_risk.py` — 합산 리스크 모니터링
- `scripts/seed_historical_data.py`, `scripts/promote_strategy.py`
- DB 스키마 확장: strategy_promotions, aggregate_risk_snapshots, strategy_id 5개 테이블
- 테스트 88/88 통과

---

## Phase 1~5 — 인프라·에이전트·전략·UI (2026-03-12~13)

**Phase 1 인프라:**
- PostgreSQL 11개 테이블, FastAPI, KIS OAuth, KRX 공휴일, 헬스체크, 스모크테스트
- React + Vite + TypeScript + Tailwind 프론트엔드 스캐폴딩

**Phase 2 코어 에이전트:**
- CollectorAgent (KIS WebSocket + FinanceDataReader), PredictorAgent (Claude/GPT/Gemini)
- PortfolioManagerAgent, NotifierAgent, OrchestratorAgent

**Phase 3 Strategy A Tournament:**
- 5개 Predictor 병렬 실행, 롤링 정확도 기반 우승자 선정, Orchestrator --tournament 연동

**Phase 4 Strategy B Consensus/Debate:**
- Proposer/Challenger/Synthesizer 흐름, debate_transcripts 저장, max_rounds/consensus_threshold

**Phase 5 대시보드 + 운용 검증:**
- 대시보드/포트폴리오/마켓/설정 UI 완성 + API 연동
- 실거래 준비 가드/감사 체계, 페이퍼 운용 자동 리포트, Docker 기준 Phase 1~7 100% 검증 통과

---

## 작업 로그

| 날짜 | 작업 내용 |
|------|-----------|
| 2026-03-28 | 블로그 자동 포스팅 시스템 구축, MEMORY.md 아카이브 분리, CLAUDE.md/architecture.md 반영, 논의 문서 5건 포스팅+삭제, progress.md 정리 정책 수립 |
| 2026-03-18 | 끊어진 파이프라인 전수 수정 완료 — Critical 3건 + Warning 4건 + Notice 1건 총 8건 처리 |
| 2026-03-17 | RL Trading UI 버그 6종 수정, 에이전트 레지스트리 PostgreSQL 중앙 관리 |
| 2026-03-16 | 피드백 루프 파이프라인 구현, N+1 쿼리 배치 최적화, Copilot 리뷰 코드 품질 수정 |
| 2026-03-15 | Phase 9 RL Trading Lane, S3 Data Lake, 독립 포트폴리오 인프라, N-way 블렌딩 |

---

*Archived from progress.md on 2026-03-28*
