# 📝 progress.md — 현재 세션 진척도

> 에이전트와 "현재 어디까지 했는지" 맞추는 단기 기억 파일입니다.
> 완료된 이력은 `progress-archive.md`를 참조하세요.
> **정리 정책**: 150줄 초과 시 완료+코드 유추 가능 항목 삭제. 200줄 초과 시 오래된 완료 항목 강제 삭제.
> **문서 연결 정책**: 작업 항목에 관련 discussion 파일이 있으면 `상세: .agent/discussions/파일명.md` 형태로 링크를 기재한다.

---

## 이 프로젝트가 하는 일

한국 주식(KOSPI/KOSDAQ)을 **AI가 자동으로 분석하고 매매**하는 시스템이다.
5개의 AI 에이전트가 역할을 나눠 협업한다:

- **CollectorAgent** — 주가 데이터를 수집한다 (일봉 + 실시간 틱)
- **PredictorAgent** — AI(Claude/GPT/Gemini)로 종목을 분석하고 매수/매도 신호를 낸다
- **PortfolioManagerAgent** — 리스크 규칙을 검증하고 실제 주문을 넣는다
- **OrchestratorAgent** — 전체 흐름을 조율하고 에이전트 상태를 감시한다
- **NotifierAgent** — 매매 결과, 이상 상황을 Telegram으로 알린다

세 가지 전략을 동시에 운용한다:
- **Strategy A (토너먼트)** — AI 5명이 각자 예측 → 성적 좋은 AI의 신호를 채택
- **Strategy B (토론)** — AI끼리 찬반 토론 → 합의된 신호만 채택
- **Strategy RL (강화학습)** — 과거 데이터로 학습한 모델이 자동 판단

---

---

## ✅ 최근 완료

### 클라우드 LLM 인증·비용 전략 구현 (2026-04-13)

CLI 구독 인증 1순위 + API Key SDK 자동 fallback + 1분 주기 Health 감시.
- `cli_bridge.py` — `CLIAuthError` 예외 + stderr 인증 키워드 감지 (9개 패턴)
- `claude_client.py` — CLI auth 실패 → SDK lazy fallback (`_ensure_sdk_client()`)
- `gpt_client.py` — CLI 구독 우선순위로 변경 (기존 API key 우선 → CLI 먼저) + auth 실패 시 SDK fallback
- `llm_usage_limiter.py` — `reserve_provider_call(mode=)` CLI/SDK 사용 모드 Redis 추적
- `unified_scheduler.py` — `check_llm_auth_health()` 1분 크론 잡 (Claude CLI/Codex/Gemini ADC 점검, 상태 변경 시 Telegram 알림)
- `notifier.py` — `send_llm_auth_alert()` 인증 상태 변경 알림 메서드
- `.env.example` — 클라우드 인증 섹션 확장 (CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_API_KEY, OPENAI_API_KEY fallback 설명)
- `scripts/oci_instance_retry.sh` — Oracle Ampere A1 인스턴스 생성 5분 재시도 스크립트
- 테스트 39개 추가, 전체 2424개 통과
- 상세: `.agent/discussions/20260411-cloud-llm-auth-cost-optimization.md`

### 클라우드 마이그레이션 갭 수정 (2026-04-13, PR #188)

Docker Compose prod 배포 준비 + K3s 원복 가능 상태 보장.
- `docker-compose.prod.yml` — MinIO profile 비활성화(R2 전환), tick-collector override, db-init-migrate 4단계, RL 학습 비활성화
- `s3_client.py` — ensure_bucket() R2 graceful 처리 (403/409 경고 로그, MinIO 정상 동작 유지)
- K3s prod overlay — worker-env.yaml (RL 비활성화) + R2 전환 가이드
- `.env.example` — S3/R2 환경변수 섹션 추가
- `k8s/README.md` — Docker Compose→K3s 원복 8단계 매뉴얼 + 트러블슈팅
- 테스트 R2 시나리오 4건 추가, 전체 2381개 통과

### Optuna 하이퍼파라미터 자동 탐색 Phase 2 (2026-04-12, PR #186)

SB3 알고리즘의 하이퍼파라미터를 Optuna TPE sampler로 자동 탐색.
- `rl_hyperopt.py` — RLHyperOptimizer (DQN 10개, A2C 6개, PPO 9개 search space)
- TPE sampler + MedianPruner, SQLite 저장, best_params JSON 출력
- `rl_continuous_improver.py` — 프로파일 `hyperopt.enabled` 또는 `use_hyperopt` 플래그 연동
- `rl_bootstrap.py` — `--hyperopt`, `--hyperopt-trials N` CLI 플래그
- SB3 프로파일 3개에 `hyperopt` 섹션 추가 (기본 disabled)
- `requirements.txt` + `tech_stack.md`에 `optuna>=3.0,<4.0` 등록
- 테스트 27개 추가, 전체 2377개 통과

### RL SB3 통합 Trainer + Ensemble Phase 1 (2026-04-12)

Tabular Q → SB3(DQN/A2C/PPO) 통합 trainer 구현 완료.
- `rl_trading_sb3.py` — SB3Trainer (ALGO_MAP 패턴, lazy import, multi-seed 학습)
- 프로파일 3개 (`dqn_v1_baseline`, `a2c_v1_baseline`, `ppo_v1_baseline`)
- `rl_continuous_improver.py` — `_WalkForwardSB3Adapter` + `_trainer_for_profile()` SB3 분기
- `rl_runner.py` — `_infer_sb3()` SB3 추론 분기 + algorithm별 llm_model 태깅
- `rl_policy_store_v2.py` — .zip 모델 파일 영구 저장 (shutil.copy2)
- `rl_walk_forward.py` — `_extract_q_table()` str 통과 (SB3 model_path)
- `rl_trading.py` — `RLPolicyArtifact.q_table` Optional, `model_path` 필드 추가
- `rl_environment.py` — `GymTradingEnv` MRO 수정 (TradingEnv → gym.Env)
- 테스트 55개 (`test_rl_sb3.py`) + 기존 308개 전체 통과
- `stable-baselines3>=2.3,<3.0` requirements.txt 추가
- 상세: `.agent/discussions/20260412-rl-sb3-ensemble-phase1-implementation.md`

### RL 학습 파이프라인 안정화 (2026-04-12, PR #167~#172)

학습 잡 FAILED 원인 해결 + 진행률 추적 + 프로파일 동적 조회.
- `progress_pct` 컬럼 추가 — 멀티시드 학습 루프에서 seed 완료마다 진행률 콜백 (PR #167)
- 프로파일 이름 하드코딩 제거 — `artifacts/rl/profiles/` 디렉토리 동적 스캔 (PR #168)
- Dockerfile 프로파일 COPY + deploy-local.sh PVC 자동 동기화 (PR #169, #171)
- V1 TabularQTrainer `**kwargs` 호환성 수정 (PR #172)

### prediction_schedule 테이블 구현 (2026-04-12, PR #166)

전략별 예측 주기를 DB 테이블로 관리. Orchestrator 1분 체크 + 전략별 30분 간격 skip 로직.
GET/PUT /api/v1/scheduler/prediction-schedule API. K3s 마이그레이션 완료.

### rl_targets 테이블 + Docker 이미지 정리 (2026-04-12, PR #163, #164)

RL chicken-and-egg 문제 해결 + 이미지 이름 alpha-api/alpha-ui로 통일.

### KIS 토큰 health 체크 크론잡 (2026-04-12, PR #170)

장중 09~15시 매시 정각 KIS OAuth 토큰 유효성 자동 검증.

### 틱+일봉 통합 분석 레이어 Phase 0 (2026-04-12, PR #178~#180)

ohlcv_minute 인프라 + S3 아카이브 + UnifiedMarketData 빌더 완성.
- `ohlcv_minute` 테이블 (월별 파티셔닝) + 15:50 KST 배치 집계 크론 (PR #179)
- S3 Parquet 아카이브 + 매월 1일 파티션 관리 크론 (PR #180)
- `UnifiedMarketData` 빌더 + `compute_intraday_features()` (PR #178)

---

## 🔄 다음 작업

### 로컬 데이터 축적 (진행 중)

로컬 K3s에서 틱/분봉 데이터를 먼저 축적. 클라우드 비용 발생을 늦추면서 RL 선행 조건 충족.
클라우드 전환 시 `pg_dump` + R2 sync로 이전.

**✅ 해결 (2026-04-11, PR #138):**
1. `collector.run()` 복원 → `collect_daily_bars()` 위임. 08:30 KST 일봉 수집 정상화.
2. 별도 `tick-collector` 서비스 신규 추가 — 장애 격리(틱↔매매 독립), 독립 재시작. K3s 배포 필요.

### RL 모델 DQN 업그레이드 + Optuna (Phase 1~2 완료)

**✅ Phase 1 — SB3 통합 Trainer + Ensemble (2026-04-12):** 완료.
**✅ Phase 2 — Optuna 자동 탐색 (2026-04-12, PR #186):** 완료. 위 "최근 완료" 참조.

상세: `.agent/discussions/20260412-rl-dqn-upgrade-optuna.md`

### RL 실시간 추론 파이프라인 (선행 조건: 위 Phase 1~2 + 분봉 40영업일)

장중 매 5분 분봉 기반 RL 추론. PPO primary. 기존 인프라(WebSocket→Redis→분봉 집계) 활용.
변경: `unified_scheduler.py` 장중 스케줄 + `rl_runner.py` 분봉 obs + 유상태 position.
상세: `.agent/discussions/20260412-rl-realtime-inference-model-selection.md`
상세: `.agent/discussions/20260412-rl-multiframe-data-algorithm-fit.md`

### S3 Lifecycle 설정 (코드 변경 없음)

클라우드 전환 시 tick_data/ prefix에 30일→IA, 90일→Glacier IR 적용. 콘솔 설정만.

### 틱+일봉 통합 분석 레이어 (Phase 1 대기 — 분봉 40영업일 축적 필요)

Phase 0 완료 (PR #178~#180). 분봉 데이터 축적 시작.
**Phase 1 (40영업일 후):** RL 분봉 피처 2개 (vwap_deviation, volume_skew)
**Phase 2 (Phase 1 검증 후):** LLM 장중 패턴 컨텍스트

### ✅ 클라우드 마이그레이션 완료 (2026-04-17, PR #190~#192)

**서버:** Oracle Cloud ARM64 (152.67.223.37, ubuntu, 4 OCPU/24GB, 200GB).
**배포:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (prod override).
**스토리지:** Cloudflare R2 (`alpha-datalake` 버킷, S3v4). MinIO는 `--profile minio-local`로 폴백.
**LLM 인증:** CLI/OAuth 마운트 (`~/.claude`, `~/.codex`, `~/.config/gcloud`) + `CLAUDE_CODE_OAUTH_TOKEN` 환경변수. OpenAI는 더미 key(미사용).
**DB 시드:** instruments 2,770건(KOSPI 949 + KOSDAQ 1,821), trading_universe 3건.
**검증 결과:** smoke ✅ / health ✅ / R2 list ✅ (Gate B 통과).
**남은 작업:** Budget Alert $0 설정(콘솔), S3 Lifecycle(tick_data 30d→IA/90d→Glacier IR).
상세: `docs/oracle-cloud-setup.md` + `docs/cloud-migration-phases.md`

---

## 📋 보류 항목

- 뉴스/리서치 자동 검색 (SearchAgent) — 보류
- Decision Transformer — 분봉 6개월+ 축적 후 재검토
- ~~코드 린트 자동화~~ — 완료 (pre-commit hook + CI test/ 추가)
- 오래된 데이터 자동 아카이브 — 데이터가 더 쌓이면
- DB 정리 크론 (7일 초과 틱 파티션 DROP) — 용량 > 5GB 시
---

*Last updated: 2026-04-17 (클라우드 마이그레이션 완료 — Oracle ARM64 + Cloudflare R2)*
