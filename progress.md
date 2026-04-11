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

## 🔄 다음 작업

### instruments + trading_universe 후속 작업 (코드 완료, 배포·시딩 미완)

코드 리팩터링은 완료(PR 대기). 하지만 아직 **실제 DB에 데이터가 없다.**
시스템이 종목을 찾으려면 아래 3단계가 필요하다:

1. **K3s DB 마이그레이션** — instruments DDL 경량화(컬럼 축소) + trading_universe 테이블 생성 + stock_master → krx_stock_master 테이블 리네임을 실서버 DB에 반영
2. **instruments 시딩** — krx_stock_master(2,700+ 종목 카탈로그)에서 실제 운용할 종목을 instruments(경량 등록 테이블)에 등록. `scripts/db/seed_all_instruments.py` 실행.
3. **trading_universe 시딩** — "가상투자 계좌에서 이 종목들을 운용하겠다"는 매핑 데이터를 넣어야 함. 예: `(paper, 005930.KS)`, `(paper, 000660.KS)`. **시드 스크립트 미작성.**

3번이 완료되어야 `list_tickers(mode="paper")`가 종목을 반환하고, Orchestrator/Predictor/RL이 정상 작동한다.
상세: `.agent/discussions/20260411-instruments-trading-universe-design.md`

### ✅ 클라우드 배포 전 QA Round 2 (완료, PR #143, #144)

### 로컬 데이터 축적 (진행 중)

로컬 K3s에서 틱/분봉 데이터를 먼저 축적. 클라우드 비용 발생을 늦추면서 RL 선행 조건 충족.
클라우드 전환 시 `pg_dump` + R2 sync로 이전.

**✅ 해결 (2026-04-11, PR #138):**
1. `collector.run()` 복원 → `collect_daily_bars()` 위임. 08:30 KST 일봉 수집 정상화.
2. 별도 `tick-collector` 서비스 신규 추가 — 장애 격리(틱↔매매 독립), 독립 재시작. K3s 배포 필요.

### S3 Lifecycle 설정 (코드 변경 없음)

클라우드 전환 시 tick_data/ prefix에 30일→IA, 90일→Glacier IR 적용. 콘솔 설정만.

### RL 분봉 피처 확장 (선행 조건: 분봉 40영업일 축적)

vwap_deviation + volume_skew 2개 피처 추가. 데이터 축적 후 구현 시작.
상세: `.agent/discussions/20260411-rl-intraday-feature-expansion.md`

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

*Last updated: 2026-04-12*
