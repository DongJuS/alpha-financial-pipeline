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
K3s DB에 일봉 시딩 완료 (3종목 2,394건, 2023-01~2026-04).
클라우드 배포 전 QA Round 1 완료 (테스트 46개 파일, 12,846줄 추가).
다음은 QA Round 2 → 로컬 데이터 축적 → 클라우드 전환 → RL 피처 확장 순서로 진행.

**완료된 것:**
- 3가지 AI 전략으로 자동 매매 (모의투자 검증 완료)
- 한국+미국 주가 데이터 1,150만 행 수집
- 실시간 시세 수집 (증권사 WebSocket, 다중 연결, 자동 재연결)
- 틱 전용 저장소 + 분봉 집계 + gap backfill (Step 8b)
- Predictor에 장중 1시간봉 통합 + S3 hour 파티셔닝·크론 flush (Step 8b 후속)
- AI 모델 호출 통합 LLMRouter (Step 9 Phase 2)
- 과거 데이터로 전략 성과 검증 (백테스트) + 웹 대시보드
- 에이전트 건강 모니터링 → Telegram 자동 알림
- K3s(경량 쿠버네티스) 서버 배포, 자동 테스트 798개 통과
- alpha_db 정리: gen heartbeat 오염 제거 + 무의미한 predictions 정리
- **클라우드 배포 전 QA Round 1 (PR #140)**: 4-에이전트 병렬 QA, 테스트 커버리지 대폭 확대

**다음 목표:**
- 로컬에서 틱 데이터 축적 시작 (클라우드 전환 전, 비용 절감)
- RL 분봉 피처 확장 (분봉 데이터 40영업일 축적 후)
- 클라우드 전환: Hetzner CX22 + Cloudflare R2 (월 ~5,000원)

---

## 완료된 마일스톤

> 상세 이력은 `roadmap-archive.md` 참조.

---

## 진행 중 마일스톤

### 로컬 데이터 축적 (진행 중)

**왜 필요한가:** 클라우드 전환 전에 로컬에서 틱/분봉 데이터를 먼저 축적. 비용 발생을 늦추면서 RL 40영업일 선행 조건을 충족시킨다.
K3s DB에 일봉 시딩 완료 (3종목 2,394건). 틱 수집은 장중 WebSocket으로 자동 진행.
클라우드 전환 시 `pg_dump` + R2 sync로 이전.

**✅ tick-collector 서비스 분리 완료 (PR #138):** collector.run() 복원 + 별도 tick-collector 서비스. 장애 격리(틱↔매매 독립) + 독립 재시작. unified_scheduler에서 tick 크론잡 2개 제거(12→10 잡). K3s 배포 후 데이터 축적 시작.

### RL 분봉 피처 확장 (선행 조건: 분봉 40영업일 축적)

**왜 필요한가:** RL이 일봉 6개 피처만 사용 중. 분봉 파생 피처(vwap_deviation, volume_skew)를 추가하면 장중 패턴 포착 가능.

**설계 토론 완료 (2026-04-11):** Tabular Q-learning 유지 + 분봉 파생 일봉 피처 2개 추가. 상태 공간 27→243, 에피소드·시드 증가로 보완.
선행 조건: Step 8b 완료 + 분봉 데이터 40영업일 축적.
- 상세: `.agent/discussions/20260411-rl-intraday-feature-expansion.md`

### 클라우드 배포 전 QA (Round 1 완료, Round 2 미착수)

**왜 필요한가:** 클라우드 전환 전에 전체 시스템 품질을 검증. 소스 133개 파일(31,040줄) 대비 테스트 커버리지 ~55% → 80%+ 목표.

**Round 1 완료 (PR #140):** 4개 AI QA 에이전트 병렬 작업. 46개 테스트 파일, 12,846줄 추가. src/ 수정 없음.
- Agent 1: orchestrator/RL/ranking 테스트 ~152개
- Agent 2: collector/gen/datalake/tick 테스트 ~185개
- Agent 3: API 통합/E2E/보안 테스트
- Agent 4: DB/config/scheduler/LLM/conftest ~272개 + 공용 픽스처

**Round 2 미착수:** Round 1 품질 검증에서 발견된 커버리지 갭 보강.
- orchestrator independent portfolio 모드, dynamic weight 최적화
- RL GymTradingEnv 래퍼, get_policy_mode paper/real 분기
- ranking sector heatmap, tie-handling
- strategy_a/b, portfolio_manager, rl_trading_v2 에지케이스 (Round 1 누락 확인됨)
- Agent 2~4 품질 검증 + 보강

파티셔닝 문서: `.agent/partition/20260411-cloud-pre-qa-partition.md`

### RL 레지스트리 자동 동기화 ✅

instruments 테이블을 종목 SoT로 채택. 하드코딩 전면 제거, RL bootstrap 자동 등록. PR #136.

### 일봉 수집 종목 확대 + 스크리너 도입 ✅

수집 100종목(FDR 무료) + 스크리너 필터링 → 전략 실행 하드캡 10종목. PR #137.

### Predictor MTF 실효과 검증

**왜 필요한가:** 분봉 통합(1시간봉) 구현 완료했으나, 실제 예측 품질이 올라갔는지 미검증.
일봉만 사용한 예측 vs 일봉+분봉 예측의 시그널 품질을 백테스트 또는 모의투자 로그로 비교해야 투자 판단의 근거가 된다.

### 클라우드 전환 (날짜 미정)

Hetzner CX22 + Cloudflare R2 조합(월 ~5,000원)으로 결정.
비용 발생 시점을 최대한 늦추는 원칙. Docker Compose 배포 + Cold migration + 로컬 2주 유지 롤백 전략 확정.
- 상세 (실행 계획): `.agent/discussions/20260411-cloud-migration-execution-plan.md`

**LLM 인증·비용 전략 결정 (2026-04-11):** CLI 구독 인증 1순위 + API Key 자동 fallback.
Claude `setup-token`(1년 유효) + Codex `device-auth` + Gemini ADC로 구독료만 사용.
토큰 만료 시 동일 provider SDK로 자동 전환 + 1분 주기 Health 체크 + Telegram 알림.
모델 다운그레이드 불필요 (Opus 유지).
- 상세 (인프라·비용): `.agent/discussions/20260411-roadmap-priority-cost-optimization.md`
- 상세 (LLM 인증): `.agent/discussions/20260411-cloud-llm-auth-cost-optimization.md`

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
