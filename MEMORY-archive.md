# 🗄️ MEMORY-archive.md — 완료된 기술적 결정 이력

> **이 파일은 MEMORY.md에서 분리된 아카이브입니다.**
> 이미 구현 완료된 결정의 상세 이력을 원문 그대로 보존합니다.
> 활성 운영 규칙과 미해결 이슈는 `MEMORY.md`를 참조하세요.

---

## 2026-04-08 — Cluster Secret 단일 소스화 SOPS+age 도입 (PR #104)

- **문제:** PR #102/#103 머지 후 라이브 배포 시 새 api 파드가 `asyncpg.InvalidPasswordError` 로 CrashLoopBackOff. 옛 파드만 살아 있어 사용자가 `192.168.64.3/feedback` 접속 시 PR 이전 코드가 응답하는 deadlock. 추적 결과 cluster secret 이 3곳에 따로 살고 어디가 진실인지 아무도 모름:
  - `k8s/helm/bitnami-values/postgres-values.yaml:7` — `alpha_pass` (평문 커밋)
  - `k8s/base/secrets.yaml:14` — `change-me` (평문 커밋, kustomize 가 매번 덮어씀)
  - `kubectl get secret app-secret` — `change-me`
- **결정:** **SOPS + age** 채택 (3축 매핑: 확장성·안전·관리 수월함)
  - 확장성 ✅ — `.sops.yaml` recipient 추가만으로 협업자 합류, 디렉토리별 rule 로 환경 분리 가능
  - 안전 ✅ — age 는 X25519 + ChaCha20-Poly1305 (modern AEAD), encrypted_regex 로 키 이름은 평문 / 값만 ENC[...]
  - 관리 수월함 ✅ — 운영 server 0대, controller 0개, unseal 의식 없음, DR = age key 1개 백업
- **탈락 대안:**
  - **Vault/OpenBao** — 1인 1노드에 unseal/HA/Raft 는 관리 수월함 파탄. Vault BUSL 라이선스 + 2025 년 Cyata 0day. 향후 팀 5인+ 시 SOPS→Vault 마이그레이션은 평이 (decrypt → vault kv put). SOPS 가 stepping stone.
  - **Sealed Secrets** — sealing key 가 새 SPOF, rotation 까다로움. PR diff 가시성에서 SOPS 우위.
  - **Infisical** — 또 다른 server 운영 부담.
- **산출물 (PR #104, 5 commits):**
  - `.sops.yaml` — encrypted_regex `^(data|stringData)$` 로 키 이름은 평문, 값만 암호화
  - `k8s/secrets/app-secret.enc.yaml` — bootstrap 후 자동 생성, git 에 암호화된 채로 커밋
  - `k8s/scripts/secrets-bootstrap.sh` — age 키 생성 + `.sops.yaml` 치환 + `.env` → 암호화 파일 (멱등)
  - `k8s/scripts/secrets-edit.sh` — `sops` 인터랙티브 편집 wrapper
  - `k8s/scripts/rotate-secrets.sh` — leak 사고 대응용 한 번 실행 회전 + 재배포 (8단계 자동)
  - `k8s/scripts/deploy-local.sh` — `sops --decrypt | kubectl apply` 단계 추가, `SOPS_AGE_KEY_FILE` export (macOS sops 기본 위치 mismatch 회피)
  - `k8s/base/secrets.yaml` 삭제, `k8s/base/kustomization.yaml` 에서 리소스 라인 제거
  - `k8s/helm/{bitnami-values,alpha-trading}/*.yaml` 평문 placeholder 제거 + 주석
  - `docs/secrets.md` — 일상 운영 가이드
  - `docs/secret-leak-recovery.md` — leak 사고 대응 절차 (CLAUDE.md 에서 링크)
  - `test/test_secrets_sops.sh` — 14건 hermetic 단위 테스트 (merge gate)
- **사고 (배포 중):** 첫 deploy 시도에서 `kubectl apply` 가 `cannot convert int64 to string` 으로 거절하면서 **error 메시지에 전체 patch 평문이 포함되어 모든 secret 이 사용자 터미널 + 채팅 로그에 leak**. 원인:
  1. bootstrap 이 `KIS_IS_PAPER_TRADING=true` / `TELEGRAM_CHAT_ID=8203915188` 를 quote 없이 YAML 로 출력 → bool/int 으로 자동 추론
  2. `Secret.stringData` 는 string-only 라 거절 + kubectl 이 거절 사유로 patch 본문을 dump
- **사고 fix:** bootstrap 이 모든 값을 single-quoted YAML scalar 로 출력 (`printf "  %s: '%s'\n"`, 내부 single quote escape). 또한 `DATABASE_URL` 의 `localhost` 를 `alpha-pg-postgresql:5432` 로 sed 치환 (k8s 컨텍스트와 로컬 컨텍스트 분리). 회귀 방지: case 10 (`test_secrets_bootstrap_quotes_bool_and_int_values`) + case 11 (`test_secrets_bootstrap_rewrites_database_url_localhost`).
- **rotate-secrets.sh 검증 hook:** 가짜 repo + hermetic age key 로 실제 postgres / kubectl / docker 없이 rotation 흐름 전체를 end-to-end 검증. `ROTATE_NON_INTERACTIVE` / `ROTATE_SKIP_CONFIRM` / `ROTATE_SKIP_POSTGRES` / `ROTATE_SKIP_DEPLOY` 환경변수는 **테스트 전용** — 운영자는 절대 직접 export 금지 (KIS 입력이 컨텍스트에 노출). case 14 (`test_rotate_secrets_end_to_end_hermetic`) 가 9개 invariant 검증.
- **명시적으로 *안* 한 것:**
  - postgres PVC nuke (운영 데이터 보존, `ALTER USER` 로 런타임 동기화)
  - `.env` 폐기 (로컬 개발용 부트스트랩 스크립트 입력으로 유지, cluster secret 만 SOPS 로 일원화)
  - CI 에 SOPS 통합 (CI 는 lint/test 만 돌려 secret 불필요)
  - LLM credentials (`llm-credentials` Secret) SOPS 화 — 파일 기반 secretGenerator 라 별도 PR
  - KIS 토큰 자동 rotation (별도 작업, KIS API 호출 로직)
- **운영 책임 분리 (사용자 ↔ SOPS):**
  - SOPS 가 함: secret 의 *전달* (git → cluster), 협업자 동기화, drift 방지, DR
  - 사용자가 함: secret 의 *발급/회전* (KIS / Telegram / postgres / age key 백업), leak 시 원천 키 재발급
- **장기 기억:** `feedback_secrets_handling.md` — Claude 는 secret 이 도구 출력에 닿을 수 있는 명령(개인키 생성, `--decrypt` 검증, 비번 ALTER 등)을 직접 실행하지 않고 사용자에게 위임. 도구 출력은 `~/.claude/projects/.../*.jsonl` 에 영구 저장되어 leak 시 회수 불가.
- **검증:** `bash test/test_secrets_sops.sh` → 14/14 passed, `shellcheck k8s/scripts/*.sh test/test_secrets_sops.sh` → clean. 라이브 검증(새 api Running + asyncpg 연결 + Task B bandit 재개)은 사용자의 실제 rotation 후 진행 예정.

---

## 2026-03-29 — 문서 정비 + smoke test 통과 (PR #53)

- **작업:** README 정량 지표 섹션 추가, Airflow 비교 문서 신규 작성, README 빠른 시작 minio 누락 수정
- **의사결정:**
  - Airflow 전면 마이그레이션 대신 "비교 스파이크" 접근 — Alpha의 실시간 요구사항(30초 인터벌, 이벤트 드리븐)에는 APScheduler+Redis가 적합. Airflow의 실행 이력 UI/backfill CLI/DAG 시각화만 선별 도입 검토.
  - README 빠른 시작에 minio 서비스 필수 — docker-compose.yml에서 api/worker가 `minio: service_healthy`에 의존하므로 누락 시 시작 불가.
- **산출물:** `docs/airflow-comparison.md` (15항목 비교표, 9개 구현체↔Airflow 매핑, 9개 잡 DAG 매핑), README.md 정량 지표
- **검증:** smoke test 전체 통과 (DB/Redis/FastAPI/FDR)

---

## 2026-03-18 — 데이터 수집/저장 경로 전수 감사 (상세)

- **작업:** 코드 기반으로 전체 데이터 수집 소스 9개, 저장소 4종(PG 20테이블, Redis 13키+5 Pub/Sub, S3 4 DataType, 로컬 파일 2경로)을 매핑.
- **산출물:** `DATA-STOCK_ARCHITECTURE.md` (상세 문서), `architecture.md` 데이터 아키텍처 섹션 갱신 (참조 링크 추가)
- **발견된 끊어진 파이프라인 (Critical 3건, Warning 5건, Notice 3건):**
  1. 🔴 **SearchAgent 완전 stub** — `run_research()`에 TODO 3개만 있고 항상 neutral/0.5 반환. SearXNG 클라이언트는 완성되어 있으나 SearchAgent에서 호출 안 함.
  2. 🔴 **Orchestrator CLI에서 Runner 미등록** — `_main_async()`에서 StrategyRegistry가 비어 있어 전략 실행 0건.
  3. 🔴 **LLM 프로바이더 전원 장애** — Docker 내 Claude CLI 부재, GPT 미사용 정책, Gemini ADC 미마운트 → Predictor 전체 실패.
  4. 🟡 **Yahoo 일봉 Redis/S3 미저장** — `collect_yahoo_daily_bars()`는 PG만 사용.
  5. 🟡 **실시간 틱 S3 미저장** — `store_tick_data()` 함수 미구현 (enum만 존재).
  6. 🟡 **Historical Bulk Redis/S3 미사용** — 벌크 시드 후 Redis 캐시 빈 채로 남음.
  7. 🟡 **IndexCollector DB 미저장** — Redis 120초 캐시만, 지수 이력 분석 불가.
  8. 🟡 **debate_transcripts/rl_episodes S3 미구현** — DataType enum만 존재.
  9. 🟠 **스케줄러가 IndexCollector만 가동** — 일봉/매크로/종목마스터 자동 수집 없음.
  10. 🟠 **ticker_master 테이블 누락 가능성** — lifespan에서 조회하지만 init_db에 DDL 미확인.
  11. 🟠 **RLRunner 활성 정책 0건** — 학습 → 활성화 파이프라인 미실행 시 RL 시그널 0건.

---

## 2026-03-17 — 에이전트 레지스트리 PostgreSQL 중앙 관리 (상세)

- **문제:** 에이전트 ID가 여러 곳에 하드코딩(API 라우터 `AGENT_IDS` 리스트, 각 에이전트 클래스 기본값)되어 불일치 발생. `OrchestratorAgent(agent_id="orchestrator")`이 하트비트를 `"orchestrator"`로 기록하지만 API는 `"orchestrator_agent"`를 조회 → 영원히 "연결 끊김" 표시.
- **결정:** `agent_registry` PostgreSQL 테이블로 에이전트 목록을 중앙 관리. API는 DB에서 동적 조회, 폴백 하드코딩 유지.
- **수정사항:**
  - `scripts/db/init_db.py`: `agent_registry` 테이블 DDL + 11개 시드 데이터
  - `src/api/routers/agents.py`: `AGENT_IDS` 하드코딩 → `_load_agent_registry()` DB 조회 (폴백 포함)
  - `src/agents/orchestrator.py`: `agent_id` 기본값 `"orchestrator"` → `"orchestrator_agent"`, PM/Notifier 인스턴스도 정규 ID 사용
  - 레지스트리 CRUD API: `/registry/list`, `/registry/register`, `/registry/{id}` DELETE

---

## 2026-03-17 — LLM 프로바이더 운영 정책 (상세)

- **현황:** Predictor 1~5 모든 종목 예측 실패 (0성공/3실패)
- **원인 추정:** Claude CLI 또는 Gemini OAuth 호출이 Docker 컨테이너 내에서 실패 중. 컨테이너 로그(`docker compose logs worker`) 확인 필요.

---

## 2026-03-16 — N+1 쿼리 배치 최적화 executemany (상세)

- **결정:** 수집-저장 파이프라인의 모든 bulk upsert 함수(`for + await execute()` 패턴)를 `asyncpg executemany()`로 전환. 실시간 틱에는 메모리 버퍼 도입.
- **근거:**
  - `for + await execute()`는 매 반복마다 커넥션 acquire/release + 네트워크 왕복 발생 → 2,400건 기준 10~30초
  - `executemany`는 내부적으로 PostgreSQL extended protocol pipelining 사용 → 네트워크 왕복 1회, 0.1~0.5초
  - `max_size`를 200으로 올려도 해결 불가: 직렬 `await`라 커넥션 1개만 사용, PostgreSQL 커넥션 비용(5~10MB/개), `max_connections=100` 초과 위험
- **구현:**
  - `db_client.py`: `executemany()` 헬퍼 (chunk_size=5,000 자동 분할)
  - `queries.py`: `upsert_market_data()` 전환
  - `marketplace_queries.py`: 4개 함수 전환 (krx_stock_master/theme/macro/rankings)
  - `collector.py`: `_tick_buffer` + `_flush_tick_buffer()` (100건 또는 1초 주기)
- **AI 합의:** GitHub Copilot + Claude Opus 모두 Option A(executemany) 추천. UNNEST(Option B)는 복잡도 대비 이점 미미, COPY(Option C)는 upsert 불가로 부적합.

---

## 2026-03-16 — Strategy S Orchestrator 통합 + 마켓플레이스 Closure (상세)

- **결정:** SearchRunner를 StrategyRunner Protocol로 구현하여 Orchestrator에 등록. 4-way 블렌딩(A:0.3/B:0.3/S:0.2/RL:0.2) 완성.
- **구현:**
  - `src/agents/search_runner.py` — StrategyRunner Protocol 구현, ResearchPortfolioManager 래핑
  - `test/test_search_runner_integration.py` — Protocol 준수/에러 핸들링/Orchestrator 등록 테스트
  - `orchestrator.py` TYPE_CHECKING import 수정
- **마켓플레이스 Closure:** Week 1~5 전체 구현 완료 확인. `roadmap.md`에 Phase 13 추가. 논의 문서 closed.
- **README 전면 업데이트:** 4전략 N-way 블렌딩 아키텍처, 확장 상태 표 반영.

---

## 2026-03-16 — Copilot 리뷰 코드 품질 수정 PR #11 후속 (상세)

- **수정 내역:**
  1. **orchestrator.py — risk_summary dict→dataclass:** `risk_summary.get("violations")` → `risk_summary.warnings`. `AggregateRiskMonitor.get_risk_summary()`는 `RiskSummary` dataclass를 반환하며, 필드명은 `warnings`(list[str]).
  2. **orchestrator.py — StrategyPromoter 파라미터:** `evaluate_promotion_readiness(strategy_name)` → `evaluate_promotion_readiness(strategy_name, from_mode="virtual", to_mode="paper")`. 메서드는 3개 필수 파라미터 필요.
  3. **orchestrator.py — PromotionCheckResult 필드명:** `readiness.is_ready` → `readiness.ready`. dataclass 필드명은 `ready: bool`.
  4. **WalkForwardResult.overall_approved:** 모든 소비자에서 일관되게 사용 확인 — 변경 불필요.
- **교훈:** dataclass 반환값을 dict처럼 사용하는 패턴은 런타임까지 발견 안 되므로, 향후 `mypy --strict` 도입 검토 필요.

---

## 2026-03-15 — Search Strategy (S) 파이프라인 통합 (상세)

**결정**: 기존 Strategy A/B 구조를 유지하면서 Search Strategy (S)를 4번째 전략으로 추가.

**배경**:
- RL Trading 및 검색 파이프라인 확장이 필요함
- 기존 구조의 변경을 최소화해야 함
- 멀티 에이전트 시스템의 N-way 블렌딩이 이미 구현되어 있음

**구현**:
- `ResearchPortfolioManager`: SearchAgent를 래핑하여 종목별 리서치 수행
- `SearchRunner`: StrategyRunner 프로토콜 준수하는 새로운 전략 러너
- Sentiment → Signal 매핑: bullish=BUY, bearish=SELL, neutral/mixed=HOLD
- Redis 캐싱: 4시간 TTL로 동일 쿼리 중복 실행 방지
- PortfolioManagerAgent의 주문 권한 분리: 시그널만 생성

**결과**:
- N-way 블렌딩에 자연스럽게 통합
- `strategy_blend_weights`의 `"S": 0.20` 추가로 20% 가중치 부여
- 기존 Strategy A/B 동작에 영향 없음

---

## 2026-03-15 — Phase 9 RL Trading Lane 전체 구현 완료 (상세)

- **구현 항목:**
  1. `src/agents/rl_dataset_builder_v2.py` — SMA(5/20/60), RSI(14), 변동성(10일), 거래량비율, 수익률 + 매크로 컨텍스트(KOSPI/KOSDAQ/USD/VIX/섹터) 확장 데이터셋
  2. `src/agents/rl_environment.py` — Gymnasium 호환 TradingEnv, 4-action(BUY/SELL/HOLD/CLOSE), 기회비용+포지션 리워드+거래 페널티, MDD 조기종료, numpy 사전 계산
  3. `src/api/routers/rl.py` — 17개 REST 엔드포인트 (정책 CRUD 5개 + 실험 2개 + 평가 1개 + 학습 2개 + walk-forward 1개 + shadow 4개 + promotion 2개)
  4. `src/agents/rl_walk_forward.py` — N-fold expanding/sliding window 교차검증, consistency_score(positive_ratio × CV 보정), 자동 승인 판정
  5. `src/agents/rl_shadow_inference.py` — ShadowInferenceEngine(shadow 시그널 생성/성과추적), PaperPromotionCriteria(shadow→paper 6개 조건), RealPromotionCriteria(paper→real 6개 조건), 시뮬레이션 수익률/MDD 계산
- **승격 파이프라인:** 학습 → 오프라인 평가 → shadow 추론(is_shadow=True, 블렌딩 제외) → paper 승격 게이트 → paper 운용 → real 승격 게이트
- **테스트:** `test/test_phase9_rl.py` 5개 클래스

---

## 2026-03-15 — Phase 2 후속: 독립 포트폴리오 인프라 구현 (상세)

- **VirtualBroker 시뮬레이션:** 슬리피지 0~N bps (BUY 상승/SELL 하락), 부분 체결 50~100% (10주 초과 시), 체결 지연 0~N초. 모두 config로 조정 가능.
- **승격 기준:** virtual→paper (30일 운영, 20건 거래, 0% 수익, -15% DD, 0.5 Sharpe), paper→real (60일, 50건, 5%, -10%, 1.0). `PROMOTION_CRITERIA_OVERRIDE` env로 JSON 오버라이드 가능.
- **합산 리스크:** 단일 종목 노출 한도 (`MAX_SINGLE_STOCK_EXPOSURE_PCT`), 전략 간 종목 중복 한도 (`MAX_STRATEGY_OVERLAP_COUNT`). 스냅샷을 `aggregate_risk_snapshots` 테이블에 JSONB로 기록.
- **DB 확장:** `strategy_id VARCHAR(10)` 컬럼을 5개 테이블에 추가, `COALESCE(strategy_id, '')` 패턴으로 하위 호환 유지. account_scope CHECK에 'virtual' 추가.
- **핵심 파일:** `src/brokers/virtual_broker.py`, `src/utils/strategy_promotion.py`, `src/utils/aggregate_risk.py`, `scripts/seed_historical_data.py`, `scripts/promote_strategy.py`

---

## 2026-03-15 — Index Collector 에이전트 추가 (상세)

- `IndexCollector`: KIS API를 통해 KOSPI(0001), KOSDAQ(1001) 수집
- `index_scheduler.py`: APScheduler 사용
  - 08:55 KST: 사전 워밍업 (1회)
  - 장중 매 30초: 정기 수집 (시장 열려있을 때만)
- Redis 캐시: `market_index:{...}` 키로 저장, TTL 1분

---

## 2026-03-15 — Sentiment → Signal 매핑 규칙 (상세)

```python
SENTIMENT_TO_SIGNAL = {
    "bullish": "BUY",
    "bearish": "SELL",
    "neutral": "HOLD",
    "mixed": "HOLD",
}
```

**신뢰도 (confidence) 기준**:
- `< 0.3`: HOLD로 fallback (항상)
- `sources = 0`: confidence를 0.3 이하로 하향
- `> 1.0`: 1.0으로 클립
- `[0, 1]`: 4자리 반올림

---

## 2026-03-15 — 캐싱 전략 (상세)

- 검색 결과를 Redis에 4시간 캐싱
- `ResearchPortfolioManager._get_cached_signal(ticker)`: 캐시 조회
- `ResearchPortfolioManager._cache_signal(ticker, signal)`: 캐시 저장
- Key: `research:signal:{ticker}`

---

## 2026-03-15 — 에러 핸들링 정책 (상세)

- 리서치 실패 시 항상 HOLD 신호로 fallback
- `ResearchPortfolioManager._research_single_ticker()`: try-except로 예외 처리
- `ResearchPortfolioManager.run_research_cycle()`: 부분 장애 감지 및 로깅

---

## 2026-04-13 — 클라우드 LLM 인증·비용 전략 구현 (PR #189)

CLI 구독 1순위 + API Key SDK 자동 fallback 아키텍처 구현. `CLIAuthError` 예외로 인증 실패를 구분하고, Claude/GPT 클라이언트가 CLI 실패 시 내부적으로 SDK로 전환. 1분 주기 health 크론잡이 3 프로바이더(Claude CLI, Codex auth.json, Gemini ADC) 감시 → 상태 변경 시만 Telegram 알림. Redis에 CLI/SDK 사용 모드 추적. `.env.example`에 fallback API key 환경변수 문서화. Oracle Always Free 인스턴스 생성 재시도 스크립트 추가. 테스트 39개 추가, 전체 2424개 통과.

---

## 2026-04-13 — 클라우드 마이그레이션 갭 수정 (PR #188)

Docker Compose prod 배포 준비 + K3s 원복 가능 상태 보장. docker-compose.prod.yml MinIO profile 비활성화(R2 전환), s3_client.py ensure_bucket() R2 graceful 처리(403/409 경고 로그), K3s prod overlay worker-env.yaml(RL 비활성화) + R2 전환 가이드, `.env.example` S3/R2 환경변수 섹션 추가, `k8s/README.md` Docker Compose→K3s 원복 8단계 매뉴얼. 테스트 R2 시나리오 4건 추가.

---

## 2026-04-12 — KIS OAuth 토큰 장중 health 체크 (PR #170)

장중(09~15시) 매시 정각 KIS OAuth 토큰 유효성 자동 검증 크론잡 추가. unified_scheduler 11번째 잡. 토큰 없음 → 재발급, TTL 1h 미만 → 갱신, 실패 시 NotifierAgent→Telegram 알림. 분산 락 TTL 30초. KIS_IS_PAPER_TRADING 설정에 따라 paper/real 스코프 자동 결정. 배포 전 K3s pod에서 `issue_kis_token(scope='paper')` 토큰 발급 테스트로 연결 정상 확인.

---

## 2026-04-12 — RL Training Jobs/Experiments DB 관리 (PR #165)

RL 학습 잡 라이프사이클을 in-memory dict에서 DB 테이블로 전환. `rl_training_jobs`(queued→running→completed/failed)와 `rl_experiments`(실험 결과) 2개 테이블 신설. 종목 등록(PUT /rl/tickers) 시 활성 정책 없는 종목에 대해 자동으로 queued job 생성. UI "학습 시작" 버튼이 POST /training-jobs/{job_id}/start를 호출하면 asyncio.create_task로 백그라운드 학습 실행, 완료 시 실험 결과를 rl_experiments에 저장. 기존 파일시스템(artifacts/rl/experiments/) 의존 제거.

---

## 2026-04-12 — prediction_schedule 테이블 설계 (discussion only)

Strategy A/B 예측 주기를 DB 테이블로 관리하는 설계안 확정. A안 채택: prediction_schedule 테이블(strategy_name PK, interval_minutes, is_active) + orchestrator 루프 sleep(600)→sleep(60) + 전략별 last_run_at 기반 skip 로직. 기본 30분 간격, 장중 ~13회 실행. 환경변수 ORCH_INTERVAL_SECONDS는 fallback으로만 유지. 구현 미착수. 상세: `.agent/discussions/20260412-prediction-schedule-table-design.md`

---

## 2026-04-11 — RL 종목 레지스트리 자동 동기화 (PR #136)

instruments 테이블을 종목 SoT로 채택하여 Orchestrator·RL 스케줄러의 하드코딩(_DEFAULT_TICKERS 등) 전면 제거. RL bootstrap 크론잡이 DB에서 종목을 읽어 registry.json에 자동 등록. registry.json은 학습 이력 저장소로 역할 축소. ticker 정규화 중복(259960 vs 259960.KS) 병합.

---

## 2026-04-11 — 일봉 수집 100종목 확대 + 스크리너 도입 (PR #137)

일봉 수집 3→100종목 확대(FDR 무료, 비용 0원) + 스크리너 모듈 도입. 거래량 급등(20일 평균 2배) + 변동률(±3%) 기반 필터링 → 전략 실행 하드캡 10종목. 전 종목 LLM 실행은 비용 폭발이라 2-tier(수집→스크리너→전략) 구조 채택.

---

## 2026-04-11 — Step 8b 후속: Predictor 분봉 통합 + S3 틱 최적화 (PR #133)

(1) Predictor에 당일 1시간봉 통합 — get_ohlcv_bars('1hour')로 장중 데이터를 fetch하여 LLM 프롬프트에 포함, 데이터 없으면 일봉만 fallback. (2) S3 틱 최적화 — _make_s3_key()에 hour 파라미터 추가(Hive-style date+hour 2단계 파티셔닝), _flush_tick_buffer()에서 S3 제거 후 장 종료 크론(15:40 KST)으로 DB→S3 시간대별 일괄 flush.

---

## 2026-04-11 — S3 틱 데이터 최적화 설계

로컬 MinIO 1초 flush 유지(이중 백업) + 장 종료 후 DB→클라우드 일괄 아카이브. _make_s3_key()에 optional hour 파라미터(Hive-style date+hour 2단계 파티셔닝). get_ticks_by_hour()로 시간대별 분리 쿼리 → 하루 ~7개 대형 Parquet. 클라우드 Lifecycle: tick_data/ prefix 30d→IA, 90d→Glacier IR. step8b-followup(PR #133)에 흡수 구현.

---

## 2026-04-11 — 실시간 틱 수집 스케줄링 방식 결정 (폐기)

3종목 기준으로 크론잡 2개(시작+헬스체크) 추가를 결정했으나, 100종목 스케일링 분석 결과 별도 tick-collector 서비스(PR #138)로 재결정. 장애 격리(틱↔매매 독립) + 독립 재시작이 핵심 근거. 본 문서는 tick-collector-service-design.md가 대체.

---

*Archived from MEMORY.md on 2026-03-28*
