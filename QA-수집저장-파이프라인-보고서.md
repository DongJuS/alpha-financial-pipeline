# QA 심층 보고서: 수집-저장 파이프라인

> **작성일**: 2026-03-16 | **기반 문서**: qa-report-v2.pdf (2nd Round QA)
> **QA 수행자**: Claude Agent | **대상**: agents-investing 백엔드 데이터 파이프라인
> **목적**: 백엔드 개발자에게 수집-저장 관련 결함을 정확히 전달하여 즉각 수정 가능하도록 함

---

## 1. 요약 (Executive Summary)

QA v2 리포트와 실제 소스코드를 대조 검증한 결과, **UI 레벨의 Pass Rate는 93.1%로 양호**하나, 수집-저장 파이프라인에는 **데이터가 실제로 흐르지 않는 치명적 문제**가 다수 존재합니다.

| 구분 | QA 리포트 판정 | 코드 검증 결과 | 실제 심각도 |
|------|---------------|---------------|-----------|
| Collector Agent | PASS (healthy) | 정상 작동 확인, 1560 daily bars 수집 | **OK** |
| Predictor 1~5 | WARN (all error) | **Silent Failure** - 예외 삼킴, 0건 저장 | **CRITICAL** |
| S3/MinIO DataLake | WARN (0 objects) | 컨테이너 미실행 + 재시도 로직 없음 | **HIGH** |
| OpenAI/GPT Provider | FAIL (missing) | OPENAI_API_KEY 미설정 → 프로바이더 등록 안됨 | **HIGH** |
| DB 테이블 수 | 27개 (리포트) | **29개** (코드 확인) — 리포트 오차 존재 | **LOW** |
| Redis Heartbeat | PASS (1,161건) | 정상 작동 | **OK** |

**핵심 문제**: Predictor가 100% 실패하고 있으므로, 현재 시스템은 **시세 데이터만 수집하고 예측 신호는 전혀 생성하지 못하는 상태**입니다. 투자 판단의 핵심인 Signal Generation이 완전히 중단된 것입니다.

---

## 2. 아키텍처 흐름도 (데이터 파이프라인)

```
[KIS API / FDR / Yahoo]
        │
        ▼
┌─────────────────┐     ┌──────────┐
│ Collector Agent  │────▶│ PostgreSQL│ (market_data 테이블)
│ (collector.py)   │     │ 27+2 tables│
│  822 lines       │     └──────────┘
└────────┬────────┘           │
         │                    │
         ▼                    ▼
┌─────────────────┐     ┌──────────┐
│ Redis Pub/Sub   │     │ S3/MinIO │ ← ❌ 컨테이너 미실행
│ (heartbeat+data)│     │ alpha-lake│
└────────┬────────┘     └──────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│           Orchestrator (orchestrator.py) │
│  ┌────────┐ ┌────────┐ ┌──────┐ ┌────┐ │
│  │Strat A │ │Strat B │ │Search│ │ RL │ │
│  │(30%)   │ │(30%)   │ │(20%) │ │(20%)│ │
│  └───┬────┘ └───┬────┘ └──┬───┘ └──┬─┘ │
│      └──────┬───┘         │        │    │
│             ▼             ▼        ▼    │
│     ┌──────────────┐                    │
│     │  Predictor   │ ← ❌ 5개 전부 FAIL │
│     │  1~5 (LLM)   │                    │
│     └──────────────┘                    │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ Portfolio Manager│ → (waiting: 신호 없음)
│ → Broker Orders  │
└─────────────────┘
```

---

## 3. CRITICAL 이슈 상세

### 3.1 [CRITICAL] Predictor Agent Silent Failure — 전체 예측 생성 중단

**현상**: 5개 Predictor Agent 모두 success=0, fail=20 (총 100건 실패)

**파일**: `src/agents/predictor.py`

**근본 원인 분석**:

Predictor의 개별 ticker 처리 시 예외가 발생하면, `logger.warning()`으로 로그만 남기고 `None`을 반환합니다. `None`이 반환되면 DB 저장을 **완전히 건너뜁니다**.

```python
# predictor.py Line 181-186 (문제 코드)
except Exception as e:
    logger.warning("%s 예측 생략 [%s]: %s", self.agent_id, ticker, e)
    return None  # ← DB 저장 없이 조용히 넘어감

# predictor.py Line 193-198
if pred is None:
    failed_tickers.append(tickers[idx])
    continue  # ← insert_prediction() 호출 안됨
```

**왜 100% 실패하는가 — 3가지 가능 시나리오**:

| 시나리오 | 가능성 | 검증 방법 |
|---------|--------|---------|
| **A. LLM 프로바이더 전부 미설정** | **높음** | `.env`에서 OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY 확인 |
| **B. Fallback Chain 전체 실패** | 중간 | 각 프로바이더의 API key 유효성 + quota 확인 |
| **C. market_data 조회 결과가 빈 배열** | 낮음 | Collector는 정상(1560 bars)이므로 가능성 낮음 |

**Provider Fallback Chain 구조**:
```
Primary (예: Claude) → Secondary (예: GPT) → Tertiary (예: Gemini)
                                                        │
                                                        ▼
                                              RuntimeError 발생
                                              → warning 로그만 남김
                                              → pred = None
```

**수정 요청 (개발자용)**:

1. **즉시**: `predictor.py` Line 185의 `logger.warning` → `logger.error`로 변경하고, 예외 traceback 전체를 출력하도록 수정
2. **즉시**: 시스템 시작 시 LLM 프로바이더 최소 1개 설정 여부를 검증하는 startup validation 추가 (`src/api/main.py` 또는 `src/agents/predictor.py`의 `__init__`)
3. **단기**: 실패한 prediction도 `predictions` 테이블에 `status='error'` 레코드로 기록하여 추적 가능하게 변경
4. **단기**: Predictor별 실패 카운터를 별도 메트릭으로 수집 (현재는 heartbeat의 metrics 딕셔너리에만 존재)

```python
# 수정 예시: predictor.py
except Exception as e:
    logger.error(
        "%s 예측 실패 [%s]: %s",
        self.agent_id, ticker, e,
        exc_info=True  # ← traceback 포함
    )
    # 실패 레코드도 DB에 기록
    await insert_prediction(PredictionSignal(
        agent_id=self.agent_id,
        ticker=ticker,
        signal="ERROR",
        confidence=0.0,
        reasoning_summary=str(e),
    ))
    return None
```

---

### 3.2 [HIGH] S3/MinIO DataLake 완전 미작동 — 0 Objects, 0 Bytes

**현상**: alpha-lake 버킷은 존재하나 오브젝트 0개

**파일**: `src/services/datalake.py` (196 lines), `docker-compose.yml`

**근본 원인**:

1. **MinIO 컨테이너가 실행되지 않음** (docker-compose에서 minio 서비스 stopped 상태)
2. datalake.py에 **S3 업로드 실패 시 재시도 로직이 없음**

```python
# datalake.py — S3 업로드 부분 (재시도 없음)
async def _upload_parquet(self, key: str, buffer: bytes):
    await self.s3_client.put_object(
        Bucket=self.bucket_name,
        Key=key,
        Body=buffer,
    )
    # ← 실패 시 예외가 그대로 전파됨. 재시도 없음.
```

**영향 범위**:

| 저장 대상 | Parquet Schema | 현재 상태 |
|-----------|---------------|----------|
| market_data (DAILY_BARS) | ticker, timestamp_kst, OHLCV, volume, change_pct | ❌ 미저장 |
| predictions | agent_id, llm_model, strategy, ticker, signal, confidence | ❌ 미저장 |
| orders | ticker, order_type, quantity, price, status | ❌ 미저장 |
| blend_results | ticker, blended_signal, component_signals, weights_used | ❌ 미저장 |

**Hive Partitioning 구조** (정상 시):
```
alpha-lake/
├── market_data/
│   └── date=2026-03-16/
│       └── 1710567600.parquet  (Snappy 압축)
├── predictions/
│   └── date=2026-03-16/
│       └── 1710567601.parquet
└── orders/
    └── date=2026-03-16/
        └── 1710567602.parquet
```

**수정 요청 (개발자용)**:

1. **즉시**: MinIO 컨테이너 실행 확인 및 재시작
   ```bash
   docker-compose up -d minio minio-init
   # minio-init 서비스가 alpha-lake 버킷을 자동 생성함
   ```

2. **단기**: S3 업로드에 exponential backoff 재시도 추가
   ```python
   # 수정 예시
   from tenacity import retry, stop_after_attempt, wait_exponential

   @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
   async def _upload_parquet(self, key: str, buffer: bytes):
       await self.s3_client.put_object(...)
   ```

3. **단기**: S3 실패 시에도 PostgreSQL 저장은 독립적으로 성공하도록 보장 (현재 Collector는 DB 저장 → S3 저장 순서이므로, S3 실패가 전체 플로우를 중단시킬 수 있음)

---

### 3.3 [HIGH] OpenAI/GPT Provider 미등록

**현상**: /models 페이지에서 Claude, Gemini만 표시. GPT 카드 없음.

**파일**: `src/utils/config.py`, `.env.example`

**원인**: `OPENAI_API_KEY` 환경변수가 미설정 → 프로바이더 등록 로직에서 GPT를 스킵

**영향**:
- Predictor의 3-provider fallback chain 중 1개가 비활성 → 내결함성 저하
- GPT-4o를 primary로 사용하는 predictor가 있을 경우, 해당 predictor는 항상 secondary로 fallback

**수정 요청**:

1. `.env` 파일에 `OPENAI_API_KEY` 설정
2. `/models` API 엔드포인트에서 미설정 provider도 `DISABLED` 상태로 표시하도록 수정 (현재는 아예 숨김)

---

## 4. MEDIUM 이슈 상세

### 4.1 [MEDIUM] DB 테이블 수 불일치

**QA 리포트**: 27개 | **실제 코드 (`scripts/db/init_db.py`)**: 29개

누락된 2개 테이블:
- `strategy_promotions` — RL/Search 전략 승격 이력
- `aggregate_risk_snapshots` — 포트폴리오 레벨 리스크 모니터링

**영향**: System Health 페이지의 "27 DB tables" 표시가 부정확. 실제로는 29개가 존재해야 정상.

**수정 요청**: `system-health` API에서 DB 테이블 카운트 로직 확인. `init_db.py`의 최신 스키마가 실제 DB에 반영되었는지 마이그레이션 확인 필요.

---

### 4.2 [MEDIUM] Concurrent Semaphore 제한 (3)

**파일**: `src/agents/predictor.py`

Predictor가 LLM API를 호출할 때 `asyncio.Semaphore(3)`으로 동시 호출 수를 제한합니다. 5개 Predictor가 각각 20개 ticker를 처리하면 총 100건의 LLM 호출이 필요하나, 동시에 3건만 처리 가능합니다.

**영향**: 처리 지연 + timeout 발생 가능성. 특히 Claude API의 rate limit과 결합 시 cascade failure 위험.

**수정 요청**: Semaphore 값을 설정 파일(`config.py`)에서 조정 가능하도록 외부화. 프로바이더별 rate limit에 맞춘 적응형 제한 고려.

---

### 4.3 [MEDIUM] DB Connection Pool 고갈 가능성

**파일**: `src/utils/config.py`

```python
# 현재 설정
DB_POOL_MIN = 2
DB_POOL_MAX = 20
DB_COMMAND_TIMEOUT = 30  # seconds
```

5개 Predictor + Collector + Orchestrator + Portfolio Manager + API 서버가 동시에 DB를 사용하면 20개 연결이 부족할 수 있습니다. 특히 `insert_prediction()`이 ticker 20개를 순차적으로 처리할 때 connection hold 시간이 길어집니다.

**수정 요청**:
- Pool max를 30~40으로 증가 고려
- Prediction insert를 batch upsert로 변경 (20건 개별 INSERT → 1건 bulk INSERT)

---

### 4.4 [MEDIUM] Circuit Breaker 패턴 부재

현재 S3, LLM API, DB 중 하나가 장애 나면 cascade failure가 발생합니다. 예를 들어:

```
MinIO 다운 → datalake.store_daily_bars() 예외
            → Collector 전체 사이클 실패
            → market_data 수집 중단
            → Predictor 입력 데이터 없음
            → 전체 파이프라인 중단
```

**수정 요청**: `pybreaker` 등을 사용한 Circuit Breaker 패턴 도입. S3 실패가 DB 저장까지 영향주지 않도록 격리.

---

## 5. 데이터 정합성 검증 결과

QA 리포트의 cross-page 데이터 일관성을 코드 레벨에서 검증했습니다.

| 검증 항목 | 리포트 판정 | 코드 검증 | 비고 |
|-----------|-----------|----------|------|
| Dashboard 총자산 == Portfolio 총자산 (10,014,670) | PASS | **PASS** | 동일 API 엔드포인트 사용 확인 |
| Dashboard 보유종목 == Portfolio positions (4) | PASS | **PASS** | `portfolio_positions` 테이블 단일 소스 |
| Agent Control 에이전트 수 == System Health (9) | PASS | **PASS** | `agent_heartbeats` 테이블 기반 |
| Audit 알림 수 (1,759) 일관성 | PASS | **PASS** | `notification_history` COUNT 쿼리 |
| Collector 1,560 bars == market_data rows | PASS | **PASS** | 동일 테이블 `market_data` 기준 |
| Predictor 성공률 35.6% (Tournament) | — | **의문** | 전체 FAIL인데 35.6%가 표시되는 것은 이전 데이터 잔존 가능 |

**주의**: Tournament 테이블의 accuracy 35.6%는 **과거 정상 작동 시기의 데이터**일 가능성이 높습니다. 현재 Predictor가 전부 실패 중이므로 이 수치는 stale data입니다. 개발자는 `predictor_tournament_scores` 테이블의 `updated_at` 컬럼을 확인하여 최신 여부를 검증해야 합니다.

---

## 6. 수정 우선순위 매트릭스

| 순위 | 이슈 | 심각도 | 예상 소요 | 담당 |
|------|------|--------|----------|------|
| **P0** | Predictor Silent Failure — 예외 로깅 강화 + 실패 레코드 기록 | CRITICAL | 2h | 백엔드 |
| **P0** | LLM 프로바이더 Startup Validation 추가 | CRITICAL | 1h | 백엔드 |
| **P1** | MinIO 컨테이너 재시작 + 정상 동작 확인 | HIGH | 30min | 인프라/백엔드 |
| **P1** | OPENAI_API_KEY 환경변수 설정 | HIGH | 10min | 인프라 |
| **P1** | S3 업로드 재시도 로직 추가 (tenacity) | HIGH | 2h | 백엔드 |
| **P2** | DB 테이블 수 불일치 확인 (27 vs 29) | MEDIUM | 1h | 백엔드 |
| **P2** | Prediction batch upsert 전환 | MEDIUM | 3h | 백엔드 |
| **P2** | Circuit Breaker 패턴 도입 | MEDIUM | 4h | 백엔드 |
| **P3** | Semaphore 외부 설정화 | LOW | 30min | 백엔드 |
| **P3** | DB Pool Max 증가 (20→40) | LOW | 10min | 인프라 |

---

## 7. 검증에 사용한 소스 파일 목록

| 파일 경로 | 라인 수 | 역할 |
|-----------|--------|------|
| `src/agents/collector.py` | 822 | 데이터 수집 에이전트 |
| `src/agents/predictor.py` | 265 | LLM 예측 에이전트 |
| `src/agents/orchestrator.py` | 435 | 전략 오케스트레이터 |
| `src/agents/strategy_a_runner.py` | 124 | Strategy A (Tournament) |
| `src/agents/strategy_b_runner.py` | 56 | Strategy B (Debate) |
| `src/agents/search_runner.py` | 74 | Search Pipeline |
| `src/agents/rl_runner.py` | 136 | RL Trading |
| `src/services/datalake.py` | 196 | S3/Parquet 서비스 |
| `src/utils/redis_client.py` | — | Redis + Heartbeat |
| `src/utils/config.py` | — | 환경 설정 |
| `src/db/queries.py` | — | DB 쿼리 40+ 함수 |
| `scripts/db/init_db.py` | — | 29개 테이블 DDL |
| `docker-compose.yml` | — | 서비스 구성 |

---

## 8. 결론

**현재 시스템 상태**: 시세 데이터 수집(Collector)만 정상 작동 중. 핵심 가치인 **예측 신호 생성(Predictor)과 데이터 레이크 적재(S3)가 완전히 중단**된 상태.

**즉시 조치 필요 사항**:
1. Predictor의 silent failure 원인 파악 (LLM API key 확인이 최우선)
2. MinIO 컨테이너 복구
3. 에러 가시성 확보 (warning → error 레벨 변경, 실패 레코드 DB 기록)

이 3가지가 해결되지 않으면 투자 시스템은 **"시세만 보는 관전 모드"**로 운영되는 것과 같습니다.

---

*QA 보고서 생성: 2026-03-16 | 검증 방법: 소스코드 정적 분석 + QA v2 리포트 대조 + 아키텍처 흐름 추적*
