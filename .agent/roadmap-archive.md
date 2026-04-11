# roadmap-archive.md — 완료된 마일스톤 이력

> 이 파일은 roadmap.md에서 분리된 아카이브입니다.
> 활성 마일스톤과 진행 중 항목은 `.agent/roadmap.md`를 참조하세요.

---

### Step 3 — RL 강화학습 + 3전략 블렌딩 ✅

과거 주가 데이터로 AI 모델을 학습시키고, 학습된 모델이 매매 신호를 내는 RL(강화학습) 전략을 추가했다.
기존 Strategy A(토너먼트)·B(토론)와 함께 3가지 전략을 가중 평균으로 합산하여 최종 매매 판단을 내린다.

---

### Step 4 — K3s 프로덕션 배포 ✅

시스템 전체를 K3s(경량 쿠버네티스)에 배포했다.
Helm(인프라 설정)과 Kustomize(앱 설정)를 병행하여 1커맨드(`deploy-local.sh`)로 전체 배포 가능.

---

### Step 5 — 시스템 안정화 ✅

Docker Compose로 8개 서비스(DB, 캐시, 스토리지, API, Worker, UI 등)를 동시에 띄우고,
모든 서비스가 정상(healthy)인 상태에서 매매 1사이클이 완주되는 것을 확인했다.

---

### Step 6 — 테스트 정비 ✅

자동 테스트를 462개 → 798개로 확장하고, 비동기 이벤트 루프 오염 문제를 해결했다.
테스트가 독립적으로 통과하여 코드 변경 시 기존 기능이 안 깨지는지 자동 검증할 수 있다.

---

### Step 7 — 글로벌 데이터 레이크 ✅

한국 2,771종목 + 미국 6,595종목의 과거 주가를 총 1,150만 행(1.94GB) 수집했다.
날짜별로 자동 분할 저장(파티셔닝)하여 대량 데이터도 빠르게 조회할 수 있다.

---

### Step 8 — 실시간 시세 수집 안정화 ✅

증권사(한국투자증권) WebSocket으로 초 단위 실시간 시세(틱)를 수집하는 인프라를 완성했다.
- 1128줄짜리 수집 코드를 역할별 5개 모듈로 분리 (실시간/일봉/과거/공통/인터페이스)
- 종목 40개 초과 시 자동으로 여러 WebSocket 연결을 열어 병렬 수집
- 연결 끊김 시 자동 재연결 (랜덤 지연 + 최대 30초 대기, 한 연결이 죽어도 나머지는 계속 수집)
- 틱 전용 데이터 모델 생성 (일봉 스키마에 틱을 억지로 끼워넣던 문제 해결)

---

### Step 8a — 서버 건강 모니터링 + Telegram 알림 ✅

에이전트 heartbeat(90초) → Redis → Docker/K8s 자동 재시작 → OrchestratorAgent 점검 → Telegram 알림.

---

### Step 8b — 틱 데이터 전용 저장소 + 분봉 집계 ✅

tick_data PostgreSQL 파티션 테이블(일 117만 틱, 55MB). insert_tick_batch() + get_ohlcv_bars() 분봉 집계.
WebSocket gap 감지 + KIS REST backfill. price INTEGER 저장(float 오차 방지).

---

### Step 8b 후속 — Predictor 분봉 통합 + S3 틱 최적화 ✅

Predictor에 당일 1시간봉 통합(get_ohlcv_bars('1hour') → LLM 프롬프트). 분봉 없으면 일봉만 fallback.
S3: _make_s3_key(hour=N) Hive-style 2단계 파티셔닝. flush 분리: 매 틱 S3 PUT → 15:40 KST 크론 일괄 flush.

---

### Step 9 Phase 1 — 코드 정리 (상수 + 설정 통합) ✅

constants.py에 매직넘버 통합, Settings 클래스로 환경변수 읽기 통합.

---

### Step 9 Phase 2 — LLMRouter ✅

Claude/GPT/Gemini 호출 코드를 LLMRouter로 통합. provider 판별 + fallback 체인을 한 곳에서 관리.

---

### Step 10 — 전략 백테스트 ✅

RL/Strategy A/B 과거 데이터 성과 검증. 수익률·샤프·MDD·승률. CLI 실행, DB 저장, REST API 3개.

---

### Step 12 — 백테스트 대시보드 UI ✅

목록 페이지(전략별 필터, 수익률·샤프·MDD 테이블) + 상세 페이지(성과 지표 카드, 가치 곡선, 수익률 차트).

---

### 데이터 압축 최적화 ✅

Parquet 압축 Snappy→zstd(30~40% 감소). PostgreSQL 긴 텍스트 lz4 압축.
