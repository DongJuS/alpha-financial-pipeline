# 📡 api_spec.md — API 엔드포인트 상세 설계

> 모든 API 엔드포인트의 명세를 정의합니다.
> 에이전트가 API 구현 시 이 문서를 기준으로 작업합니다.

---

## 📌 기본 정보

- **Base URL:** `http://localhost:8000/api/v1`
- **인증 방식:** Bearer Token (JWT)
- **응답 형식:** JSON
- **타임스탬프:** ISO 8601, KST 오프셋 (`+09:00`)
- **금액 단위:** 원화(KRW), 정수형 (소수점 없음)
- **목록 응답:** `{"data": [], "meta": {"total": 0, "page": 1, "per_page": 20}}`

---

## 🔐 인증

### POST `/auth/login`
- **설명:** 사용자 로그인 (JWT 토큰 발급)
- **Request Body:**
  ```json
  { "email": "string", "password": "string" }
  ```
- **Response (200):**
  ```json
  { "token": "string", "expires_in": 86400 }
  ```

---

## 👤 사용자

### GET `/users/me`
- **설명:** 현재 사용자 정보 조회
- **인증:** 필요
- **Response (200):**
  ```json
  { "id": "string", "email": "string", "name": "string" }
  ```

---

## 📈 시장 데이터

### GET `/market/tickers`
- **설명:** 추적 중인 종목 목록
- **Query Params:** `market=KOSPI|KOSDAQ`, `page`, `per_page`

### GET `/market/ohlcv/{ticker}`
- **설명:** 특정 종목 OHLCV 이력 조회
- **Query Params:** `from=2026-01-01`, `to=2026-03-12`, `interval=daily|tick`
- **Response (200):**
  ```json
  {
    "ticker": "005930", "name": "삼성전자",
    "data": [
      {
        "timestamp_kst": "2026-03-12T15:30:00+09:00",
        "open": 72000, "high": 73500, "low": 71800, "close": 73000,
        "volume": 12345678, "change_pct": 1.39
      }
    ]
  }
  ```

### GET `/market/quote/{ticker}`
- **설명:** 종목 최신 실시간 시세
- **Response (200):**
  ```json
  {
    "ticker": "005930", "name": "삼성전자",
    "current_price": 73000, "change": 1000, "change_pct": 1.39,
    "volume": 12345678, "updated_at": "2026-03-12T10:32:15+09:00"
  }
  ```

### GET `/market/index`
- **설명:** KOSPI/KOSDAQ 지수 현황
- **Response (200):**
  ```json
  {
    "kospi": { "value": 2750.32, "change_pct": 0.45 },
    "kosdaq": { "value": 870.15, "change_pct": -0.12 }
  }
  ```

---

## 🤖 에이전트 관리

### GET `/agents/status`
- **설명:** 모든 에이전트 헬스 상태 조회
- **Response (200):**
  ```json
  {
    "agents": [
      {
        "agent_id": "collector_agent", "status": "healthy",
        "last_action": "KOSPI 장 마감 수집 완료",
        "metrics": { "api_latency_ms": 120, "error_count_last_hour": 0 },
        "updated_at": "2026-03-12T06:32:15Z"
      }
    ]
  }
  ```

### GET `/agents/{agent_id}/logs`
- **설명:** 특정 에이전트 최근 로그
- **Query Params:** `limit=50`, `level=INFO|WARNING|ERROR`

### POST `/agents/{agent_id}/restart`
- **설명:** 에이전트 재시작 트리거 (관리자 전용)

### POST `/agents/dual-execution/run`
- **설명:** 2개 실행 에이전트를 자동 순차 실행 (빠른 흐름 + 꼼꼼 검증)
- **인증:** 필요
- **Request Body:**
  ```json
  {
    "task": "docker 컨테이너 기반 실행 구성 점검",
    "context": ["API 라우팅 유지", "문서 동기화"]
  }
  ```
- **Response (200):**
  ```json
  {
    "task": "docker 컨테이너 기반 실행 구성 점검",
    "generated_at": "2026-03-12T09:00:00+00:00",
    "fast_flow": {
      "agent_id": "fast_flow_agent",
      "mode": "fast-overview",
      "summary": "작업을 큰 흐름 기준으로 분해...",
      "priorities": ["1. 컨테이너/배포 먼저 고정"],
      "execution_tracks": ["현재 상태를 5분 내 스캔..."],
      "quick_risks": ["환경별 포트/네트워크 차이로 연결 실패 가능성"]
    },
    "slow_meticulous": {
      "agent_id": "slow_meticulous_agent",
      "mode": "slow-meticulous",
      "assumptions": ["기존 API 계약과 DB 스키마 호환성 유지"],
      "detailed_steps": [
        {
          "step": "[1] 컨테이너/배포 변경 구현",
          "why": "컨테이너/배포 영역이 전체 작업 성공률에 직접 영향",
          "done_criteria": "코드/설정/문서가 서로 모순 없이 반영됨"
        }
      ],
      "validation_checks": ["정적 점검 또는 컴파일 단계에서 문법 오류가 없어야 함"],
      "blockers_to_watch": ["외부 의존 서비스 미기동 시 검증 결과 왜곡 가능"]
    },
    "combined": {
      "execution_mode": "fast-first-then-meticulous",
      "immediate_actions": [
        "fast_flow_agent 계획으로 우선순위 고정",
        "slow_meticulous_agent 체크리스트로 누락 검증",
        "검증 통과 후 상세 커밋 메시지로 결과 고정"
      ],
      "verification_gate": ["핵심 API 경로 또는 스크립트 실행 결과가 성공이어야 함"],
      "completion_definition": ["핵심 변경이 실행 가능한 상태로 반영됨"]
    }
  }
  ```

---

## 🧠 전략 시그널

### GET `/strategy/a/signals`
- **설명:** Strategy A (Tournament) 최신 시그널
- **Query Params:** `date=2026-03-12`
- **Response (200):**
  ```json
  {
    "date": "2026-03-12", "winner_agent_id": "predictor_3",
    "signals": [
      {
        "agent_id": "predictor_3", "llm_model": "gpt-4o",
        "ticker": "005930", "signal": "BUY", "confidence": 0.78,
        "target_price": 75000, "stop_loss": 71000,
        "reasoning_summary": "5일 이동평균 돌파, 외국인 순매수 전환"
      }
    ]
  }
  ```

### GET `/strategy/a/tournament`
- **설명:** 토너먼트 점수 및 순위
- **Query Params:** `days=5`
- **Response (200):**
  ```json
  {
    "period_days": 5,
    "rankings": [
      {
        "agent_id": "predictor_3", "llm_model": "gpt-4o",
        "persona": "모멘텀 (Mo)", "rolling_accuracy": 0.80,
        "correct": 4, "total": 5, "is_current_winner": true
      }
    ]
  }
  ```

### GET `/strategy/b/signals`
- **설명:** Strategy B (Consensus) 최신 합의 시그널
- **Query Params:** `date=2026-03-12`

### GET `/strategy/b/debate/{debate_id}`
- **설명:** Strategy B 토론 전문 조회 (감사 목적)
- **Response (200):**
  ```json
  {
    "id": 42, "date": "2026-03-12", "ticker": "005930",
    "rounds": 2, "consensus_reached": true, "final_signal": "BUY",
    "proposer_content": "삼성전자 기술적 매수 근거...",
    "challenger1_content": "단기 리스크 요인으로...",
    "challenger2_content": "금리 환경에서...",
    "synthesizer_content": "종합 분석 결과...",
    "created_at": "2026-03-12T08:55:00+09:00"
  }
  ```

### GET `/strategy/combined`
- **설명:** 두 전략 블렌딩된 최종 시그널
- **Response (200):**
  ```json
  {
    "blend_ratio": 0.5,
    "signals": [
      {
        "ticker": "005930",
        "strategy_a_signal": "BUY", "strategy_b_signal": "BUY",
        "combined_signal": "BUY", "combined_confidence": 0.80,
        "conflict": false
      }
    ]
  }
  ```

---

## 💼 포트폴리오

### GET `/portfolio/positions`
- **설명:** 현재 보유 포지션 조회
- **Response (200):**
  ```json
  {
    "total_value": 10250000, "total_pnl": 250000, "total_pnl_pct": 2.5, "is_paper": true,
    "positions": [
      {
        "ticker": "005930", "name": "삼성전자",
        "quantity": 100, "avg_price": 72000, "current_price": 73000,
        "unrealized_pnl": 100000, "weight_pct": 70.73
      }
    ]
  }
  ```

### GET `/portfolio/history`
- **설명:** 거래 이력 조회
- **Query Params:** `page`, `per_page`, `from`, `to`, `ticker`

### GET `/portfolio/performance`
- **설명:** 성과 지표 (P&L, 수익률, Sharpe 등)
- **Query Params:** `period=daily|weekly|monthly|all`
- **Response (200):**
  ```json
  {
    "period": "monthly", "return_pct": 5.32,
    "max_drawdown_pct": -1.8, "sharpe_ratio": 1.42,
    "win_rate": 0.65, "total_trades": 23,
    "kospi_benchmark_pct": 2.1
  }
  ```

### GET `/portfolio/performance-series`
- **설명:** 일자별 누적 성과 시계열 (Portfolio vs KOSPI Proxy)
- **Query Params:** `period=daily|weekly|monthly|all`
- **Response (200):**
  ```json
  {
    "period": "monthly",
    "points": [
      {
        "date": "2026-03-01",
        "portfolio_return_pct": 1.2,
        "benchmark_return_pct": 0.8,
        "realized_pnl_cum": 120000,
        "trade_count": 3
      }
    ]
  }
  ```

### GET `/portfolio/config`
- **설명:** 현재 전략/리스크/모드 설정 조회 (관리자 전용)
- **Response (200):**
  ```json
  {
    "strategy_blend_ratio": 0.5,
    "max_position_pct": 20,
    "daily_loss_limit_pct": 3,
    "is_paper_trading": true,
    "enable_paper_trading": true,
    "enable_real_trading": false,
    "primary_account_scope": "paper",
    "market_hours_enforced": true,
    "market_status": "after_hours"
  }
  ```

### GET `/portfolio/readiness`
- **설명:** 실거래 전환 readiness 점검 결과 조회 (관리자 전용)
- **주요 체크 항목:** 자격증명, DB/Redis, 리스크 한도, 페이퍼 운용 일수, 운영 감사(`security`, `risk_rules`) 최신 통과 여부
- **Response (200):**
  ```json
  {
    "ready": false,
    "critical_ok": false,
    "high_ok": false,
    "checks": [
      {"key":"cred:KIS_APP_KEY","ok":true,"message":"KIS_APP_KEY 설정 정상","severity":"critical"},
      {"key":"paper:track_record","ok":false,"message":"페이퍼 운용 일수 부족(active_days=7, required=30, trades=14)","severity":"critical"},
      {"key":"audit:security","ok":true,"message":"보안 감사 정상(passed=true, age_hours=3.1, max_age_days=7)","severity":"critical"}
    ]
  }
  ```

### GET `/portfolio/readiness/audits`
- **설명:** 운영 감사(`operational_audits`) 및 실거래 모드 전환 감사(`real_trading_audit`) 최근 이력 조회 (관리자 전용)
- **Query Params:** `limit`(1~200), `audit_type=security|risk_rules`(선택)
- **Response (200):**
  ```json
  {
    "operational_audits": [
      {
        "id": 12,
        "audit_type": "security",
        "passed": true,
        "summary": "보안 감사 통과",
        "details": {"passed": true},
        "executed_by": "scripts/preflight_real_trading.py",
        "created_at": "2026-03-12T13:41:25.000000+00:00"
      }
    ],
    "mode_switch_audits": [
      {
        "id": 7,
        "requested_at": "2026-03-12T13:15:00.000000+00:00",
        "requested_by_email": "admin@example.com",
        "requested_by_user_id": "uuid-or-sub",
        "requested_mode_is_paper": false,
        "confirmation_code_ok": true,
        "readiness_passed": false,
        "readiness_summary": {"ready": false},
        "applied": false,
        "message": "실거래 전환 차단: 확인 코드 또는 readiness 점검 실패"
      }
    ]
  }
  ```

### POST `/portfolio/config`
- **설명:** 전략 블렌드 비율, 리스크 한도 설정
- **Request Body:**
  ```json
  { "strategy_blend_ratio": 0.6, "max_position_pct": 20, "daily_loss_limit_pct": 3 }
  ```

### POST `/portfolio/trading-mode`
- **설명:** 페이퍼/실거래 모드 전환 (관리자 전용)
- **Request Body:**
  ```json
  {
    "enable_paper_trading": true,
    "enable_real_trading": true,
    "primary_account_scope": "paper",
    "confirmation_code": "string"
  }
  ```
- **동작:** 실거래 활성화(`enable_real_trading=true`) 시 confirmation_code + readiness 점검을 모두 통과해야 적용됩니다.

---

## 🔔 알림

### GET `/notifications/history`
- **설명:** 최근 Telegram 발송 이력 조회
- **Query Params:** `limit=20`

### GET `/notifications/preferences`
- **설명:** 현재 알림 설정 조회

### POST `/notifications/test`
- **설명:** 테스트 Telegram 알림 발송
- **Request Body:** `{ "message": "string" }`

### PUT `/notifications/preferences`
- **설명:** 알림 설정 변경
- **Request Body:**
  ```json
  {
    "morning_brief": true, "trade_alerts": true,
    "circuit_breaker": true, "daily_report": true, "weekly_summary": true
  }
  ```

---

## 🚨 에러 코드

| 코드 | 상태 | 설명 |
|------|------|------|
| 400 | Bad Request | 잘못된 요청 파라미터 |
| 401 | Unauthorized | 인증 실패 |
| 403 | Forbidden | 권한 없음 |
| 404 | Not Found | 리소스 없음 |
| 409 | Conflict | 이미 진행 중인 작업 있음 |
| 429 | Too Many Requests | 레이트 리밋 초과 |
| 500 | Internal Server Error | 서버 내부 오류 |

---

## 🧩 확장 API 메모 (통합 테스트 진행 중)

아래 엔드포인트는 RL Trading, Search/Scraping, 5-agent 의사결정 계층을 위한 확장 메모입니다.
기존 코어 API를 대체하지 않으며, 최종 주문 권한은 계속 `PortfolioManagerAgent`에 있습니다.

### POST `/agents/review-council/run`
- **설명:** 5개 planning agent를 호출해 개발 방향성과 우선순위를 생성
- **인증:** 필요
- **Request Body:**
  ```json
  {
    "task": "RL Trading과 Search/Scraping 통합 우선순위 결정",
    "scope": ["docs", "api", "storage"],
    "constraints": [
      "Strategy A/B 유지",
      "PortfolioManager 주문 권한 유지",
      "README는 통합 테스트 진행 중 표기"
    ]
  }
  ```
- **Response (200):**
  ```json
  {
    "task": "RL Trading과 Search/Scraping 통합 우선순위 결정",
    "agents": {
      "fast_flow_agent": {
        "summary": "검색 계약 먼저 고정 후 RL lane 병렬 준비"
      },
      "slow_meticulous_agent": {
        "checkpoints": ["storage schema", "evaluation gate", "audit trail"]
      },
      "optimist_agent": {
        "opportunities": ["Strategy B 품질 향상", "RL feature 확장"]
      },
      "pessimist_agent": {
        "risks": ["출처 미저장", "과적합 정책의 조기 연결"]
      },
      "decision_director_agent": {
        "selected_direction": "search-first-then-rl-offline",
        "why": "추적 가능한 데이터 계약이 먼저 필요하기 때문"
      }
    }
  }
  ```

### POST `/rl/training-jobs`
- **설명:** RL 학습 작업 생성
- **Request Body:**
  ```json
  {
    "dataset_version": "rl_ds_v1",
    "policy_family": "ppo",
    "tickers": ["005930", "000660"],
    "feature_profile": "market_plus_research_v1"
  }
  ```
- **Response (202):**
  ```json
  {
    "job_id": "rl_train_001",
    "status": "queued",
    "dataset_version": "rl_ds_v1"
  }
  ```

### GET `/rl/training-jobs/{job_id}`
- **설명:** RL 학습 작업 상태/결과 조회

### GET `/rl/evaluations`
- **설명:** RL 평가 결과 목록 조회
- **Query Params:** `policy_id`, `dataset_version`, `status=approved|hold|rejected`

### GET `/rl/policies`
- **설명:** 등록된 RL 정책 목록 조회

### GET `/rl/policies/active`
- **설명:** 현재 활성 정책 또는 shadow 정책 조회

### POST `/research/search-jobs`
- **설명:** 검색/스크래핑 파이프라인 실행
- **Request Body:**
  ```json
  {
    "ticker": "005930",
    "query": "삼성전자 AI 반도체 공급망 2026",
    "intent": "research",
    "max_results": 10
  }
  ```
- **Response (202):**
  ```json
  {
    "job_id": "research_001",
    "status": "queued"
  }
  ```

### GET `/research/search-jobs/{job_id}`
- **설명:** 검색 job 상태 조회

### GET `/research/search-jobs/{job_id}/results`
- **설명:** 검색 결과, source, extraction 요약 조회

### GET `/research/sources/{source_id}`
- **설명:** 원문 source 메타데이터 및 구조화 결과 조회

### GET `/research/extractions/{extraction_id}`
- **설명:** Claude 기반 추출 결과 조회

### 설계 메모
- 검색 파이프라인은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI`를 전제로 합니다.
- RL 정책은 학습/평가/등록 단계를 거친 뒤에만 활성 정책이 될 수 있습니다.
- `review-council` API는 개발 의사결정용이며 주문이나 거래 상태를 직접 변경하지 않습니다.

*Last updated: 2026-03-14*
