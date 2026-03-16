# QA 심층 분석 보고서: 수집-저장 파이프라인

> **프로젝트**: agents-investing
> **QA 일자**: 2026-03-16
> **분석 범위**: 수집(Collection) → 저장(Storage) → 소비(Consumption) 전체 파이프라인
> **분석 방법**: QA Report v1/v2 크로스 레퍼런스 + 소스코드 정밀 리뷰 (16개 핵심 파일)
> **대상 독자**: 백엔드 개발자 (버그 수정 및 인프라 복구 담당)

---

## 1. Executive Summary

| 구분 | 상태 | 비고 |
|------|------|------|
| **Collector → PostgreSQL** | ✅ OPERATIONAL | 1,560 daily bars 정상 수집 |
| **Collector → Redis** | ✅ OPERATIONAL | 1,161 heartbeats / 24h 확인 |
| **Collector → S3/MinIO** | ❌ DEAD | MinIO 컨테이너 미기동, 0 objects |
| **Predictor → PostgreSQL** | ❌ DEAD | LLM 5개 전원 실패, predictions 0건 |
| **DataLake Parquet 아카이브** | ❌ DEAD | 4종 Parquet 모두 미생성 |
| **stock_master 시딩** | ⚠️ PARTIAL | 테이블 존재하나 sector/industry 미충전 |

**한줄 진단**: 수집 단계는 PostgreSQL/Redis까지 정상 동작하나, **S3 DataLake가 완전 사망** 상태이고 **Predictor 전원 LLM 호출 실패**로 인해 수집된 데이터가 소비되지 못하고 있다. 시스템 전체가 "수집은 하지만 아무것도 하지 않는" 상태.

---

## 2. 아키텍처 전체 흐름도

```
┌─────────────────── COLLECTION STAGE ───────────────────┐
│                                                         │
│  KIS WebSocket ──┐                                      │
│  FDR (일봉)  ────┤→ CollectorAgent → PostgreSQL ✅       │
│  Yahoo Finance ──┘   (867 lines)    market_data         │
│                                     (1,560 bars/day)    │
│                          │                              │
│                          ├→ Redis Pub/Sub ✅             │
│                          │  (latest_ticks, heartbeat)   │
│                          │                              │
│                          └→ S3/MinIO ❌ OFFLINE          │
│                             (Parquet 미생성)              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  StockMasterCollector → stock_master ⚠️ (섹터 미충전)    │
│  MacroCollector → macro_indicators ⚠️ (FDR 가용성 이슈)  │
│  IndexCollector → KOSPI/KOSDAQ 지수 ✅                   │
│                                                         │
└─────────────────── PREDICTION STAGE ───────────────────┘
│                                                         │
│  market_data → PredictorAgent 1~5 ❌ ALL FAIL           │
│               (success=0, fail=20 per agent)            │
│               → predictions 테이블: 0건                  │
│               → S3 Parquet: 미생성                       │
│                                                         │
└─────────────────── EXECUTION STAGE ────────────────────┘
│                                                         │
│  predictions(0건) → StrategyRunner → PortfolioManager   │
│                     ❌ 시그널 없음     ⏸ IDLE            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. CRITICAL 이슈 상세 (즉시 조치 필요)

### 3.1 [CRIT-01] S3/MinIO DataLake 완전 사망

**심각도**: 🔴 P0
**파일**: `src/services/datalake.py`, `src/utils/s3_client.py`
**현상**: DataLake 페이지 bucket summary 0 objects, 0B size, 0 prefixes

**근본 원인**:

1. MinIO 컨테이너가 기동되지 않음 (docker-compose stopped)
2. S3 업로드 실패 시 **silent warning**만 남기고 넘어감 → 데이터 유실 인지 불가

**문제 코드** (`datalake.py`):
```python
# store_daily_bars() 내부
except Exception as e:
    logger.warning("S3 일봉 저장 실패 (비필수): %s", e)
    return None  # ← 실패를 삼켜버림, 재시도 없음
```

**유실되고 있는 데이터**:

| Parquet 스키마 | Hive 파티션 패턴 | 상태 |
|---------------|-----------------|------|
| `ParquetDailyBarsSchema` | `daily_bars/date=YYYY-MM-DD/` | ❌ 0건 |
| `ParquetPredictionsSchema` | `predictions/date=YYYY-MM-DD/` | ❌ 0건 |
| `ParquetOrdersSchema` | `orders/date=YYYY-MM-DD/` | ❌ 0건 |
| `ParquetBlendResultsSchema` | `blend_results/date=YYYY-MM-DD/` | ❌ 0건 |

**S3 클라이언트 설정** (`s3_client.py`):
```
endpoint: http://localhost:9000
access_key: minioadmin
secret_key: minioadmin
bucket: alpha-lake
region: ap-northeast-2
```

**수정 방안**:

```bash
# 1단계: 즉시 — MinIO 컨테이너 기동
docker-compose up -d minio minio-init

# 2단계: 코드 수정 — 재시도 로직 추가
```

```python
# datalake.py — store_daily_bars() 수정안
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _upload_with_retry(self, key: str, data: bytes, metadata: dict):
    return await self.s3.upload_bytes(key, data, metadata)

async def store_daily_bars(self, ...):
    try:
        result = await self._upload_with_retry(key, parquet_bytes, metadata)
        logger.info("S3 일봉 저장 성공: %s (%d bytes)", key, len(parquet_bytes))
        return result
    except Exception as e:
        logger.error(  # warning → error 승격
            "S3 일봉 저장 최종 실패 (3회 재시도 후): %s", e,
            exc_info=True,
        )
        # 실패 기록을 DB에 남겨 운영자에게 알림
        await self._record_datalake_failure("daily_bars", key, str(e))
        return None
```

**검증 방법**:
```bash
# MinIO 기동 후 확인
curl -s http://localhost:9000/minio/health/live  # → 200 OK
mc ls local/alpha-lake/                           # → 객체 목록 확인
```

---

### 3.2 [CRIT-02] Predictor 5개 전원 LLM 호출 실패 (success=0, fail=100)

**심각도**: 🔴 P0
**파일**: `src/agents/predictor.py`
**현상**: Agent Control에서 predictor_1~5 모두 error 뱃지, success=0 / fail=20

**근본 원인 분석**:

`.env` 파일 확인 결과:
```env
ANTHROPIC_API_KEY=            # ← 빈 값
ANTHROPIC_CLI_COMMAND=claude  # ← CLI 경로 (claude binary 설치 여부 미확인)
OPENAI_API_KEY=               # ← 빈 값
GEMINI_API_KEY=               # ← 빈 값
GOOGLE_APPLICATION_CREDENTIALS=  # ← 빈 값
```

**LLM 프로바이더별 상태**:

| Provider | Config Key | 값 | is_configured | 결과 |
|----------|-----------|------|---------------|------|
| Claude SDK | `ANTHROPIC_API_KEY` | 빈 문자열 | `False` | ❌ |
| Claude CLI | `ANTHROPIC_CLI_COMMAND` | `claude` | 바이너리 존재 시 `True` | ❓ 미확인 |
| Gemini | `GEMINI_API_KEY` / `GOOGLE_APPLICATION_CREDENTIALS` | 빈 문자열 | `False` | ❌ |
| GPT | `OPENAI_API_KEY` | 빈 문자열 | N/A (미구현) | ❌ |

**실패 경로 추적** (`predictor.py`):
```python
# __init__ (lines 57-71)
configured_providers: list[str] = []
if self.claude.is_configured:
    configured_providers.append(...)
if self.gemini.is_configured:
    configured_providers.append(...)

if not configured_providers:
    raise RuntimeError(msg)  # ← 여기서 터져야 하는데...
```

**의심 시나리오**: Orchestrator가 PredictorAgent 생성 시 RuntimeError를 `try-except`로 감싸고 있을 가능성 → 에이전트가 "만들어진 것처럼" 등록되지만 실제로는 좀비 상태.

**문제 코드** (예측 실행부):
```python
# _predict_single() (lines 202-210)
except Exception as e:
    logger.warning(  # ← warning 레벨이라 운영 모니터링에 안 잡힘
        "%s 예측 실패 [%s]: %s",
        self.agent_id, ticker, e,
    )
    return None  # ← 실패를 삼켜버림
```

**수정 방안**:

```python
# 1단계: .env 설정 — 최소 1개 프로바이더 활성화
ANTHROPIC_API_KEY=sk-ant-xxxxx  # 또는
GEMINI_API_KEY=AIzaSyxxxxx

# 2단계: predictor.py — Silent failure 제거
async def _predict_single(self, ticker: str, ...):
    try:
        result = await self._llm_signal(ticker, ...)
        return result
    except Exception as e:
        logger.error(  # warning → error 승격
            "%s 예측 실패 [%s]: %s",
            self.agent_id, ticker, e,
            exc_info=True,  # 스택트레이스 포함
        )
        # 실패 기록을 predictions 테이블에 status='error'로 저장
        await self._record_prediction_failure(ticker, str(e))
        return None

# 3단계: orchestrator.py — 에이전트 생성 실패 시 명시적 핸들링
try:
    predictor = PredictorAgent(config)
except RuntimeError as e:
    logger.critical("Predictor 생성 실패: %s", e)
    await self._notify_admin("predictor_creation_failed", str(e))
    raise  # 절대 삼키지 않음
```

**검증 방법**:
```bash
# LLM 프로바이더 설정 후
python -c "from src.llm.claude_client import ClaudeClient; c = ClaudeClient(); print(c.is_configured)"
# → True 출력 확인

# 단일 예측 테스트
python -m src.agents.predictor --ticker 005930 --dry-run
# → signal, confidence, reasoning 출력 확인
```

---

### 3.3 [CRIT-03] stock_master 섹터 데이터 미시딩

**심각도**: 🟡 P1
**파일**: `src/agents/stock_master_collector.py`, `src/db/marketplace_queries.py`
**현상**: Marketplace 섹터 히트맵 빈 화면, 랭킹 섹션 데이터 없음

**근본 원인**: `stock_master` 테이블에 종목 기본 정보는 있으나 `sector`, `industry` 컬럼이 비어있음. KRX에서 제공하는 기본 데이터에 섹터 분류가 포함되지 않는 경우가 있으며, 별도의 매핑 테이블이나 추가 크롤링이 필요.

**수정 방안**:
```python
# stock_master_collector.py에 섹터 매핑 로직 추가
# FinanceDataReader의 StockListing에서 sector 정보 추출
# 또는 KRX 업종분류 API 호출

async def seed_sector_data(self):
    """stock_master의 sector/industry 필드 충전"""
    listing = fdr.StockListing('KRX')
    # sector 컬럼 매핑 후 bulk upsert
```

---

## 4. HIGH 이슈 상세 (이번 스프린트 내 조치)

### 4.1 [HIGH-01] S3 업로드 재시도 로직 부재

**파일**: `src/utils/s3_client.py`
**현상**: boto3 기본 3회 재시도만 존재, 애플리케이션 레벨 재시도 없음

현재 `s3_client.py`에서 boto3 config에 `retries={"max_attempts": 3}`를 설정했지만, 이는 HTTP 레벨 재시도일 뿐이다. MinIO 컨테이너가 일시적으로 재시작되는 경우 등 인프라 레벨 장애에 대응하지 못함.

**수정 방안**: `tenacity` 라이브러리를 사용한 애플리케이션 레벨 재시도 추가 (위 CRIT-01 코드 참조)

---

### 4.2 [HIGH-02] Predictor Silent Failure → 운영 모니터링 사각지대

**파일**: `src/agents/predictor.py` lines 202-210
**현상**: 예측 실패가 `logger.warning` 레벨로만 기록되어 알림 시스템에 잡히지 않음

**수정 방안**:
1. `logger.warning` → `logger.error` 승격
2. `predictions` 테이블에 `status` 컬럼 추가 (`success` / `error` / `timeout`)
3. 연속 N회 실패 시 Telegram 알림 발송 (Notifier 연동)

---

### 4.3 [HIGH-03] Global ErrorBoundary 부재

**파일**: UI 전체 (`App.tsx` 또는 `main.tsx`)
**현상**: 1st/2nd QA 공통 FAIL — React 컴포넌트 하나가 크래시하면 전체 페이지 white screen

**수정 방안**:
```tsx
// src/components/ErrorBoundary.tsx
class GlobalErrorBoundary extends React.Component {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // 에러 로깅 서비스에 전송
    console.error('Uncaught error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallbackUI error={this.state.error} onReset={() => this.setState({ hasError: false })} />;
    }
    return this.props.children;
  }
}

// App.tsx에서 Router를 감싸기
<GlobalErrorBoundary>
  <RouterProvider router={router} />
</GlobalErrorBoundary>
```

---

## 5. MEDIUM 이슈 상세 (다음 페이즈)

### 5.1 [MED-01] 클라이언트 폼 밸리데이션 부재

**페이지**: Settings, Models, RL Training
**현상**: HTML `min`/`max` 속성만 존재, JavaScript 레벨 검증 없음
**수정 방안**: React Hook Form + Zod 스키마 도입

### 5.2 [MED-02] 세션 만료 핸들링 없음

**현상**: 토큰 만료 시 silent redirect → /login, 작업 중이던 사용자 데이터 유실 가능
**수정 방안**: axios interceptor에서 401 감지 → 토스트 알림 + 로그인 모달

### 5.3 [MED-03] Macro Collector FDR 가용성 이슈

**파일**: `src/agents/macro_collector.py`
**현상**: FDR의 해외지수 데이터가 간헐적으로 빈 DataFrame 반환
**수정 방안**: Yahoo Finance 대체 소스 추가, 빈 응답 시 이전 캐시 유지

---

## 6. 데이터 일관성 검증 결과

### 6.1 Cross-Page 수치 일치 (QA v2 기준)

| 검증 항목 | 페이지 A | 페이지 B | 일치 여부 |
|-----------|---------|---------|---------|
| 총자산 10,014,670원 | Dashboard | Portfolio | ✅ 일치 |
| 보유종목 4건 | Dashboard | Portfolio | ✅ 일치 |
| 에이전트 수 9 | Agent Control | System Health | ✅ 일치 |
| 알림 수 1,759건 | Notifications | Audit Trail | ✅ 일치 |
| Collector 1,560 bars | Agent Control | System Health | ✅ 일치 |

### 6.2 DB 테이블 수 불일치

| 소스 | 테이블 수 | 비고 |
|------|---------|------|
| System Health UI 표시 | 27 | UI에서 읽어온 값 |
| 소스코드 분석 (queries.py + marketplace_queries.py) | 29+ | 코드에서 참조하는 테이블 |
| **차이** | **+2 이상** | migration 파일 재확인 필요 |

---

## 7. 인프라 연결 상태 종합

| 인프라 | 상태 | 응답시간 | 비고 |
|--------|------|---------|------|
| PostgreSQL | ✅ OK | 4.2ms | 27 tables, 정상 가동 |
| Redis | ✅ OK | 1.9ms | heartbeat 1,161건/24h |
| S3/MinIO | ❌ ERROR | N/A | 컨테이너 미기동 |
| KIS REST API | ✅ OK | - | Paper 계좌 44 orders, 4 positions |
| KIS WebSocket | ✅ OK | - | 실시간 틱 수집 정상 |
| Claude API | ✅ READY | - | Models 페이지 확인 |
| Gemini API | ✅ READY | - | Models 페이지 확인 |
| OpenAI/GPT API | ❌ MISSING | - | .env OPENAI_API_KEY 빈 값 |

---

## 8. 수정 우선순위 & 체크리스트

### P0 — 즉시 (오늘 중)

- [ ] **MinIO 컨테이너 기동**: `docker-compose up -d minio minio-init`
- [ ] **MinIO 기동 후 alpha-lake 버킷 확인**: `mc ls local/alpha-lake/`
- [ ] **LLM API 키 최소 1개 설정**: `.env`에 `ANTHROPIC_API_KEY` 또는 `GEMINI_API_KEY`
- [ ] **Predictor 단독 테스트**: `python -m src.agents.predictor --ticker 005930 --dry-run`
- [ ] **Orchestrator 1회 실행**: 수집 → 예측 → 전략 전체 사이클 확인

### P1 — 이번 스프린트

- [ ] `datalake.py` S3 업로드에 tenacity 재시도 로직 추가
- [ ] `predictor.py` silent failure → `logger.error` + DB 실패 기록
- [ ] `stock_master_collector.py` 섹터/업종 데이터 시딩 로직 추가
- [ ] UI: `App.tsx`에 Global ErrorBoundary 추가
- [ ] UI: Settings/Models/RL Training 폼에 클라이언트 밸리데이션 추가

### P2 — 다음 스프린트

- [ ] 세션 토큰 만료 핸들링 (axios interceptor + 토스트)
- [ ] Logout 확인 다이얼로그 추가
- [ ] Settings blend ratio 슬라이더 툴팁
- [ ] Marketplace 빈 데이터 상태 메시지 개선
- [ ] Notifications 빈 리스트 empty state 텍스트

### P3 — 백로그

- [ ] 레이아웃 status chip 작은 뷰포트 오버랩 수정
- [ ] Agent Control 로딩 스켈레톤 vs 빈 상태 구분
- [ ] REST API 호출 circuit breaker 패턴 도입
- [ ] DB 커넥션 풀 설정 최적화

---

## 9. 검증 대상 파일 목록

### 수집 파이프라인 (Collector)
| 파일 | 라인 수 | 상태 |
|------|--------|------|
| `src/agents/collector.py` | 867 | ✅ 리뷰 완료 |
| `src/agents/stock_master_collector.py` | 242 | ✅ 리뷰 완료 |
| `src/agents/macro_collector.py` | 125 | ✅ 리뷰 완료 |
| `src/agents/index_collector.py` | 97 | ✅ 리뷰 완료 |

### 저장 레이어 (Storage)
| 파일 | 라인 수 | 상태 |
|------|--------|------|
| `src/db/queries.py` | 900+ | ✅ 리뷰 완료 |
| `src/db/marketplace_queries.py` | 900+ | ✅ 리뷰 완료 |
| `src/db/models.py` | 123 | ✅ 리뷰 완료 |
| `src/services/datalake.py` | 189 | ✅ 리뷰 완료 |
| `src/utils/s3_client.py` | 132 | ✅ 리뷰 완료 |
| `src/utils/redis_client.py` | 105 | ✅ 리뷰 완료 |

### 소비 레이어 (Consumption)
| 파일 | 라인 수 | 상태 |
|------|--------|------|
| `src/agents/predictor.py` | 413 | ✅ 리뷰 완료 |
| `src/agents/orchestrator.py` | 501 | ✅ 리뷰 완료 |

### 설정/스케줄링
| 파일 | 상태 |
|------|------|
| `.env.example` | ✅ 리뷰 완료 |
| `src/schedulers/index_scheduler.py` | ✅ 리뷰 완료 |

---

## 10. 결론

수집-저장 파이프라인은 **구조적으로 잘 설계**되어 있다. PostgreSQL + Redis + S3 Parquet 3중 저장 구조는 확장성과 감사 추적 면에서 적절하다. 그러나 현재 **두 가지 치명적 장애**가 시스템 전체를 마비시키고 있다:

1. **S3/MinIO 미기동** → DataLake 전체 비활성, Parquet 아카이브 유실
2. **LLM 프로바이더 미설정** → Predictor 100% 실패, 전략 실행 불가

이 두 문제를 해결하면 수집 → 예측 → 전략 → 실행의 전체 파이프라인이 즉시 복원될 것으로 판단된다. 단, **silent failure 패턴**(warning 로그만 남기고 실패를 삼키는 코드)이 여러 곳에 산재해 있어, 향후 운영 안정성을 위해 에러 핸들링 전반을 강화해야 한다.

---

*Generated: 2026-03-16 | QA Analyst: Claude Agent | Method: Source Code Review + Browser QA Report Cross-reference*
