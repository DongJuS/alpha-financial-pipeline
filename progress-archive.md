# 🗄️ progress-archive.md — 완료된 작업 이력

> **이 파일은 progress.md에서 분리된 아카이브입니다.**
> 활성 스프린트와 미완료 항목은 `progress.md`를 참조하세요.

---

## Step 4 — Bitnami 인프라 전환 + Kustomize 분리 (2026-03-29)

PR #63 (Helm), PR #64 (Kustomize).
- PR #63: 커스텀 StatefulSet 삭제 → Bitnami chart values 작성 (`k8s/helm/bitnami-values/`)
- PR #64: base에서 인프라 yaml 삭제, configmap/secrets Bitnami 서비스명 정합, overlays dev/prod 보강
- **왜**: Stateful 인프라는 Bitnami chart가 직접 작성보다 안전. 앱과 인프라 관심사 분리.

---

## Step 3 — RL 부트스트랩 + 3전략 동시 블렌딩 (2026-03-29)

PR #32/#33/#34. 장 전(RL 학습) → 장 중(A/B/RL 블렌딩) → 장 후(재학습+가중치 조정) 운영 흐름 완성.
- `scripts/rl_bootstrap.py` — FDR 720일 시딩→학습→활성 정책 등록
- `orchestrator.py` — 3전략 병렬 실행 + graceful fallback
- `unified_scheduler.py` — 장 전/중/후 9개 잡 스케줄

## Step 5 — Alpha 안정화 + e2e 검증 (2026-03-29)

PR #48/#49/#51/#52/#53/#54.
- docker compose 8서비스 전부 healthy
- Collector → Orchestrator 1사이클 재현: 수집 24건 → 3전략 병렬 → 블렌딩 fallback → S3 Parquet 저장 (16초)
- `docker-compose.yml` — `db-init` 서비스 추가, worker healthcheck 수정, worker `GEN_API_URL` 추가

## Step 6 — 테스트 스위트 완전 정비 (2026-03-29)

PR #44/#45/#50. 462 → 557 passed (+95건). 0 failed.
- event loop 오염 근본 해결, 인터페이스 불일치 수정, Python 3.11 전환

## Step 4 — K3s 프로덕션 배포 (2026-03-29, 대부분 완료)

PR #38/#39/#41/#51/#63/#64. 잔여: deploy.sh 수정 + K3s 실배포.
- Helm chart + Bitnami values + Kustomize base/overlays + CI/CD + Dockerfile multi-stage

---

## Phase 12 — 블로그 자동 포스팅 (2026-03-28)

| 파일 | 내용 |
|------|------|
| `src/utils/blog_client.py` | BloggerClient (OAuth refresh, publish/update/find_by_title) |
| `src/utils/discussion_renderer.py` | MD→HTML 변환, 프론트매터 파싱 |

---

## Phase 11 — N-way 블렌딩 + StrategyRunner Registry (2026-03-16)

- StrategyRunner Protocol + StrategyRegistry, N-way 블렌딩, N+1 쿼리 최적화

---

## Phase 10 — 피드백 루프 파이프라인 (2026-03-16)

- S3 Parquet 읽기, predictions+outcomes 매칭, RL 재학습 파이프라인

---

## Phase 9 — RL Trading Lane (2026-03-15)

- RL V2, Gymnasium TradingEnv, walk-forward, shadow inference

---

## Phase 8 — Search Foundation (2026-03-15)

- SearXNG → Claude 감성 분석, SearchRunner

---

## Phase 7 — S3 Data Lake (2026-03-15)

- MinIO + Parquet, Hive 파티셔닝

---

## Phase 6 — 독립 포트폴리오 인프라 (2026-03-15)

- VirtualBroker, 전략 승격, 합산 리스크

---

## Phase 1~5 — 인프라·에이전트·전략·UI (2026-03-12~13)

인프라 → 코어 에이전트 → Strategy A/B → 대시보드 → 운용 검증

---

## Step 8b: 틱 데이터 전용 저장소 (2026-04-11)

틱이 ohlcv_daily에 억지 변환되어 마지막 1건만 남던 기술부채 해결.
tick_data PostgreSQL 파티션 테이블 도입 (일 117만 틱, 55MB — TimescaleDB/DuckDB 기각, PG로 충분).
WebSocket gap 감지 + KIS REST backfill 추가.

---

## Step 9 Phase 2: LLMRouter (2026-04-11)

AI 모델 호출 코드가 6개 파일에 흩어져 있어 LLMRouter로 통합.
provider 판별 + fallback 체인을 한 곳에서 관리.

---

## 클라우드 전환 결정 변경 (2026-04-11)

AWS Lightsail(월 3.7만원) → Hetzner CX22 + Cloudflare R2(월 ~5,000원)로 변경.
비용 발생 시점을 최대한 늦추는 원칙 유지.

---

## Step 8b 후속: Predictor 분봉 통합 + S3 틱 최적화 (2026-04-11)

Predictor에 당일 1시간봉 통합(get_ohlcv_bars('1hour') → LLM 프롬프트). 분봉 없으면 일봉만 fallback.
S3: _make_s3_key(hour=N) Hive-style 파티셔닝. flush 분리: 매 틱 S3 PUT 제거 → 15:40 KST 크론 일괄 flush.
PR #133.

---

## alpha_db 정리 + 스케줄러 연동 (2026-04-11)

- gen_collector heartbeat 오염 제거 (370건), 무의미한 predictions 정리 (confidence=0, 5,637건)
- K3s DB 일봉 시딩: 005930/000660/259960 × 2023-01~2026-04 (2,394건)
- **스케줄러 미연동 버그 수정**: `run_orchestrator_worker.py`가 `unified_scheduler`를 시작하지 않아 크론 잡(일봉 수집 등) 10개가 미실행. `start_unified_scheduler()` 호출 추가.
- 스케줄러 실패해도 Orchestrator는 계속 진행하도록 방어 처리.

---

## 일봉 수집 종목 확대 + 스크리너 도입 (2026-04-11)

3종목 고정 수집/실행 → 100종목 수집 + 스크리너 필터링 + 전략 실행 하드캡 10종목으로 전환.
**왜:** 포트폴리오 분산 불가 + RL/백테스트 데이터 부족. 전 종목 LLM 실행은 비용 폭발이라 스크리너(거래량 급등 OR 변동률)로 1차 필터링 후 상위 N개만 전략에 넘기는 2-tier 구조 채택. 수집 비용 0원(FDR 무료), 스크리너 비용 0원(연산), LLM 비용 하드캡 고정.
PR #137.

---

## RL 레지스트리 자동 동기화 (2026-04-11)

instruments 테이블을 종목 SoT로 채택하여 Orchestrator·RL 스케줄러의 하드코딩 전면 제거.
**왜:** 종목 추가 시 registry.json + worker + orchestrator 3곳을 수동 수정해야 했음. DB를 single source of truth로 통일하여 종목 관리 포인트를 1곳으로 축소. RL bootstrap 시 DB에 있으나 registry에 없는 종목 자동 등록.
PR #136.
