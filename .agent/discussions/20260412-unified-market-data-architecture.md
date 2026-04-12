# 틱+일봉 통합 분석 레이어 아키텍처 결정

status: open
created_at: 2026-04-12
topic_slug: unified-market-data-architecture
related_files:
- src/db/queries.py
- src/agents/rl_dataset_builder_v2.py
- src/agents/collector/_realtime.py
- src/agents/collector/_daily.py
- src/services/datalake.py
- src/schedulers/unified_scheduler.py

## 1. 핵심 질문

틱 데이터와 일봉 데이터를 합쳐서 RL/LLM 분석에 활용 가능한 통합 데이터 레이어를 어떤 구조로 만들 것인가?

## 2. 배경

현재 상태:
- `ohlcv_daily`: 일봉, FDR/Yahoo에서 08:30 수집. RL + LLM 양쪽에서 사용
- `tick_data`: 실시간 틱, KIS WebSocket 09:00~15:30 수집. Redis 캐시 + API 실시간 조회용으로만 사용
- `get_ohlcv_bars()`: tick_data를 1분/5분/15분/1시간 봉으로 집계하는 함수 존재 (on-demand)
- RL은 일봉 6피처만 사용, LLM(Strategy A/B)은 일봉 + 매크로 컨텍스트만 사용
- 틱 데이터를 수집·저장하지만 전략 분석에 활용하지 않아 인프라 비용 대비 ROI가 낮음

## 3. 제약 조건

- 수집 파이프라인(tick_collector + daily collector)은 변경하지 않음 — 안정성 우선
- 월 운영비 목표: 5,000~10,000원
- GPU 없음 (Hetzner CX22)
- 과도한 설계 금지 (50종목, 일 117만 틱 규모)
- 분봉 데이터 40영업일 축적이 RL 학습 선행 조건

## 4. 선택지 비교

| 선택지 | 장점 | 단점 | 비용/복잡도 |
|--------|------|------|------------|
| A. DB 집계 테이블만 (ohlcv_minute) | PostgreSQL 안에서 완결, 쿼리 간편 | 90일 DROP 시 장기 데이터 영구 소실, DB에 데이터 두 벌 | 낮음 |
| B. Parquet 기반 데이터 레이크만 | DB 부담 최소, 대량 데이터 처리 유리 | 학습 시 S3 I/O 지연, 로컬 환경 S3 없이 테스트 어려움 | 중간 |
| C. 하이브리드 (DB 최근 90일 + Parquet 아카이브) | DB 항상 가벼움, 장기 데이터 보존, 백테스트 유연성 | 월 1회 아카이브 크론잡 추가 | 중간 (기존 S3 flush 패턴 재사용) |

## 5. 결정 사항

### 5.1 결정

**선택지 C: 하이브리드 (DB 최근 90일 + S3 Parquet 아카이브)**

데이터 플로우:
```
[수집 레이어 — 변경 없음]
FDR/Yahoo ──08:30──→ ohlcv_daily (일봉)
KIS WS ──09:00~15:30──→ tick_data (틱)

[집계 레이어 — 신규]
tick_data ──16:00 배치──→ ohlcv_minute (1분봉, vwap, trade_count 포함)
tick_data ──실시간──→ Redis 1분봉 캐시 (당일, 추론용)
ohlcv_minute ──월 1회──→ S3 Parquet 아카이브 (90일 초과분)

[분석 레이어 — 신규]
ohlcv_daily + ohlcv_minute → UnifiedMarketData
  ├─→ to_rl_features() → RL 학습/추론
  └─→ to_llm_context() → Strategy A/B 프롬프트
```

3축 평가:
- **확장성**: 장기 데이터가 S3에 보존되어 6개월/1년 백테스트 가능. DB는 90일만 유지하여 성능 안정
- **안전**: 수집 레이어 장애가 분석 레이어에 전파되지 않음. 분봉 데이터 없으면 기존 일봉 only Fallback
- **관리 수월함**: 월 1회 S3 아카이브는 기존 datalake.py S3 flush 패턴 재사용. 크론잡 하나 추가 수준

### 5.2 트레이드오프

- 안 A 대비 월 1회 크론잡이 추가되지만, 기존 S3 패턴 재사용이라 실질 부담 미미
- S3 아카이브 데이터 접근 시 Parquet 로드 지연이 있으나, 백테스트/재학습 용도라 실시간성 불필요
- DB + S3 두 곳에 데이터가 존재하지만, lifecycle이 명확 (최근 90일=DB, 이전=S3)

## 6. 실행 계획

| Phase | 시점 | 내용 | 완료 기준 |
|-------|------|------|----------|
| 0 | 즉시 | ohlcv_minute 테이블 + 집계 크론 + Redis 실시간 캐시 + 월 1회 S3 아카이브 | 집계 크론 정상 동작, 분봉 데이터 축적 시작 |
| 1 | 40영업일 후 | RL 분봉 피처 2개 추가 (vwap_deviation, volume_skew) | 8피처 모델 excess return > 6피처 모델 |
| 2 | Phase 1 검증 후 | LLM 장중 패턴 자연어 컨텍스트 추가 | 시그널 정확도 비교 |
| 3 | 성과 확인 후 | 추가 피처 (intraday_volatility, tick_intensity) + API 정식화 | UnifiedDataBuilder API 노출 |

## 7. 참조

### 7.1 참고 파일

- `src/db/queries.py:94-148` — get_ohlcv_bars() 분봉 집계 함수 (on-demand 패턴)
- `src/agents/rl_dataset_builder_v2.py:33-86` — 현재 RL 피처 셋 (일봉 기반 6피처)
- `src/agents/collector/_realtime.py` — 틱 수집 + 버퍼 flush 로직
- `src/services/datalake.py` — S3 flush/아카이브 패턴 (재사용 대상)
- `src/schedulers/unified_scheduler.py` — 크론잡 등록 (현재 10개)
- `docs/db/pg_tick_data.md` — tick_data 스키마 (시간별 파티션)
- `docs/db/pg_ohlcv_daily.md` — ohlcv_daily 스키마 (연별 파티션)

### 7.2 참고 소스

- `.agent/discussions/20260411-rl-intraday-feature-expansion.md` — RL 분봉 피처 확장 설계 (Phase 1의 근거)
- `.agent/discussions/20260412-unified-market-data-implementation.md` — 구현 상세 (이 문서의 후속)

### 7.3 영향받는 파일

- `src/db/models.py` — OhlcvMinute 모델 추가
- `src/db/queries.py` — 집계/조회 함수 추가
- `src/schedulers/unified_scheduler.py` — 크론잡 등록
- `src/agents/collector/_realtime.py` — Redis 분봉 캐시 갱신
- `src/services/datalake.py` — 월 1회 분봉 S3 아카이브
- `src/agents/rl_dataset_builder_v2.py` — UnifiedMarketData 통합 (Phase 1)
- DB 마이그레이션 SQL — ohlcv_minute 테이블 + 파티션

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
