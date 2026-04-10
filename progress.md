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
Step 9           코드 추상화 (Factory)     █████░░░░░   50% 🔧 (후순위)
Step 10          백테스트 시뮬레이션       ██████░░░░   60% 🔧 (코드 머지됨, 통합 검증 필요)
안정화 스프린트   Step 10 검증 + CI 정리   ░░░░░░░░░░    0% 📋 ← 현재
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

## 🔧 안정화 스프린트 (2026-04-10 ~)

Step 10 백테스트 4개 PR(#111~#114) 병렬 머지 후, 통합 검증 없이 다음 기능으로 넘어가면
인터페이스 불일치·DDL 누락·CI 신뢰도 하락이 축적된다.
신규 기능 개발 전에 아래 안정화 작업을 완료한다.

### P0 — 즉시 (오늘 오전)

| # | 항목 | 상세 | 상태 |
|---|------|------|------|
| 1 | integration test CI 분리 | `test/integration/conftest.py`에 `pytestmark=[pytest.mark.integration]` 추가. 100건 실패는 서버 미기동(httpx.ConnectError)이 원인이며 코드 결함 아님. `-m "not integration"`으로 유닛만 실행 가능하게 | [ ] |
| 2 | backtest DDL 확인 | `scripts/db/init_db.py`에 backtest_runs·backtest_daily 테이블 DDL이 포함되었는지 확인. 누락 시 추가 | [ ] |
| 3 | backtest CLI 기동 확인 | `python -m src.backtest --help` 실행하여 import 에러·의존성 누락 없이 기동되는지 검증 | [ ] |
| 4 | requirements.txt 확인 | Step 10 PR 4건에서 추가된 신규 패키지 여부 확인. 누락 시 다른 환경에서 import 실패 | [ ] |
| 5 | 미커밋 변경 정리 | roadmap.md 정리 + progress.md 업데이트 + test_portfolio_manager.py 1줄 변경을 커밋 또는 revert | [ ] |

### P1 — 오늘 내

| # | 항목 | 상세 | 상태 |
|---|------|------|------|
| 6 | 실데이터 RL 백테스트 검증 | ohlcv_daily 실데이터로 1종목 RL 백테스트 CLI 실행. engine→signal_source→metrics 경로 end-to-end 확인 | [ ] |
| 7 | Step 10 통합 테스트 추가 | engine ↔ signal_source ↔ optimizer 경로를 커버하는 테스트 1~2개. 유닛 테스트(mock)만으로는 모듈 간 인터페이스 불일치를 잡지 못함 | [ ] |

### P2 — 이번 주

| # | 항목 | 상세 | 상태 |
|---|------|------|------|
| 8 | Docker Compose 전체 기동 검증 | Step 10 머지 후 `docker compose up --build` → healthy → smoke_test.py 통과 확인 | [ ] |
| 9 | gen 격리 주말 사이클 검증 | `--profile gen` 기동 → alpha_gen_db에만 데이터 적재되는지 확인 (PR #105 이후 미검증) | [ ] |

### 리스크

- backtest CLI가 DB 연결 필수이면 로컬 PostgreSQL 또는 Docker 필요
- integration test mark 분리 후 CLAUDE.md의 테스트 실행 명령 업데이트 필요
- 4 PR 병렬 머지 인터페이스 불일치 발견 시 핫픽스 우선

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
- [ ] 다중 연결 확장 (20→40종목 동시 구독)
- [ ] WebSocket 재연결/장애 복구 안정화 검증

### Step 9: 코드 추상화 (후순위 — 모델 교체 시 착수)
- [x] Phase 1: constants.py + 매직 넘버 교체 (18곳+, 7파일) — PR #107~110 ✅
- [x] Phase 1: os.environ.get() → Settings 전환 (6건, 5파일) — PR #110 ✅
- [ ] Phase 2: src/llm/factory.py 생성 + 모델명 통합
- [x] 테스트: 612 passed, 0 failed

### Step 10: 백테스트 시뮬레이션 (코드 머지 완료 — 통합 검증은 안정화 스프린트에서)
**PR #111~#114 머지 완료 (2026-04-10).** 실데이터 end-to-end 검증은 안정화 스프린트 #6~7 참조.
- [x] 구현 구조: `src/backtest/` (engine.py, metrics.py, models.py, signal_source.py, cli.py, optimizer.py, cost_model.py, repository.py)
- [x] RL 백테스트 구현 (gymnasium 환경 재사용, LLM 비용 없음) — PR #113
- [x] 성과 지표 산출 (수익률, 샤프 비율, MDD, 승률) — PR #112
- [x] 수수료 0.015% + 세금 0.18% 반영한 시뮬레이션 체결 — PR #111 cost_model.py
- [x] 체결 시뮬: 인메모리 포지션 추적, 고정 슬리피지 3bps — PR #113 engine.py
- [x] 인터페이스: CLI (`python -m src.backtest`) — PR #114
- [x] 가중치 최적화: 그리드 서치 + 샤프 비율 최대화 — PR #114 optimizer.py
- [ ] train/test 기간 분리 (과적합 방지) — 검증 필요
- [ ] Strategy A/B: Signal Replay (predictions DB 재생) — P1 이후
- [ ] 저장: DB 2테이블 (backtest_runs 메타 + backtest_daily 상세) — DDL 확인 필요
- [ ] API GET 엔드포인트 — P3

---

## 📋 로드맵 (미정 / 보류)

- Step 8 WebSocket 안정화 — Step 10 이후 재검토 (현 전략이 일봉 기반이라 미사용)
- Step 9 Phase 2 LLM Factory — 모델 교체 시 착수
- 멀티 타임프레임 데이터 파이프라인 — Step 8 이후
- RL 하이퍼파라미터 자동 탐색 (Optuna) — 보류
- Pre-commit Lint 자동화 (ruff --fix) — 틈날 때
- 스토리지 계층화 (Hot/Cold) — 성능 이슈 발생 시
- SearchAgent (SearXNG) — 보류
- 대시보드 UI — Step 10 이후

---

*Last updated: 2026-04-10*
