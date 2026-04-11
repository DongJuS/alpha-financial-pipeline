# Step 8b 후속 구현: Predictor 분봉 통합 + S3 틱 최적화

status: open
created_at: 2026-04-11
topic_slug: step8b-followup-implementation
related_files:
- src/agents/predictor.py
- src/services/datalake.py
- src/agents/collector/_realtime.py
- src/schedulers/unified_scheduler.py

## 1. 핵심 질문

Step 8b에서 완성한 틱 저장소(tick_data + get_ohlcv_bars)를 실제로 활용하고, S3 저장 효율을 개선하는 구현을 어떻게 진행할 것인가?

## 2. 배경

Step 8b에서 틱 전용 저장소와 분봉 집계 함수를 완성했으나, 실제 활용이 0%인 상태였다:
- `get_ohlcv_bars()`가 구현되어 있지만 아무 코드에서 호출하지 않음
- Predictor는 일봉(30일)만 보고 매매 판단
- 매 틱마다 S3에 소량 파일을 쓰는 비효율적 구조

후속 작업 3개 중 즉시 실행 가능한 2개를 구현:
1. Predictor에 분봉 데이터 통합
2. S3 틱 저장 최적화 (hour 파티셔닝 + flush 분리)

3번(RL 분봉 피처 확장)은 분봉 데이터 40영업일 축적 필요하여 보류.

## 3. 제약 조건

- 기존 PredictionSignal 인터페이스 유지 (블렌딩·백테스트 호환)
- LLM 토큰 비용 증가 최소화 (5분봉 대신 1시간봉 선택)
- 분봉 데이터 없는 시간(장외/주말)에도 기존과 동일하게 동작
- 다른 DataType의 S3 키 형식에 영향 없어야 함

## 4. 선택지 비교

### Predictor 분봉 간격 선택

| 선택지 | 프롬프트 추가량 | 비용 영향 | 정보 밀도 |
|--------|---------------|----------|----------|
| 5분봉 (당일) | ~78행 | 높음 | 높음 |
| 1시간봉 (당일) | ~7행 | 낮음 | 중간 |
| 15분봉 (당일) | ~26행 | 중간 | 중간~높음 |

### S3 flush 방식

| 선택지 | 파일 수/일 | 장점 | 단점 |
|--------|-----------|------|------|
| 매 틱마다 (현행) | 수만 개 | 즉시 S3 반영 | PUT 비용, I/O 부하 |
| 장 종료 후 일괄 | ~7개 | 비용/효율 최적 | 장중 S3 미반영 |

## 5. 결정 사항

### 5.1 결정

**Predictor: 당일 1시간봉 통합**
- `predictor.py`에 `_fetch_intraday_bars()` 추가 → `get_ohlcv_bars('1hour', 오늘 00:00, now)` 호출
- 1시간봉이면 당일 최대 ~7행으로 토큰 증가 미미
- `run_once()`에서 일봉/포지션과 함께 병렬 fetch
- `_llm_signal()`에 `intraday_bars` 파라미터 추가, 데이터 있으면 프롬프트에 "오늘 장중 1시간봉" 섹션 포함
- 데이터 없으면(빈 리스트/None) 기존과 동일하게 일봉만 사용

**S3: hour 파티셔닝 + 크론 flush 분리**
- `_make_s3_key()`에 optional `hour` 파라미터 추가 (미지정 시 기존 형식 유지)
- `_flush_tick_buffer()`에서 S3 호출 제거 → DB INSERT만 수행
- `flush_ticks_to_s3()` 신규 함수: DB에서 당일 틱 조회 → 시간대별 그룹핑 → hour 파티셔닝된 S3 파일 생성
- APScheduler 크론 15:40 KST 등록 (`s3_tick_flush`)

3축 평가:
- **확장성**: hour 파티셔닝으로 Athena/DuckDB 파티션 자동 인식. 분봉 간격은 상수로 변경 가능
- **안전**: 분봉 없으면 fallback, S3 실패해도 DB 수집 무영향, 크론 실패 시 수동 CLI 가능
- **관리 수월함**: predictor.py 1파일 수정, S3 변경은 3파일 + 크론 1건

### 5.2 트레이드오프

- 1시간봉은 5분봉 대비 세밀한 장중 움직임을 놓칠 수 있음. 효과 확인 후 간격 조절
- 장중에 S3에 당일 틱이 없음 → 실시간 조회는 Redis/DB에서 하므로 문제 없음
- 크론 실패 시 당일 틱 S3 미저장 → 다음날 수동 실행 또는 자동 재시도 후속 추가

## 6. 실행 계획

| 순서 | 항목 | 변경 대상 파일 | 완료 기준 |
|------|------|---------------|----------|
| 1 | Predictor 분봉 fetch + 프롬프트 통합 | `src/agents/predictor.py` | 1시간봉 데이터가 LLM 프롬프트에 포함됨 ✅ |
| 2 | `_make_s3_key()` hour 파라미터 추가 | `src/services/datalake.py` | hour 지정 시 `hour=09` 경로 생성 ✅ |
| 3 | `_flush_tick_buffer()` S3 호출 제거 | `src/agents/collector/_realtime.py` | DB INSERT만 수행 ✅ |
| 4 | `flush_ticks_to_s3()` 일괄 함수 추가 | `src/services/datalake.py` | 시간대별 파일 생성 ✅ |
| 5 | APScheduler 크론 15:40 등록 | `src/schedulers/unified_scheduler.py` | `s3_tick_flush` 잡 등록 ✅ |
| 6 | 테스트 추가/수정 | `test/test_tick_storage.py`, `test/test_scheduler_market_flow.py` | 61 passed ✅ |

## 7. 참조

### 7.1 참고 파일

- `src/agents/predictor.py:67-76` — `_fetch_intraday_bars()` 신규 추가
- `src/agents/predictor.py:78-140` — `_llm_signal()` intraday_bars 파라미터 추가
- `src/services/datalake.py:161-178` — `_make_s3_key()` hour 파라미터 추가
- `src/services/datalake.py:286-338` — `flush_ticks_to_s3()` 신규 추가
- `src/agents/collector/_realtime.py:67-72` — S3 호출 제거, DB INSERT만
- `src/schedulers/unified_scheduler.py:284-298` — `s3_tick_flush` 크론 등록

### 7.2 참고 소스

- `.agent/discussions/20260411-tick-realtime-strategy-design.md` — Predictor 분봉 통합 설계
- `.agent/discussions/20260411-s3-tick-optimization.md` — S3 최적화 설계
- `.agent/discussions/20260411-rl-intraday-feature-expansion.md` — RL 피처 확장 (보류)

### 7.3 영향받는 파일

- `src/agents/predictor.py`
- `src/services/datalake.py`
- `src/agents/collector/_realtime.py`
- `src/schedulers/unified_scheduler.py`
- `test/test_tick_storage.py`
- `test/test_scheduler_market_flow.py`

## 8. Archive Migration

```
Step 8b 후속 구현 완료: (1) Predictor에 당일 1시간봉 통합 — get_ohlcv_bars('1hour')로 장중 데이터를 fetch하여 LLM 프롬프트에 포함, 데이터 없으면 일봉만 fallback. (2) S3 틱 최적화 — _make_s3_key()에 hour 파라미터 추가(Hive-style date/hour 파티셔닝), _flush_tick_buffer()에서 S3 제거 후 장 종료 크론(15:40 KST)으로 DB→S3 시간대별 일괄 flush. RL 피처 확장은 분봉 데이터 40영업일 축적 후 진행.
```

## 9. Closure Checklist

- [ ] 구조/장기 방향 변경 → `.agent/roadmap.md` 반영
- [ ] 이번 세션 할 일 → `progress.md` 반영
- [ ] 운영 규칙 → `MEMORY.md` 반영
- [ ] 섹션 8의 Archive Migration 초안 작성
- [ ] `/discussion --archive <이 파일>` 실행
