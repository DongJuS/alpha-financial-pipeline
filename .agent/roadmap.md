# roadmap.md — 프로젝트 전체 마일스톤

이 파일은 이 저장소의 canonical roadmap입니다.
마일스톤 수준의 방향과 원칙만 작성합니다. 구체적인 체크리스트는 progress.md를 참조하세요.
완료된 이력은 roadmap-archive.md를 참조하세요.

> **문서 연결 정책**: 마일스톤에 관련 discussion 파일이 있으면 `- 상세: .agent/discussions/파일명.md` 형태로 링크를 기재한다.

---

## 이 프로젝트가 하는 일

한국 주식(KOSPI/KOSDAQ)을 AI가 자동으로 매매하는 시스템이다.
5개의 AI 에이전트(데이터 수집, 분석, 매매, 조율, 알림)가 협업하며,
3가지 전략(A: 토너먼트, B: 토론, RL: 강화학습)을 동시에 운용한다.

기술 스택: Python 3.11 + FastAPI (백엔드), React 18 + TypeScript (프론트),
PostgreSQL (DB), Redis (캐시/메시징), S3 (데이터 레이크), K3s (배포)

---

## 현재 상태 (2026-04-11)

핵심 매매 기능 + 실시간 틱 수집 + 틱 저장소 + AI 모델 통합까지 완성.
다음은 틱 데이터를 활용한 전략 확장과 클라우드 배포가 남아있다.

**완료된 것:**
- 3가지 AI 전략으로 자동 매매 (모의투자 검증 완료)
- 한국+미국 주가 데이터 1,150만 행 수집
- 실시간 시세 수집 (증권사 WebSocket, 다중 연결, 자동 재연결)
- 틱 전용 저장소 + 분봉 집계 + gap backfill (Step 8b)
- AI 모델 호출 통합 LLMRouter (Step 9 Phase 2)
- 과거 데이터로 전략 성과 검증 (백테스트) + 웹 대시보드
- 에이전트 건강 모니터링 → Telegram 자동 알림
- K3s(경량 쿠버네티스) 서버 배포, 자동 테스트 798개 통과

**다음 목표:**
- Predictor 분봉 피처 주입 → RL feature vector 확장
- S3 틱 최적화 (date/hour 파티셔닝, flush 주기 분리)
- 클라우드 전환: Hetzner CX22 + Cloudflare R2 (월 ~5,000원)

---

## 완료된 마일스톤

### Step 8a — 서버 건강 모니터링 + Telegram 알림 ✅

에이전트가 죽거나 이상해지면 자동으로 감지하고 Telegram으로 알리는 전체 체인을 완성했다:
1. 각 에이전트가 90초마다 "나 살아있어"라는 heartbeat 신호를 Redis에 기록
2. Docker/K8s가 heartbeat를 확인하여 이상 시 컨테이너 자동 재시작
3. OrchestratorAgent가 전체 에이전트의 상태를 매 사이클마다 점검
4. 이상(error/degraded/offline) 발견 시 Telegram으로 즉시 알림

### Step 9 Phase 1 — 코드 정리 (상수 + 설정 통합) ✅

코드 곳곳에 흩어져 있던 숫자 값(초기 자본금, AI 모델 이름 등)을 한 파일(`constants.py`)에 모으고,
환경변수 읽기 코드를 Settings 클래스로 통합했다. AI 에이전트 4개를 동시에 돌려 1시간 만에 완료.

### Step 10 — 전략 백테스트 ✅

"과거에 이 전략을 썼으면 얼마를 벌었(잃었)을까?"를 검증하는 백테스트 시스템을 완성했다:
- RL/Strategy A/Strategy B 모두 과거 데이터로 성과 검증 가능
- 성과 지표: 수익률, 연환산 수익률, 샤프 비율(위험 대비 수익), MDD(최대 낙폭), 승률
- CLI로 실행, 결과는 DB에 저장, REST API 3개로 조회 가능
- Buy&Hold(그냥 사서 보유) 대비 초과수익률 비교

### Step 12 — 백테스트 대시보드 UI ✅

백테스트 결과를 웹 브라우저에서 시각적으로 볼 수 있는 React 페이지를 만들었다:
- 목록 페이지: 전략별 필터, 수익률·샤프·MDD 테이블, 페이지네이션
- 상세 페이지: 성과 지표 8개 카드, 포트폴리오 가치 곡선 그래프, 일별 수익률 막대 그래프

### 데이터 압축 최적화 ✅

클라우드 저장 비용을 줄이기 위한 압축을 적용했다:
- S3에 저장하는 Parquet 파일 압축을 Snappy → zstd로 변경 (저장 용량 30~40% 감소)
- PostgreSQL의 AI 토론 기록·예측 근거 같은 긴 텍스트 컬럼에 lz4 압축 적용

### Step 8b — 틱 데이터 전용 저장소 + 분봉 집계 ✅

틱이 `ohlcv_daily`에 억지 변환되어 유실되던 기술부채를 해결했다:
- PostgreSQL `tick_data` 파티션 테이블 (일 117만 틱, 55MB — PG로 충분, TimescaleDB/DuckDB 기각)
- `insert_tick_batch()` + `get_ohlcv_bars()` 범용 분봉 집계 (조회 시 SQL 실시간 집계)
- Collector flush → tick_data INSERT (ohlcv_daily 혼재 제거)
- WebSocket gap 감지 + KIS REST backfill + 30분+ Telegram 경고
- price를 INTEGER 저장 (한국 주식 원 단위 정수, float 오차 방지)
- 상세: `.agent/discussions/20260410-step8b-tick-storage-design.md`

### Step 9 Phase 2 — LLMRouter ✅

AI 모델(Claude/GPT/Gemini) 호출 코드가 6개 파일에 흩어져 있던 것을 `LLMRouter`로 통합했다:
- provider 판별 + fallback 체인을 한 곳에서 관리
- 모델 교체 시 LLMRouter만 수정하면 됨
- 상세: `.agent/discussions/20260411-step9-phase2-llm-router.md`

---

## 진행 중 마일스톤

### Predictor 멀티 타임프레임 통합 (Step 8b 후속) ✅

Predictor에 당일 1시간봉 데이터를 통합하여 LLM이 장중 흐름까지 참고하도록 했다.
`_fetch_intraday_bars()` → `get_ohlcv_bars('1hour')` 호출, 프롬프트에 "오늘 장중 1시간봉" 섹션 추가.
분봉 데이터 없으면(장외/주말) 기존처럼 일봉만으로 동작.
- 상세: `.agent/discussions/20260411-step8b-followup-implementation.md`

### RL 분봉 피처 확장 (Step 8b 후속)

**왜 필요한가:** RL이 일봉 6개 피처만 사용 중. 분봉 파생 피처(vwap_deviation, volume_skew)를 추가하면 장중 패턴 포착 가능.

**설계 토론 완료 (2026-04-11):** Tabular Q-learning 유지 + 분봉 파생 일봉 피처 2개 추가. 상태 공간 27→243, 에피소드·시드 증가로 보완.
선행 조건: Step 8b 완료 + 분봉 데이터 40영업일 축적.
- 상세: `.agent/discussions/20260411-rl-intraday-feature-expansion.md`

### S3 틱 최적화 ✅ (Lifecycle 제외)

`_make_s3_key(hour=N)` optional 파라미터로 Hive-style date+hour 2단계 파티셔닝.
`_flush_tick_buffer()`에서 S3 호출 제거 → 장 종료 크론(15:40 KST) `flush_ticks_to_s3()`로 DB→S3 시간대별 일괄 flush.
소량 파일 수만 개 → 시간대별 ~7개 대형 Parquet로 개선.
Lifecycle(30d→IA, 90d→Glacier IR)은 클라우드 전환 시 콘솔 설정.
- 상세: `.agent/discussions/20260411-step8b-followup-implementation.md`

### 클라우드 전환 (날짜 미정)

Hetzner CX22 + Cloudflare R2 조합(월 ~5,000원)으로 결정.
비용 발생 시점을 최대한 늦추는 원칙. 실행 시 배포 순서·데이터 이전·롤백 전략 설계 필요.
- 상세: `.agent/discussions/20260411-roadmap-priority-cost-optimization.md`

---

## 설계 원칙

- **관심사 분리** — 코드가 길어지면 역할별로 모듈을 분리한다. 클린 코드는 기본이다
- **틱 전략은 필수** — 일봉(하루 1번) 전략만으로는 한계. 실시간 데이터 기반 전략 확장을 전제로 설계
- **과도한 설계 금지** — DI 컨테이너, Builder 패턴 등 현재 규모에서 불필요한 패턴 사용 안 함. "추상화가 없어서 버그가 2번 나면 그때 한다"

---

## 장기 로드맵 (트리거 조건 충족 시)

- Delta Lake 도입 — 수집기가 여러 대로 늘어나 같은 테이블에 동시 쓰기가 발생할 때. Parquet 위에 ACID 트랜잭션 + Time Travel 제공
- RocksDB 캐싱 레이어 — 종목 수만 개 이상으로 메타데이터가 Redis 메모리에 안 담길 때. 디스크 기반 키-값 캐시를 Redis 앞에 추가
- 멀티 클라우드 스토리지 추상화 — AWS 외 다른 클라우드(Azure/GCS)로 이전하거나 병행 운영할 때. 현재는 boto3가 S3 호환 API를 이미 추상화하여 불필요
- 전략 패턴 리팩터링 — 종목 100개 이상으로 늘어날 때
- K8s 멀티 클러스터 — 서버 1대로 부족할 때
- SearchAgent (뉴스/리서치 자동 검색) — 보류
- RL 하이퍼파라미터 자동 탐색 (Optuna) — 보류
- 코드 린트 자동화 (ruff) — 틈날 때
