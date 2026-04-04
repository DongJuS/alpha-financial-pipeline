# 📝 progress.md — 현재 세션 진척도

> 에이전트와 "현재 어디까지 했는지" 맞추는 단기 기억 파일입니다.
> 완료된 이력은 `progress-archive.md`를 참조하세요.
> **정리 정책**: 150줄 초과 시 완료+코드 유추 가능 항목 삭제. 200줄 초과 시 오래된 완료 항목 강제 삭제.

---

## 📊 Phase 진행 현황

```
Phase 1~12       코어 시스템               ██████████  100% ✅
Step 3           RL 부트스트랩 + 블렌딩     ██████████  100% ✅
Step 4           K3s 프로덕션 배포          ██████████  100% ✅
Step 5           Alpha 안정화              ██████████  100% ✅
Step 6           테스트 스위트 정비         ██████████  100% ✅
Step 7           글로벌 데이터 레이크       ████████░░   80% 🔧
Step 7b          Airflow 비교 스파이크     ████████░░   80% 🔧
Step 8           KIS WebSocket 실시간      ░░░░░░░░░░    0% 📋
Step 9           코드 추상화 (Factory)     ░░░░░░░░░░    0% 📋
K3s LLM 인증     Claude CLI + Gemini ADC  ██████████  100% ✅
KIS 모의투자      체결 동기화 + 지정가     ██████████  100% ✅
벤치마크          pgbench/k6/fio/asyncpg   ██████████  100% ✅
빈 테이블 활성화  9개 테이블               ██████████  100% ✅
```

---

## ✅ 최근 완료 (2026-03-31 ~ 04-01)

### K3s LLM 인증 자동화 — PR #88
- Dockerfile prod에 Node.js + Claude CLI 설치
- Kustomize secretGenerator로 llm-credentials Secret 자동 생성
- Claude: setup-token → CLAUDE_CODE_OAUTH_TOKEN env 주입
- Gemini: gcloud ADC → Secret file 마운트
- 트러블슈팅 11건 해결 (subPath 마운트, Secret key 점 문제, OOM 등)

### KIS 모의투자 주문 수정 — PR #89
- ORD_DVSN="01" + ORD_UNPR="0" → 전 주문 거절 원인 발견
- 모의투자: 지정가(00) + 현재가, 실거래: 시장가(06) 지원
- 삼성전자 10건 + SK하이닉스 5건 실거래 체결 확인

### KIS 체결 동기화 — PR #92
- sync_pending_orders(): PENDING → FILLED 자동 DB 업데이트
- KIS 당일체결조회(inquire-daily-ccld)로 매 cycle 동기화
- 15건 PENDING → FILLED 동기화 확인

### 장외 Orchestrator cycle 스킵 — PR #93
- 장외(15:30~09:00)에 cycle 즉시 return → LLM 200회 한도 낭비 방지

### RL auto retrain 활성화 — PR #94
- ORCH_ENABLE_RL_AUTO_RETRAIN=true (16:40 KST)
- 04/01 16:41 실행 완료: 7종목 학습, 6 성공, 0 배포

### CI/CD Docker 이미지 태그 소문자 — PR #90
- github.repository 대문자 → dongjus/alpha-financial-pipeline 하드코딩

### 성능 벤치마크 스위트 — PR #95
- pgbench, sysbench, k6, fio, asyncpg 5개 도구
- 실측: N+1→배치 5.7배, 프루닝 3배, COPY 76K rows/sec, p95 64ms

### 빈 테이블 9개 활성화 — PR #97
- trade_history, portfolio_positions, collector_errors
- operational_audits, aggregate_risk_snapshots, daily_rankings
- paper_trading_runs (+ notification_history, strategy_promotions 기존 활성)

### deploy-local.sh — PR #91
- git pull → docker build → kubectl apply → rollout restart → 검증 1커맨드

---

## 🔄 진행 중 / 미완료

### Step 7: 글로벌 데이터 레이크
- [x] 테이블 생성 (markets, instruments, ohlcv_daily 파티셔닝)
- [x] KR 2,771종목 수집 완료
- [x] US ~6,595종목 수집 완료
- [x] 총 11,513,963건 / 9,366종목 / 1.94GB
- [ ] 기존 market_data → ohlcv_daily 마이그레이션
- [ ] 기존 src/ 코드 신규 테이블 구조 적용

### Step 7b: Airflow 비교 스파이크
- [x] docker-compose.airflow.yml + DAG 6/6 SUCCESS
- [ ] 스크린샷 + 비교 기록

### Step 9: 코드 추상화 (📋 계획 완료, 미착수)
- [ ] Phase 1: src/constants.py 생성 + 매직 넘버 교체 (6곳)
- [ ] Phase 2: src/llm/factory.py 생성 + 모델명 통합
- [ ] Phase 3: os.environ.get() → Settings 경유 교체

---

## 📋 로드맵 (미정)

- Step 8: KIS WebSocket 실시간 틱 수집 (20→40→다중 연결)
- RL 하이퍼파라미터 자동 탐색 (Optuna)
- Pre-commit Lint 자동화 (ruff --fix)
- 스토리지 계층화 간소화 (PostgreSQL 1년 유지 + S3 전체)
- SearchAgent (SearXNG) — 보류

---

*Last updated: 2026-04-03*
