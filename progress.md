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
Step 8           KIS WebSocket 실시간      ████████░░   80% 🔧 ← 다음 작업
Step 8a          WS heartbeat+health 연동  ██████████  100% ✅
Step 9           코드 추상화 (Factory)     █████░░░░░   50% 🔧 (후순위)
Step 10          백테스트 시뮬레이션       ██████████  100% ✅
Step 12          대시보드 UI (백테스트)    ██████████  100% ✅
안정화 스프린트   Step 10 검증 + CI 정리   ██████████  100% ✅
K3s LLM 인증     Claude CLI + Gemini ADC  ██████████  100% ✅
KIS 모의투자      체결 동기화 + 지정가     ██████████  100% ✅
벤치마크          pgbench/k6/fio/asyncpg   ██████████  100% ✅
빈 테이블 활성화  9개 테이블               ██████████  100% ✅
```

---

## ✅ 최근 완료 (2026-04-10)

### 4에이전트 병렬 스프린트 — PR #125~#127

4에이전트 병렬 실행으로 4개 태스크를 동시 완료.

| Agent | 작업 | PR |
|-------|------|----|
| 1 | Signal Replay 통합 테스트 (ReplaySignalSource 단위 + Engine 통합) | #125 |
| 2 | 백테스트 UI 페이지 (목록+상세+차트, Recharts LineChart/BarChart) | #126 |
| 3 | Orchestrator heartbeat 모니터링 + Telegram 알림 | (커밋 `25dae41`) |
| 4 | Backtest API GET 엔드포인트 3개 (runs/detail/daily) | #127 |

### Step 8a 완성: heartbeat 모니터링 체인 완료
- PR #123: WS 배치 환경변수화 + approval_key Redis 캐싱 + heartbeat Hash 확장
- PR #124: Docker/K8s healthcheck 연동
- PR #125~#127: Orchestrator가 heartbeat 읽고 이상 시 Telegram 알림 발송

### Step 10 완성: 백테스트 전체 파이프라인 완료
- RL 백테스트 엔진 + CLI → Signal Replay 통합 테스트 → API 3개 → UI 시각화
- 전략 A/B/RL 모두 백테스트 가능, 결과 조회 + 시각화까지 E2E 완성

---

## ✅ 이전 완료 (2026-03-31 ~ 04-09)

### 핵심만 요약 (상세는 git log 참조)
- Step 9 Phase 1: constants.py + 매직 넘버 교체 + Settings 단일화 — PR #107~110
- Secret 단일 소스화 SOPS+age — PR #104
- Gen 데이터 격리 alpha_gen_db — PR #105
- RL adaptive split ε-greedy bandit — PR #102
- Observability empty_signal events — PR #106
- 안정화 스프린트 — PR #115~#121 (E2E 9/9, Docker healthy, gen 격리 정상, 746 tests)

---

## 🔄 진행 중 / 미완료

### Step 7b: Airflow 비교 스파이크
- [x] docker-compose.airflow.yml + DAG 6/6 SUCCESS
- [x] 비교 문서 작성 완료 (docs/airflow-comparison.md)
- [ ] Airflow UI 스크린샷 캡처

### Step 8: KIS WebSocket 실시간 — 모듈 분리 + 다중 연결 + 재연결 강화

**배경:** 현재 `collector.py` 1128줄에 일봉/Yahoo/분봉/실시간 수집이 전부 섞여 있다.
틱 기반 전략을 추가하려면 WebSocket 코드를 독립적으로 수정할 수 있어야 하고,
종목 수 확대(40종목 초과)에 대비한 다중 연결과, 틱 유실을 최소화하는 재연결 강화가 필요하다.

**팀 토론 결정 (2026-04-10):** 틱 전략 필수 + 클린 코드 추상화 전제로 범위 재정의.

#### Phase 1: collector.py 패키지 전환 + 모듈 분리
- [ ] `src/agents/collector/` 패키지로 전환 (기존 `from src.agents.collector import CollectorAgent` 호환 유지)
- [ ] `_base.py`: 공통 로직 (heartbeat, ticker resolve, Redis 캐시)
- [ ] `__init__.py`: CollectorAgent facade (Mixin 합성, 외부 인터페이스 유지)

#### Phase 2a: `_realtime.py` — WebSocket 실시간 수집 전담
- [ ] WebSocket 연결/파서/버퍼 로직을 `_realtime.py`로 이동
- [ ] **다중 연결**: `asyncio.gather`로 `MAX_TICKERS_PER_WS`(40) 단위 청크 병렬 수집. 한 청크 실패해도 나머지 계속 수집 (`return_exceptions=True`)
- [ ] **재연결 강화**: jitter 추가 (`random.uniform(0,1)`), 최대 대기 30초, 개별 청크만 FDR 폴백
- [ ] **TickData DTO**: 틱 전용 데이터 모델 신규 생성. 현재 `MarketDataPoint`(일봉 스키마)에 틱을 억지로 넣는 문제 해결. DB flush 시에만 변환

#### Phase 2b: `_daily.py` + `_historical.py` — 일봉/과거 수집 전담
- [ ] FDR/Yahoo 일봉 수집 → `_daily.py`
- [ ] 과거 데이터 bulk 수집 → `_historical.py`

#### Phase 3: K8s + 환경변수 + 테스트
- [ ] K8s ConfigMap에 4개 환경변수 반영: `WS_TICK_BATCH_SIZE`, `WS_TICK_FLUSH_INTERVAL`, `WS_RECONNECT_MAX`, `MAX_TICKERS_PER_WS`
- [ ] `config.py`에 `ws_reconnect_max`, `max_tickers_per_ws` Settings 필드 추가
- [ ] `test/test_collector_ws.py` 신규: 파서 유닛 + 재연결 mock + 다중연결 + 버퍼 조건 (10+ tests)
- [ ] `test/fixtures/kis_ws_packets.json` synthetic fixture

**실행 순서:** Phase 1 → (Phase 2a, 2b 병렬) → Phase 3

### Step 9: 코드 추상화 (후순위)
- [x] Phase 1: constants.py + 매직 넘버 교체 + Settings 단일화 — PR #107~110
- [ ] Phase 2: src/llm/factory.py 생성 + 모델명 통합
- 후순위 이유: 모델 교체 계획 없음, constants.py로 충분

---

## 📋 로드맵 (미정 / 보류)

- **Step 8b** 틱 전용 DB + 멀티 타임프레임 — Step 8 완료 후 착수 (상세는 roadmap.md)
- Step 9 Phase 2 LLM Factory — 모델 교체 시 착수
- RL 하이퍼파라미터 자동 탐색 (Optuna) — 보류
- Pre-commit Lint 자동화 (ruff --fix) — 틈날 때
- 스토리지 계층화 (Hot/Cold) — 성능 이슈 발생 시
- SearchAgent (SearXNG) — 보류

---

*Last updated: 2026-04-10*
