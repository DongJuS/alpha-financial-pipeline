# Alpha — 실시간 금융 데이터 파이프라인

> Real-time financial data pipeline — FDR/KIS data collection → multi-strategy parallel execution → N-way signal blending → automated paper trading on K3s

[![CI](https://github.com/DongJuS/alpha-financial-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/DongJuS/alpha-financial-pipeline/actions/workflows/ci.yml)

## Key Metrics

| | |
|---|---|
| **557 tests** | 100% pass rate, 0 failures |
| **9 scheduled jobs** | Pre-market / Intraday / Post-market automated operations |
| **9,363 instruments** | KR 2,772 + US 6,591 stocks, 21M+ daily OHLCV rows (12-year history) |
| **3 strategies** | A(Tournament) / B(Consensus) / RL(Q-Learning) with N-way blending |
| **6 pods on K3s** | Colima + Helm(infra) + Kustomize(app), verified deployment |
| **16-second cycle** | Collector → Orchestrator → Blending → S3 storage end-to-end |

## RL Trading Performance (Backtest)

Strategy RL (Tabular Q-Learning V2) trained on **real historical data** for 크래프톤(259960.KS):

| Policy | Return | Baseline (Buy&Hold) | Excess Return | Trades | Win Rate | Status |
|--------|--------|---------------------|---------------|--------|----------|--------|
| **Best** | **+47.84%** | -26.58% | **+74.41%p** | 178 | 50.6% | ✅ Approved |
| **2nd** | **+28.73%** | -26.58% | **+55.30%p** | 156 | 51.3% | ✅ Approved |

> In a **-26.58% bear market**, the RL agent achieved +47.84% return (74.41%p excess return).
> Trained with 5-seed multi-learning, holdout validation (335 steps), walk-forward cross-validation.
> ⚠️ Backtest results only. Slippage, execution delay, and market impact are not reflected.

---

## Architecture

```
                        ┌─────────────────────────┐
                        │    Data Sources          │
                        │  KRX · KIS · FDR · MinIO │
                        └────────────┬────────────┘
                                     │
                              CollectorAgent
                          (batch + WebSocket streaming)
                                     │
                              ┌──────┴──────┐
                              │  PostgreSQL  │──► S3 Data Lake
                              │   + Redis    │    (Parquet, Hive-style)
                              └──────┬──────┘
                                     │
                           OrchestratorAgent
                        ┌────────┼────────┬────────┐
                   Strategy A  Strategy B  Strategy RL
                   Tournament  Consensus   Q-Learning V2
                   5 LLM race  4 LLM debate  walk-forward
                        └────────┼────────┴────────┘
                                 │
                        N-way Signal Blending
                     (weighted score + fallback)
                                 │
                        PortfolioManager
                      (paper / real via KIS API)
                                 │
                        ┌────────┴────────┐
                   Telegram Alert    React Dashboard
```

---

## Data Pipeline

이 프로젝트의 핵심은 **데이터 파이프라인**입니다.

| 파이프라인 단계 | 구현 | 비고 |
|---|---|---|
| **배치 수집** | `CollectorAgent` — FDR 일봉 + KIS REST | 08:10~08:30 KST 스케줄 |
| **실시간 수집** | KIS WebSocket → Redis pub/sub | 30초 인터벌, 장중 연속 |
| **백필** | `rl_bootstrap.py` — FDR 720일 자동 시딩 | DB 데이터 부족 시 자동 트리거 |
| **적재** | `datalake.py` → S3 Parquet (Hive-style 파티셔닝) | `data_type/date=YYYY-MM-DD/` |
| **스케줄링** | `unified_scheduler.py` — APScheduler 9개 잡 | Redis NX 분산 락으로 중복 방지 |
| **재시도** | `job_wrapper.py` — 3회 exponential backoff + 이력 기록 | Redis에 잡별 최근 50건 보관 |
| **품질 게이트** | `readiness.py` — 10개 카테고리 사전 점검 | 실거래 전환 전 필수 통과 |
| **DB 최적화** | `upsert_market_data()` — 배치 upsert | 2,400 RTT → 1 RTT (95%+ 감소) |

### 장 전/중/후 운영 흐름

```
08:00  rl_bootstrap      활성 정책 없으면 학습, 있으면 워밍업
08:05  predictor_warmup   LLM provider 가용성 확인 + 모듈 캐시
08:10  stock_master       종목 마스터 수집
08:20  macro_daily        거시경제 지표 수집
08:30  collector_daily    전종목 일봉 수집
08:55  index_warmup       지수 데이터 워밍업
09:00  ────────────────── 장 시작 ──────────────────
09:00~ index_collection   30초 인터벌 실시간 수집
15:30  ────────────────── 장 마감 ──────────────────
16:00  rl_retrain         RL 전략 재학습
16:30  blend_weight_adj   성과 기반 블렌딩 가중치 동적 조정
```

### Daily Learning Cycle

매일 장 마감 후 최신 일봉 데이터를 기준으로 RL 모델을 재학습합니다. 고정된 과거 데이터가 아니라, **매일 누적되는 실제 시장 데이터**로 모델이 업데이트됩니다.

```
Day 1: 720일 일봉으로 학습 → Q-table v1 생성
Day 2: 721일 일봉으로 재학습 → Q-table v2 생성 (어제 종가 반영)
Day 3: 722일 일봉으로 재학습 → Q-table v3 생성 (그제+어제 반영)
...
```

| 단계 | 시점 | 동작 |
|---|---|---|
| **수집** | 08:30 KST | FDR API로 전 종목 최신 일봉 수집 → `ohlcv_daily` 테이블에 upsert |
| **추론** | 09:00~15:30 | 기존 Q-table로 BUY/SELL/HOLD 시그널 생성 (학습 없이 추론만) |
| **재학습** | 16:00 | 오늘까지의 최신 720일 일봉으로 Q-table 재학습 + walk-forward 검증 |
| **가중치 조정** | 16:30 | A/B/RL 3전략의 블렌딩 가중치를 최근 성과 기반으로 재계산 |

walk-forward 검증을 통과한 정책만 활성화되므로, 성능이 나빠진 모델은 자동으로 교체됩니다.

---

## Workflow Orchestration

Airflow를 사용하지 않고, 동일한 문제를 직접 설계했습니다.

| Airflow 개념 | Alpha 구현 | 파일 |
|---|---|---|
| Scheduler | `unified_scheduler.py` (APScheduler) | 9개 CronTrigger 잡 |
| Task retry | `job_wrapper.py` (exponential backoff) | 3회 재시도 + 이력 기록 |
| Backfill / Catchup | `rl_bootstrap.py` (720일 시딩) | DB 갭 감지 → FDR 자동 채움 |
| Distributed Lock | `distributed_lock.py` (Redis SET NX) | 멀티 Pod 중복 실행 방지 |
| SLA / Quality Gate | `readiness.py` (10개 체크) | 실거래 전환 전 필수 통과 |
| XCom (태스크 간 데이터) | Redis pub/sub + ConfigMap | 실시간 틱 → 오케스트레이터 |
| DAG 시각화 | React Dashboard | 에이전트 상태 + 실행 이력 |

> 상세 비교: [docs/airflow-comparison.md](docs/airflow-comparison.md)

---

## Infrastructure

### Production: Helm(인프라) + Kustomize(앱)

```bash
# 인프라 (Stateful) — Bitnami Helm chart
helm install alpha-pg bitnami/postgresql -n alpha-trading -f k8s/helm/bitnami-values/postgres-values.yaml
helm install alpha-redis bitnami/redis -n alpha-trading -f k8s/helm/bitnami-values/redis-values.yaml
helm install alpha-minio minio/minio -n alpha-trading -f k8s/helm/bitnami-values/minio-values.yaml

# 앱 (Stateless) — Kustomize overlay
kubectl apply -k k8s/overlays/dev    # 또는 k8s/overlays/prod

# 또는 한 줄로
./k8s/scripts/deploy.sh dev
```

### Local Development: Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose run --rm api python scripts/db/init_db.py
curl http://localhost:8000/health
```

접속:
- Dashboard: `http://localhost:5173`
- API Docs: `http://localhost:8000/docs`
- MinIO Console: `http://localhost:9001`

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, LangGraph, APScheduler |
| **LLM** | Claude (CLI/SDK), GPT-4o, Gemini (OAuth/ADC) |
| **Data** | FinanceDataReader, KIS Developers API, PyArrow Parquet |
| **Storage** | PostgreSQL 15, Redis 7, MinIO (S3-compatible) |
| **Infra** | K3s (Colima), Helm, Kustomize, Docker, GitHub Actions CI |
| **Frontend** | TypeScript, React 18, Vite, Tailwind CSS |
| **Monitoring** | Prometheus, Grafana, Telegram Bot |

---

## Testing

```bash
# 전체 테스트 (557 passed, 0 failed)
pytest test/ -m "not integration"

# Ruff lint (All checks passed)
ruff check src/ scripts/

# Smoke test (Docker 환경)
docker compose exec api python scripts/smoke_test.py --skip-telegram

# 실거래 전환 사전 점검
docker compose run --rm api python scripts/preflight_real_trading.py
```

---

## Project Structure

```
src/
├── agents/           # 7 에이전트 (collector, predictor, orchestrator, ...)
├── api/              # FastAPI REST API + routers
├── brokers/          # KIS 브로커 (paper/real/virtual)
├── db/               # PostgreSQL 쿼리 + 모델
├── llm/              # LLM 클라이언트 (Claude/GPT/Gemini)
├── schedulers/       # 통합 스케줄러 + 분산 락
├── services/         # 데이터레이크, KIS 세션, LLM 리미터
└── utils/            # 설정, 로깅, 리스크 검증, 레디니스

k8s/
├── base/             # Kustomize 공통 (api, worker, ui)
├── overlays/         # dev / prod 환경 분리
├── helm/             # Bitnami values (PostgreSQL, Redis, MinIO)
└── scripts/          # deploy.sh, teardown.sh

scripts/              # CLI 도구 (rl_bootstrap, smoke_test, preflight, ...)
test/                 # 557 tests
ui/web/               # React + TypeScript dashboard
```

---

## Disclaimer

이 시스템은 교육 및 연구 목적으로 개발되었습니다.
실제 투자에서 발생하는 손익에 대해 개발자는 책임을 지지 않습니다.
실거래 모드 활성화 전 충분한 페이퍼 트레이딩 검증을 권장합니다.
