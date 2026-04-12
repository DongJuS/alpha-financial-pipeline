# 틱+일봉 통합 분석 레이어 — 구현 상세

status: open
created_at: 2026-04-12
topic_slug: unified-market-data-implementation
related_files:
- src/db/models.py
- src/db/queries.py
- src/services/datalake.py
- src/services/unified_market_data.py
- src/schedulers/unified_scheduler.py
- src/agents/rl_dataset_builder_v2.py
- src/agents/rl_environment.py
- src/agents/rl_trading_v2.py
- src/agents/rl_runner.py

## 1. 핵심 질문

안 C(하이브리드: DB 최근 90일 + S3 Parquet 아카이브) 기반으로 ohlcv_minute 집계 테이블, S3 아카이브, UnifiedMarketData 빌더를 어떻게 구현할 것인가?

## 2. 배경

아키텍처 결정 문서(`.agent/discussions/20260412-unified-market-data-architecture.md`)에서 다음이 확정됨:
- 수집 파이프라인(tick_collector + daily collector)은 변경 없이 유지
- `ohlcv_minute` 집계 테이블을 중간 레이어로 추가
- DB에는 최근 90일만 유지, 이전 데이터는 S3 Parquet으로 아카이브
- `UnifiedMarketData` 빌더로 RL/LLM 양쪽에 통합 데이터 제공
- 4단계 Phase 실행 (0: 인프라 → 1: RL 피처 → 2: LLM 컨텍스트 → 3: 추가 피처)

이 문서는 Phase 0~2의 구체적 구현 상세를 다룬다.

## 3. 제약 조건

- 기존 수집 파이프라인 코드 변경 금지
- `get_ohlcv_bars()` (queries.py:94-148) on-demand 집계 함수는 유지 (실시간 추론용)
- DB 가격 타입은 INTEGER (한국 주식 원 단위 정수)
- 월 운영비 5,000~10,000원 한도 내
- 테스트는 `pip install -r requirements.txt` 후 `pytest`로 실행 가능해야 함

## 4. 선택지 비교

### 4.1 분봉 파생 피처 계산 위치

| 선택지 | 장점 | 단점 |
|--------|------|------|
| SQL에서 직접 계산 | DB 단일 쿼리로 완결 | 복잡한 서브쿼리, 테스트 어려움 |
| Python에서 계산 | 테스트 용이, 관심사 분리 | DB→Python 데이터 전송 필요 |

### 4.2 실시간 추론 데이터 소스

| 선택지 | 장점 | 단점 |
|--------|------|------|
| Redis 1분봉 캐시 (주기 갱신) | 추론 지연 최소 | 캐시 관리 복잡도, tick_collector 수정 필요 |
| on-demand 쿼리 (get_ohlcv_bars) | 구현 변경 없음, 코드 단순 | 매 추론마다 DB 쿼리 |

### 4.3 S3 아카이브 완료 확인 방식

| 선택지 | 장점 | 단점 |
|--------|------|------|
| S3 마커 파일 | DB/Redis 상태 불필요, S3가 single source of truth | S3 API 호출 필요 |
| DB 상태 테이블 | 빠른 조회 | 추가 테이블 관리 |

## 5. 결정 사항

### 5.1 결정

**피처 계산: Python** — DB에서는 단순 SELECT, 파생 피처 계산은 Python에서 수행. 테스트 용이성과 관심사 분리가 근거.

**실시간 추론: on-demand 쿼리** — RL 추론이 하루 1~2회이므로 `get_ohlcv_bars()` 직접 호출로 충분. Redis 캐시는 Phase 2(LLM 다중 호출)에서 단기 TTL(5분)로 추가 검토.

**S3 아카이브 확인: 마커 파일** — `s3://alpha-lake/ohlcv_minute/year=YYYY/month=MM/_ARCHIVED` 파일 존재 여부로 판단. 별도 상태 테이블 불필요.

### 5.2 트레이드오프

- Python 피처 계산은 데이터 전송 비용이 있으나, 120일 × 50종목 × 390분봉 = 234만 건 전송도 2~3초 수준으로 허용 범위
- on-demand 쿼리는 추론 빈도가 높아지면 병목이 될 수 있으나, 현재 규모에서는 문제 없음
- S3 마커 확인은 네트워크 호출이지만 월 1회이므로 무시 가능

## 6. 실행 계획

### 6.1 ohlcv_minute 테이블 DDL

```sql
CREATE TABLE ohlcv_minute (
    instrument_id  VARCHAR(20)    NOT NULL,
    bucket_at      TIMESTAMPTZ    NOT NULL,
    open           INTEGER        NOT NULL,
    high           INTEGER        NOT NULL,
    low            INTEGER        NOT NULL,
    close          INTEGER        NOT NULL,
    volume         BIGINT         NOT NULL DEFAULT 0,
    trade_count    INTEGER        NOT NULL DEFAULT 0,
    vwap           NUMERIC(15,2)  NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_id, bucket_at)
) PARTITION BY RANGE (bucket_at);

-- 초기 파티션 (3개월분)
CREATE TABLE ohlcv_minute_2026_04 PARTITION OF ohlcv_minute
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE ohlcv_minute_2026_05 PARTITION OF ohlcv_minute
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE ohlcv_minute_2026_06 PARTITION OF ohlcv_minute
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

파티셔닝: 월별. 시간별(tick_data 방식)은 파티션 과다, 일별도 90일 DROP 시 월별이 관리 편의성 우위.

### 6.2 집계 쿼리 (aggregate_ticks_to_minutes)

```sql
INSERT INTO ohlcv_minute (instrument_id, bucket_at, open, high, low, close, volume, trade_count, vwap)
SELECT
    instrument_id,
    date_trunc('minute', timestamp_kst) AS bucket_at,
    (array_agg(price ORDER BY timestamp_kst ASC))[1]   AS open,
    MAX(price)                                           AS high,
    MIN(price)                                           AS low,
    (array_agg(price ORDER BY timestamp_kst DESC))[1]  AS close,
    SUM(volume)                                          AS volume,
    COUNT(*)                                             AS trade_count,
    CASE WHEN SUM(volume) > 0
         THEN SUM(price::numeric * volume) / SUM(volume)
         ELSE 0 END                                      AS vwap
FROM tick_data
WHERE timestamp_kst >= $1
  AND timestamp_kst < $2
GROUP BY instrument_id, date_trunc('minute', timestamp_kst)
ON CONFLICT (instrument_id, bucket_at) DO UPDATE SET
    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
    close = EXCLUDED.close, volume = EXCLUDED.volume,
    trade_count = EXCLUDED.trade_count, vwap = EXCLUDED.vwap;
```

ON CONFLICT UPSERT로 멱등성 보장. 크론잡 실패 후 재실행 안전.

### 6.3 분봉 파생 피처 계산 (Python)

```python
@dataclass
class IntradayFeatures:
    vwap_deviation: float      # (close - vwap) / vwap, clamp [-1, 1]
    volume_skew: float         # am_volume / total_volume - 0.5
    intraday_volatility: float # Phase 3용, 기본 0.0
    tick_intensity: float      # Phase 3용, 기본 0.0

def compute_intraday_features(bars: list[dict]) -> IntradayFeatures:
    if not bars:
        return IntradayFeatures(0.0, 0.0, 0.0, 0.0)
    last_close = bars[-1]["close"]
    total_volume = sum(b["volume"] for b in bars)
    daily_vwap = sum(b["vwap"] * b["volume"] for b in bars) / max(total_volume, 1)
    vwap_deviation = (last_close - daily_vwap) / daily_vwap if daily_vwap > 0 else 0.0
    am_volume = sum(b["volume"] for b in bars if b["bucket_at"].hour < 12)
    volume_skew = (am_volume / max(total_volume, 1)) - 0.5
    return IntradayFeatures(
        vwap_deviation=max(-1.0, min(1.0, vwap_deviation)),
        volume_skew=volume_skew,
        intraday_volatility=0.0,
        tick_intensity=0.0,
    )
```

### 6.4 S3 Parquet 아카이브

S3 키 구조:
```
s3://alpha-lake/ohlcv_minute/year=2026/month=01/
    ├── 005930.KS.parquet
    ├── 000660.KS.parquet
    └── _ARCHIVED          ← 마커 파일
```

종목별 파일 분리: 특정 종목 장기 데이터만 로드 시 효율적.
압축: zstd (기존 datalake.py 패턴과 동일).
예상 용량: 50종목 × 22영업일 × 390분봉 = ~429,000건/월 → Parquet(zstd) ~3~5MB/월.

PyArrow 스키마:
```python
OHLCV_MINUTE_SCHEMA = pa.schema([
    ("instrument_id", pa.string()),
    ("bucket_at", pa.timestamp("ms")),
    ("open", pa.int32()),
    ("high", pa.int32()),
    ("low", pa.int32()),
    ("close", pa.int32()),
    ("volume", pa.int64()),
    ("trade_count", pa.int32()),
    ("vwap", pa.float64()),
])
```

### 6.5 크론잡 스케줄

| 잡 ID | 시간 | 주기 | Lock TTL | 내용 |
|--------|------|------|----------|------|
| `minute_aggregation` | 15:50 KST | 매일 평일 | 300초 | tick_data → ohlcv_minute 배치 집계 |
| `minute_partition_mgmt` | 00:05 KST | 매월 1일 | 120초 | 다음 달 파티션 생성 + 3개월 전 아카이브→DROP |

`minute_aggregation` 위치: s3_tick_flush(15:40) 이후, rl_retrain(16:00) 이전.

`minute_partition_mgmt` 실행 순서:
1. 다음 달 파티션 CREATE IF NOT EXISTS
2. 3개월 전 데이터 → S3 Parquet 아카이브 (archive_minute_bars)
3. S3 마커 파일(_ARCHIVED) 존재 확인
4. 확인되면 3개월 전 파티션 DROP
5. 마커 미확인 시 DROP 스킵 + Telegram 알림

### 6.6 RL 통합 (Phase 1)

`rl_dataset_builder_v2.py` build_dataset() 확장:
- 기존 `fetch_recent_market_data()` 호출 후
- `fetch_minute_bars_by_date()` 추가 호출
- 날짜별 `compute_intraday_features()` 실행
- `EnrichedRLDataset`에 `intraday_features` 필드 추가

`to_state_vector()` 확장:
- 해당 날짜의 vwap_deviation, volume_skew를 벡터에 추가
- 분봉 데이터 없는 날짜는 0.0 (Fallback)

`rl_environment.py` feature_columns에 `vwap_deviation`, `volume_skew` 추가.
`rl_trading_v2.py` 버켓 2개 추가 (상태 공간 27→243), 에피소드 60→120, 시드 5→8.

### 6.7 LLM 통합 (Phase 2)

`unified_market_data.py`에 `to_llm_context()` 함수 추가:
```
장중 패턴 요약:
- VWAP 대비 위치: 종가가 VWAP 대비 +1.2% (매수 우위)
- 거래량 분포: 오전 62% 집중 (기관 매집 패턴 가능)
- 장중 변동성: 20일 평균 대비 1.3배 (변동성 확대)
```

토큰 증가: ~150토큰/종목. 5종목이면 750토큰 추가. 비용 영향 미미.
Strategy A/B 프롬프트 템플릿에 `{intraday_context}` 슬롯 추가.
다중 호출(Strategy A 5회 + Strategy B 토론 3라운드) 시 Redis 단기 캐시(TTL 5분) 검토.

### 6.8 PR 단위

| PR | Phase | 내용 | 변경 파일 |
|----|-------|------|----------|
| 1 | 0-A | ohlcv_minute 인프라 + 집계 크론 | DDL, models.py, queries.py, unified_scheduler.py |
| 2 | 0-B | S3 아카이브 + 파티션 관리 | datalake.py, unified_scheduler.py |
| 3 | 0-C | UnifiedMarketData 빌더 | unified_market_data.py (신규) |
| 4 | 1 | RL 피처 통합 | rl_dataset_builder_v2.py, rl_environment.py, rl_trading_v2.py, rl_runner.py |
| 5 | 2 | LLM 컨텍스트 | unified_market_data.py, Strategy A/B 프롬프트 |

PR 1~3은 병렬 또는 순차로 즉시 착수 가능 (데이터 축적과 독립).

### 6.9 테스트 전략

**단위 테스트 (Phase 0):**
- `compute_intraday_features()`: 정상 분봉 입력 → 올바른 vwap_deviation/volume_skew
- `compute_intraday_features([])`: 빈 입력 → 모든 값 0.0 (Fallback)
- `archive_minute_bars()`: mock S3 → Parquet 직렬화 + 마커 생성 확인
- `aggregate_ticks_to_minutes()`: tick fixture → ohlcv_minute 정합성
- 멱등성: aggregate 2회 실행 → 동일 결과

**성과 테스트 (Phase 1):**
- 6피처 모델 vs 8피처 모델 백테스트 비교 (최소 3종목)
- excess return > 0 (8피처가 6피처보다 나아야 함)
- MDD 악화 < 5%p

## 7. 참조

### 7.1 참고 파일

- `src/db/queries.py:94-148` — get_ohlcv_bars() 기존 on-demand 분봉 집계 (집계 SQL 패턴 참고)
- `src/db/models.py:58-70` — OHLCVDaily 모델 (OhlcvMinute 모델의 참고 기준)
- `src/services/datalake.py:26-35` — DataType 열거형 (OHLCV_MINUTE 추가 위치)
- `src/services/datalake.py:138-158` — _to_parquet_bytes() (Parquet 직렬화 재사용)
- `src/services/datalake.py:286-340` — flush_ticks_to_s3() (시간대별 그룹핑 패턴 참고)
- `src/schedulers/unified_scheduler.py:44-58` — _LOCK_TTL 정의 (minute_aggregation 추가 위치)
- `src/schedulers/unified_scheduler.py:445-461` — s3_tick_flush 잡 등록 (minute_aggregation 등록 위치 참고)
- `src/agents/rl_dataset_builder_v2.py:199-254` — build_dataset() (분봉 피처 주입 지점)
- `src/agents/rl_dataset_builder_v2.py:334-368` — to_state_vector() (벡터 확장 지점)
- `src/agents/rl_environment.py:50-58` — feature_columns (vwap_deviation, volume_skew 추가 위치)
- `src/agents/collector/models.py:9-19` — TickData 모델 (집계 입력 스키마 확인)
- `src/agents/collector/_realtime.py:50-71` — _flush_tick_buffer() (수정하지 않음을 확인)
- `docs/db/pg_tick_data.md` — tick_data 스키마 (집계 소스 테이블)
- `docs/db/pg_ohlcv_daily.md` — ohlcv_daily 스키마 (가격 타입 참고)

### 7.2 참고 소스

- `.agent/discussions/20260412-unified-market-data-architecture.md` — 아키텍처 결정 (안 C 채택 근거)
- `.agent/discussions/20260411-rl-intraday-feature-expansion.md` — RL 분봉 피처 확장 설계 (Phase 1 기반)

### 7.3 영향받는 파일

Phase 0 (신규):
- `docs/db/pg_ohlcv_minute.md`
- `k8s/migrations/007_ohlcv_minute.sql`
- `src/services/unified_market_data.py`
- `test/test_unified_market_data.py`
- `test/test_minute_aggregation.py`

Phase 0 (수정):
- `src/db/models.py`
- `src/db/queries.py`
- `src/services/datalake.py`
- `src/schedulers/unified_scheduler.py`

Phase 1 (수정):
- `src/agents/rl_dataset_builder_v2.py`
- `src/agents/rl_environment.py`
- `src/agents/rl_trading_v2.py`
- `src/agents/rl_runner.py`

Phase 2 (수정):
- `src/services/unified_market_data.py`
- Strategy A/B 프롬프트 템플릿

## 8. Archive Migration

> 구현 완료 후 아카이브 시 아래 내용을 `MEMORY-archive.md`에 기록한다.
> 200자(한글 기준) 이내, 배경지식 없이 이해 가능하게 작성.

```
(구현 완료 후 작성)
```

## 9. Closure Checklist

- [ ] 구조/장기 방향 변경 → `.agent/roadmap.md` 반영
- [ ] 이번 세션 할 일 → `progress.md` 반영
- [ ] 운영 규칙 → `MEMORY.md` 반영
- [ ] 섹션 8의 Archive Migration 초안 작성
- [ ] `/discussion --archive <이 파일>` 실행
