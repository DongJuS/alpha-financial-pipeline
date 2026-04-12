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

---

## 🔄 다음 작업

### 로컬 데이터 축적 (진행 중)

로컬 K3s에서 틱/분봉 데이터를 먼저 축적. 클라우드 비용 발생을 늦추면서 RL 선행 조건 충족.
클라우드 전환 시 `pg_dump` + R2 sync로 이전.

**✅ 해결 (2026-04-11, PR #138):**
1. `collector.run()` 복원 → `collect_daily_bars()` 위임. 08:30 KST 일봉 수집 정상화.
2. 별도 `tick-collector` 서비스 신규 추가 — 장애 격리(틱↔매매 독립), 독립 재시작. K3s 배포 필요.

### S3 Lifecycle 설정 (코드 변경 없음)

클라우드 전환 시 tick_data/ prefix에 30일→IA, 90일→Glacier IR 적용. 콘솔 설정만.

### 틱+일봉 통합 분석 레이어 (Phase 0 착수 대기)

수집은 별개 유지, 분석은 통합. 안 C(DB 90일 + S3 Parquet 아카이브) 채택.

**Phase 0 (즉시 — PR 3개):**
1. `ohlcv_minute` 테이블 DDL + `aggregate_ticks_to_minutes()` + 15:50 크론잡
2. S3 Parquet 아카이브 (`archive_minute_bars()`) + 월 1회 파티션 관리 크론
3. `UnifiedMarketData` 빌더 + `compute_intraday_features()`

**Phase 1 (40영업일 후):** RL 분봉 피처 2개 (vwap_deviation, volume_skew)
**Phase 2 (Phase 1 검증 후):** LLM 장중 패턴 컨텍스트
- 상세 (아키텍처): `.agent/discussions/20260412-unified-market-data-architecture.md`
- 상세 (구현): `.agent/discussions/20260412-unified-market-data-implementation.md`
- 상세 (RL 피처): `.agent/discussions/20260411-rl-intraday-feature-expansion.md`

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
- RL 하이퍼파라미터 자동 탐색 (Optuna) — 보류
- 코드 린트 자동화 — 틈날 때
- 오래된 데이터 자동 아카이브 — 데이터가 더 쌓이면
- DB 정리 크론 (7일 초과 틱 파티션 DROP) — 용량 > 5GB 시
- `ohlcv_minute` 집계 테이블 — 분봉 쿼리 > 50ms 시

---

*Last updated: 2026-04-12 (cleaned)*
