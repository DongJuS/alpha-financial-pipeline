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

### RL 모델 DQN 업그레이드 + Ensemble + Optuna (설계 완료, 구현 대기)

Tabular Q → SB3 통합 trainer(DQN/A2C/PPO) + Optuna 자동 탐색. MacBook 로컬 학습 → 서버 배포.

**Phase 1 — SB3 통합 Trainer + Ensemble:**
1. `rl_environment_v2.py` — 연속 상태 Gymnasium 환경
2. `rl_trading_sb3.py` — SB3 통합 trainer (DQN/A2C/PPO)
3. 프로파일 3개 (dqn/a2c/ppo)
4. `rl_continuous_improver.py` + `rl_runner.py` + `rl_policy_store_v2.py` — SB3 분기
5. 테스트

**Phase 2 — Optuna:**
1. `rl_hyperopt.py` — study 관리, 알고리즘별 search space
2. `requirements.txt` + `.agent/tech_stack.md` — `optuna>=3.0,<4.0`

상세: `.agent/discussions/20260412-rl-dqn-upgrade-optuna.md`
상세: `.agent/discussions/20260412-rl-algorithm-research-ensemble.md`
상세: `.agent/discussions/20260412-rl-dqn-to-ppo-migration.md`

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

### 클라우드 LLM 인증·비용 전략 (설계 완료)

CLI 구독 1순위 + API Key 자동 fallback + 1분 주기 Health 감시. 구현 대상:
1. `claude_client.py` / `gpt_client.py` — CLI→SDK 내부 fallback 추가
2. `cli_bridge.py` — 인증 오류 전용 예외 분리
3. `unified_scheduler.py` — 1분 주기 LLM auth health 크론 잡
4. `notifier.py` — CLI 토큰 만료 알림
상세: `.agent/discussions/20260411-cloud-llm-auth-cost-optimization.md`

### 클라우드 마이그레이션 실행 (날짜 미정)

Hetzner CX22 + Cloudflare R2 결정 완료. Docker Compose 배포 + Cold migration + 로컬 2주 유지 롤백 전략 확정.
상세: `.agent/discussions/20260411-cloud-migration-execution-plan.md`

---

## 📋 보류 항목

- 뉴스/리서치 자동 검색 (SearchAgent) — 보류
- Decision Transformer — 분봉 6개월+ 축적 후 재검토
- 코드 린트 자동화 — 틈날 때
- 오래된 데이터 자동 아카이브 — 데이터가 더 쌓이면
- DB 정리 크론 (7일 초과 틱 파티션 DROP) — 용량 > 5GB 시
---

*Last updated: 2026-04-12*
