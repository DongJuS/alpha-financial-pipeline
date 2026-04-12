# 틱+일봉 통합 분석 레이어 Phase 0 — 구현 착수 검증

status: done
created_at: 2026-04-12
topic_slug: unified-market-data-phase0-implementation
related_files:
- src/db/models.py
- src/db/queries.py
- src/services/datalake.py
- src/services/unified_market_data.py
- src/schedulers/unified_scheduler.py
- scripts/db/migrate_ohlcv_minute.py

## 1. 핵심 질문

기존 아키텍처+구현 상세 설계를 바탕으로 Phase 0 구현을 3개 PR로 분할하여 병렬 착수할 때, 빈틈이나 재검토할 사항이 있는가?

## 2. 배경

아키텍처 결정(안 C: 하이브리드 DB 90일 + S3 Parquet 아카이브)과 구현 상세가 이미 확정됨:
- `20260412-unified-market-data-architecture.md` — 데이터 플로우, Phase 0~3 계획
- `20260412-unified-market-data-implementation.md` — DDL, 집계 SQL, 크론잡, PR 단위, 테스트 전략

이번 토론은 구현 착수 전 최종 검증이다.

## 3. 제약 조건

- 수집 파이프라인(tick_collector + daily collector) 코드 변경 금지
- 기존 `get_ohlcv_bars()` on-demand 함수 유지
- DB 가격 타입 INTEGER, vwap은 NUMERIC(15,2)
- 기존 datalake.py 패턴(DataType enum + _to_parquet_bytes + _upload_with_retry) 재사용
- 기존 unified_scheduler.py 패턴(_LOCK_TTL + _locked_job) 재사용
- 마이그레이션은 scripts/db/ Python 스크립트 패턴 유지

## 4. 선택지 비교

### 4.1 ohlcv_minute 테이블 필요성

| 선택지 | 장점 | 단점 |
|--------|------|------|
| get_ohlcv_bars() on-demand만 사용 | 테이블 추가 없음 | RL 학습 시 40일 × 50종목 반복 집계 → DB 부하 |
| ohlcv_minute pre-materialized | 집계 1회, 이후 단순 SELECT | 테이블 + 크론잡 추가 |

### 4.2 파티셔닝 방식

| 선택지 | 장점 | 단점 |
|--------|------|------|
| 파티셔닝 없음 | 단순 | 175만 건(90일) DROP 시 DELETE 필요 |
| 월별 RANGE | 파티션 DROP으로 빠른 삭제 | 관리 크론 필요 |

### 4.3 Phase 0 범위

| 선택지 | 장점 | 단점 |
|--------|------|------|
| DDL+집계만 (S3 아카이브 나중에) | 최소 범위 | 파티션 관리가 빠짐 |
| DDL+집계+S3 아카이브+빌더 전부 | 완결성 | 3개월 후에나 실행되는 코드 포함 |

## 5. 결정 사항

### 5.1 결정

**ohlcv_minute 테이블 필요** — on-demand 집계로는 RL 학습 시 78만 건 반복 집계 비효율.

**월별 파티셔닝** — S3 아카이브 후 파티션 DROP 편의성. 175만 건 DELETE보다 안전하고 빠름.

**Phase 0 전체 구현 (3개 PR 병렬)** — S3 아카이브는 3개월 후 첫 실행이지만 datalake.py 패턴 재사용으로 복잡도 낮음. 파티션 관리 크론의 "다음 달 파티션 CREATE" 부분은 즉시 필요.

### 5.2 트레이드오프

- S3 아카이브 코드가 3개월간 실행되지 않지만, 패턴 재사용으로 코드량 미미
- 크론잡 2개 추가로 스케줄러 복잡도 약간 증가 (10→12 잡)

## 6. 실행 계획

| PR | 내용 | 변경/신규 파일 | 완료 기준 |
|----|------|---------------|----------|
| PR 1 | ohlcv_minute DDL + 집계 크론 + 초기 파티션 | migrate_ohlcv_minute.py, models.py, queries.py, unified_scheduler.py, pg_ohlcv_minute.md, 테스트 | 집계 크론 등록, 마이그레이션 실행 가능 |
| PR 2 | S3 Parquet 아카이브 + 파티션 관리 크론 | datalake.py, unified_scheduler.py, 테스트 | 아카이브 함수 + 파티션 관리 크론 등록 |
| PR 3 | UnifiedMarketData 빌더 + compute_intraday_features | unified_market_data.py(신규), 테스트 | 빌더 함수 + 피처 계산 단위 테스트 통과 |

## 7. 참조

### 7.1 참고 파일

- `src/db/models.py:58-70` — OHLCVDaily 모델 (OhlcvMinute 패턴 참고)
- `src/db/queries.py:94-148` — get_ohlcv_bars() (집계 SQL 패턴)
- `src/services/datalake.py:26-35` — DataType enum (OHLCV_MINUTE 추가 위치)
- `src/services/datalake.py:138-158` — _to_parquet_bytes() (재사용)
- `src/services/datalake.py:286-340` — flush_ticks_to_s3() (시간대별 그룹핑 패턴)
- `src/schedulers/unified_scheduler.py:44-58` — _LOCK_TTL (크론잡 추가 위치)
- `src/schedulers/unified_scheduler.py:445-461` — s3_tick_flush 잡 등록 (패턴 참고)
- `scripts/db/migrate_rl_targets.py` — 마이그레이션 스크립트 패턴
- `src/agents/collector/models.py:9-19` — TickData 모델 (집계 입력 스키마)

### 7.2 참고 소스

- `.agent/discussions/20260412-unified-market-data-architecture.md`
- `.agent/discussions/20260412-unified-market-data-implementation.md`
- `.agent/discussions/20260411-rl-intraday-feature-expansion.md`

### 7.3 영향받는 파일

PR 1: scripts/db/migrate_ohlcv_minute.py(신규), src/db/models.py, src/db/queries.py, src/schedulers/unified_scheduler.py, docs/db/pg_ohlcv_minute.md(신규), test/test_minute_aggregation.py(신규)
PR 2: src/services/datalake.py, src/schedulers/unified_scheduler.py, test/test_minute_archive.py(신규)
PR 3: src/services/unified_market_data.py(신규), test/test_unified_market_data.py(신규)

## 8. Archive Migration

> 구현 완료 후 아카이브 시 아래 내용을 `MEMORY-archive.md`에 기록한다.

```
틱+일봉 통합 분석 레이어 Phase 0 구현 (PR #178~#180). 안 C(하이브리드) 채택: ohlcv_minute 테이블(월별 파티셔닝) + 15:50 배치 집계 크론 + S3 Parquet 종목별 아카이브(매월 1일, 마커 확인 후 DROP) + UnifiedMarketData 빌더(compute_intraday_features: vwap_deviation, volume_skew). 수집 파이프라인 무변경. Phase 1(RL 피처 통합)은 분봉 40영업일 축적 후.
```

## 9. Closure Checklist

- [x] 구조/장기 방향 변경 → `.agent/roadmap.md` 반영
- [x] 이번 세션 할 일 → `progress.md` 반영
- [ ] 운영 규칙 → `MEMORY.md` 반영 (해당 없음)
- [x] 섹션 8의 Archive Migration 초안 작성
- [ ] `/discussion --archive <이 파일>` 실행
