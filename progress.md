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
Step 7           글로벌 데이터 레이크       ██████████  100% ✅
Step 7b          Airflow 비교 스파이크     █████████░   90% 🔧
Step 8           KIS WebSocket 실시간      ████████░░   80% 🔧
Step 8a          WS heartbeat+health 연동  ██████████  100% ✅
Step 9           코드 추상화 (Factory)     █████░░░░░   50% 🔧 (후순위)
Step 10          백테스트 시뮬레이션       █████████░   90% 🔧 (Signal Replay + API 잔여)
안정화 스프린트   Step 10 검증 + CI 정리   ██████████  100% ✅
K3s LLM 인증     Claude CLI + Gemini ADC  ██████████  100% ✅
KIS 모의투자      체결 동기화 + 지정가     ██████████  100% ✅
벤치마크          pgbench/k6/fio/asyncpg   ██████████  100% ✅
빈 테이블 활성화  9개 테이블               ██████████  100% ✅
```

---

## ✅ 최근 완료 (2026-04-09 ~ 04-10)

### Step 9 Phase 1: 코드 추상화 (상수 + Settings 단일화) — PR #107~110
- `src/constants.py` 신규 생성: `PAPER_TRADING_INITIAL_CAPITAL`, `DEFAULT_*_MODEL` 상수
- Agent 1: Broker/DB 초기자본 12곳 → 상수 교체 (PR #107)
- Agent 2: 서비스/API 계열 초기자본 8곳 → 상수 교체 (PR #109)
- Agent 3: LLM 기본 모델명 6파일 12곳 → 상수 교체 (PR #108)
- Agent 4: os.environ.get() 6건 → get_settings() 전환 + config.py에 5개 Settings 필드 추가 (PR #110)
- CORS alias를 기존 `CORS_ORIGINS`로 유지 (breaking change 방지)
- db_logger HOSTNAME은 시스템 변수이므로 os.environ.get 의도적 잔존
- 612 tests passed, 0 failed

### Observability DDL — (미커밋 → PR #110에 포함)
- `scripts/db/init_db.py`에 event_logs, error_logs 테이블 DDL 추가

---

## ✅ 이전 완료 (2026-03-31 ~ 04-08)

### 핵심만 요약 (상세는 git log 참조)
- Secret 단일 소스화 SOPS+age — PR #104 (postgres 비번 drift 재발 방지)
- Gen 데이터 격리 alpha_gen_db — PR #105 (실 DB 오염 방지, profiles: [gen] 옵트인)
- RL adaptive split ε-greedy bandit — PR #102 (사이클마다 동적 split 비율 선택)
- Observability empty_signal events — PR #106 (Strategy B/RL 빈 시그널 구조화 로깅)
- KIS 모의투자 지정가 주문 + 체결 동기화 — PR #89/#92
- 장외 Orchestrator cycle 스킵 — PR #93 (LLM 한도 낭비 방지)
- 성능 벤치마크 5종 — PR #95 (N+1→배치 5.7배, p95 64ms)
- 빈 테이블 9개 활성화 — PR #97
- deploy-local.sh 1커맨드 배포 — PR #91

---

## ✅ 안정화 스프린트 (2026-04-10) — 완료

Step 10 백테스트 4개 PR(#111~#114) 병렬 머지 후, PR #115~#121로 통합 검증 완료.
E2E 9/9 passed, Docker 8서비스 healthy, gen 격리 정상. 746 tests passed.

---

## 🔜 다음 작업

### Step 8: 배치 설정 환경변수화 (WS_TICK_BATCH_SIZE / WS_TICK_FLUSH_INTERVAL) ✅
- [x] `config.py`에 `ws_tick_batch_size` (int, ge=1, le=2000, default=100) + `ws_tick_flush_interval` (float, ge=0.1, le=30.0, default=1.0) 추가
- [x] `collector.py` — 모듈 상수 `TICK_BUFFER_MAX`/`TICK_BUFFER_FLUSH_SEC` 삭제, `__init__`에서 Settings 캐시, `_flush_tick_buffer`에서 인스턴스 변수 참조
- [x] `.env.example`에 `# ── WebSocket Tick Collection` 섹션 + 2줄 추가
- [x] 테스트 통과 확인 — 737 passed, 0 failed
- K8s ConfigMap은 Step 8 안정화 시 반영 (P2)

---

## 🔄 진행 중 / 미완료

### Step 7: 글로벌 데이터 레이크 ✅
- [x] 테이블 생성 (markets, instruments, ohlcv_daily 파티셔닝)
- [x] KR 2,771 + US ~6,595종목, 11.5M행 / 1.94GB 수집 완료
- [x] src/ 코드 ohlcv_daily 전환 완료 (queries/models/collector/API/RL)
- [x] 레거시 market_data는 gen_collector dual-write만 잔존

### Step 7b: Airflow 비교 스파이크
- [x] docker-compose.airflow.yml + DAG 6/6 SUCCESS
- [x] 비교 문서 작성 완료 (docs/airflow-comparison.md)
- [ ] Airflow UI 스크린샷 캡처

### Step 8: KIS WebSocket 실시간
- [x] WebSocket 연결 구현 (collector.py — websockets, kis_websocket_url)
- [x] 실시간 틱 수집 → Redis latest_ticks + DB 저장 경로 구현
- [x] **approval_key Redis 캐싱** — TTL 22h Redis 캐싱 + `_ensure_ws_approval_key()` 구현 완료, 739 tests passed
- [x] **시그니처 정비** — `_ws_collect_loop` 분리 + `MAX_TICKERS_PER_WS` 상수 (다중 연결 분할 준비), 752 tests passed
- [ ] 다중 연결 확장 (asyncio.gather 청크별 병렬 호출)
- [ ] WebSocket 재연결/장애 복구 안정화 검증

### Step 8a: WebSocket heartbeat + health_check 연동 ✅ (2026-04-10)
**문제:** WS 끊어져도 heartbeat 갱신 계속 → 컨테이너 healthy → 모니터링 공백
- [x] `redis_client.py` — set_heartbeat() Hash 확장 (status/mode/last_data_at/error_count) + get_heartbeat_detail()
- [x] `collector.py` — _beat()에서 WS 상태 반영 (ok/degraded/error, websocket/fdr/idle) + 에러/폴백 시 즉시 반영
- [x] `scripts/docker_healthcheck.py` — 신규 (Redis heartbeat 키+status 체크)
- [x] `docker-compose.yml` — worker healthcheck → docker_healthcheck.py (start_period 60s)
- [x] `scripts/health_check.py` — heartbeat status 체크 추가 (check_heartbeats)
- [x] K8s probe — livenessProbe + readinessProbe 분리 (k8s/base/worker.yaml)
- [x] `docs/HEARTBEAT.md` — Hash 스키마, 상태 정의, Docker/K8s 체크, Orchestrator 모니터링 → "계획" 이동
- [x] 단위 테스트 13개 (heartbeat Hash CRUD, docker_healthcheck 5시나리오, status 매핑)
- [x] 회귀 테스트: 752 passed, 0 failed
- [ ] (후속 PR) Orchestrator 모니터링 + Telegram 알림

### Step 9: 코드 추상화 (후순위 — 모델 교체 시 착수)
- [x] Phase 1: constants.py + 매직 넘버 교체 (18곳+, 7파일) — PR #107~110 ✅
- [x] Phase 1: os.environ.get() → Settings 전환 (6건, 5파일) — PR #110 ✅
- [ ] Phase 2: src/llm/factory.py 생성 + 모델명 통합
- [x] 테스트: 737 passed, 0 failed

### Step 10: 백테스트 시뮬레이션 (안정화 완료, Signal Replay 착수 예정)
**PR #111~#114 코드 + PR #115~#121 안정화 완료.** E2E 9/9 passed, Docker healthy, gen 격리 정상. 746 tests.
- [x] 구현 구조: `src/backtest/` — PR #111~#114
- [x] CLI 기동 + 인터페이스 불일치 수정 — PR #115
- [x] 통합 테스트 2개 (engine E2E + optimizer pipeline) — PR #117
- [x] `fetch_ohlcv_range()` + RL state mismatch fix — PR #118
- [x] CLI `_load_ohlcv()` → `fetch_ohlcv_range` 전환 + fixture CSV — PR #119
- [x] 실데이터 RL 백테스트 E2E — 9/9 passed (BUY 6 + SELL 6 = 12 trades, seed 42 재현성 확인)
- [x] Docker Compose 전체 기동 검증 — 8서비스 healthy, smoke test + health check 통과
- [x] gen 격리 검증 — alpha_gen_db 2,340건 적재, alpha_db 0건 (격리 정상)
- [ ] Strategy A/B: Signal Replay — RL E2E 이후
- [ ] API GET 엔드포인트 — P3

---

## 📋 로드맵 (미정 / 보류)

- Step 8a WebSocket heartbeat + health_check 연동 — 즉시 착수 가능 (인프라 안정성)
- Step 8 WebSocket 안정화 — Step 8a 이후 재검토 (현 전략이 일봉 기반이라 미사용)
- Step 9 Phase 2 LLM Factory — 모델 교체 시 착수
- 멀티 타임프레임 데이터 파이프라인 — Step 8 이후
- RL 하이퍼파라미터 자동 탐색 (Optuna) — 보류
- Pre-commit Lint 자동화 (ruff --fix) — 틈날 때
- 스토리지 계층화 (Hot/Cold) — 성능 이슈 발생 시
- SearchAgent (SearXNG) — 보류
- 대시보드 UI — Step 10 이후

---

*Last updated: 2026-04-10*
