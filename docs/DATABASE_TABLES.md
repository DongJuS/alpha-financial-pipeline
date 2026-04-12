# DATABASE_TABLES.md

> **정책: 이 문서는 항상 200줄 이내를 유지한다.**

DDL 정의: `scripts/db/init_db.py` | 쿼리: `src/db/queries.py`, `src/db/marketplace_queries.py`
상세 문서: `docs/db/{db}_{테이블명}.md` | 비-RDB: `docs/db/redis_keys.md`, `docs/db/minio_alpha_lake.md`

---

## 저장소 구성

| 종류 | 인스턴스 | 용도 | 상세 |
|------|----------|------|------|
| PostgreSQL 15 | alpha_db | 운영 데이터 (영속) | 아래 테이블 참조 |
| PostgreSQL 15 | alpha_gen_db | 시뮬레이션 격리 (`--profile gen`) | alpha_db 동일 스키마 |
| Redis 7 | redis:6379/0 | 캐시 + Pub/Sub | [redis_keys](db/redis_keys.md) |
| MinIO (S3) | minio:9000 | 콜드 데이터 아카이브 (Parquet) | [minio_alpha_lake](db/minio_alpha_lake.md) |

---

## 사용자

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **users** | 대시보드 로그인/권한 | ✅ | → watchlist.user_id | [상세](db/pg_users.md) |

## 시장 데이터

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **markets** | 거래소 메타 (KOSPI, KOSDAQ, NYSE, NASDAQ) | ✅ | → instruments.market_id | [상세](db/pg_markets.md) |
| **instruments** | 종목 마스터 (CODE.SUFFIX 정규화) | ✅ | ← markets / → ohlcv_daily, tick_data | [상세](db/pg_instruments.md) |
| **ohlcv_daily** | 일봉 OHLCV (연도별 파티셔닝 2010~2027) | ✅ | ← instruments | [상세](db/pg_ohlcv_daily.md) |
| **tick_data** | 실시간 틱 (timestamp_kst 파티셔닝) | ✅ | ← instruments | [상세](db/pg_tick_data.md) |
| **ohlcv_minute** | 1분봉 집계 (bucket_at 월별 파티셔닝) | ✅ | ← tick_data 집계 | [상세](db/pg_ohlcv_minute.md) |
| **market_data** | 레거시 OHLCV 통합 | ⚠️ 폐지예정 | 없음 (ohlcv_daily로 이관 중) | [상세](db/pg_market_data.md) |

## 예측 & 신호

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **predictions** | 전략 A/B/RL/S/L 예측 신호 | ✅ | → debate_transcripts.id | [상세](db/pg_predictions.md) |
| **debate_transcripts** | 전략 B 4인 토론 전문 | ✅ | ← predictions | [상세](db/pg_debate_transcripts.md) |
| **predictor_tournament_scores** | Predictor별 일별 정확도 → 승자 결정 | ✅ | agent_id 논리 참조 | [상세](db/pg_predictor_tournament_scores.md) |
| **model_role_configs** | 전략별 에이전트 설정 (5 Predictor + 4 Consensus) | ✅ | agent_id 논리 참조 | [상세](db/pg_model_role_configs.md) |

## 포트폴리오 & 거래

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **portfolio_config** | 글로벌 정책 (혼합비, 최대포지션, 손실한도) | ✅ | 단일 행 | [상세](db/pg_portfolio_config.md) |
| **trading_accounts** | 계좌 메타 (paper/real/virtual) | ✅ | → positions, trades, orders, snapshots | [상세](db/pg_trading_accounts.md) |
| **portfolio_positions** | 현재 보유 포지션 (account_scope별) | ✅ | ← trading_accounts | [상세](db/pg_portfolio_positions.md) |
| **trade_history** | 체결 거래 기록 (paper/real/virtual 통합) | ✅ | ← trading_accounts | [상세](db/pg_trade_history.md) |
| **broker_orders** | KIS 주문 추적 (요청→체결/거부) | ✅ | ← trading_accounts | [상세](db/pg_broker_orders.md) |
| **account_snapshots** | 일일 계좌 스냅샷 (수익성 추적) | ✅ | ← trading_accounts | [상세](db/pg_account_snapshots.md) |

## 모니터링 & 감사

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **agent_registry** | 에이전트 중앙 레지스트리 (11개 기본) | ✅ | → heartbeats.agent_id | [상세](db/pg_agent_registry.md) |
| **agent_heartbeats** | 에이전트 상태 (healthy/degraded/error/dead) | ✅ | ← agent_registry | [상세](db/pg_agent_heartbeats.md) |
| **notification_history** | 알림 발송 이력 | ✅ | 독립 | [상세](db/pg_notification_history.md) |
| **collector_errors** | 데이터 수집 오류 로그 | ✅ | 독립 | [상세](db/pg_collector_errors.md) |
| **real_trading_audit** | paper→real 전환 감사 추적 | ✅ | 독립 | [상세](db/pg_real_trading_audit.md) |
| **operational_audits** | 보안/리스크/재조정 검증 기록 | ✅ | 독립 | [상세](db/pg_operational_audits.md) |
| **paper_trading_runs** | 장기 백테스팅 결과 | ✅ | 독립 | [상세](db/pg_paper_trading_runs.md) |

## 마켓플레이스

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **krx_stock_master** | KRX 전종목 마스터 (ticker, sector, tier) | ✅ | ← theme_stocks, watchlist | [상세](db/pg_krx_stock_master.md) |
| **ticker_master** | 정규화 티커 통합 (stock/etf/index 등) | ✅ | 독립 | [상세](db/pg_ticker_master.md) |
| **theme_stocks** | 테마→종목 매핑 (반도체, EV, 바이오) | ✅ | ticker → krx_stock_master | [상세](db/pg_theme_stocks.md) |
| **macro_indicators** | 매크로 지표 (지수/환율/원자재/금리) | ✅ | 독립 | [상세](db/pg_macro_indicators.md) |
| **daily_rankings** | 일별 사전계산 랭킹 (시총/거래량/상승률) | ✅ | ticker → krx_stock_master | [상세](db/pg_daily_rankings.md) |
| **watchlist** | 사용자 관심 종목 (그룹별, 알림 설정) | ✅ | ← users, ticker → krx_stock_master | [상세](db/pg_watchlist.md) |

## 전략 승격 & 리스크

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **strategy_promotions** | virtual→paper→real 승격 감사 | ✅ | strategy_id 논리 참조 | [상세](db/pg_strategy_promotions.md) |
| **aggregate_risk_snapshots** | 시스템 전체 리스크 메트릭 히스토리 | ✅ | 독립 | [상세](db/pg_aggregate_risk_snapshots.md) |

## 백테스트

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **backtest_runs** | 백테스트 실행 메타 (전략/기간/수익률) | ✅ | → backtest_daily.run_id | [상세](db/pg_backtest_runs.md) |
| **backtest_daily** | 백테스트 일별 스냅샷 | ✅ | ← backtest_runs | [상세](db/pg_backtest_daily.md) |

## 리서치 파이프라인 (Strategy S — 보류)

| 테이블 | 역할 | 사용 | 관계 | 상세 |
|--------|------|:----:|------|------|
| **search_queries** | SearXNG 검색 요청 기록 | ❌ 보류 | → search_results | [상세](db/pg_search_queries.md) |
| **search_results** | 검색 엔진별 결과 | ❌ 보류 | ← search_queries → page_extractions | [상세](db/pg_search_results.md) |
| **page_extractions** | URL 콘텐츠 추출/구조화 | ❌ 보류 | ← search_results | [상세](db/pg_page_extractions.md) |
| **research_outputs** | Claude 추론 리서치 계약서 | ❌ 보류 | ← search_queries | [상세](db/pg_research_outputs.md) |

---

## 범례

- ✅ 활성 사용 중 | ⚠️ 폐지 예정 | ❌ 미사용/보류
- 총 **38개 테이블** + alpha_gen_db (동일 스키마) + Redis 캐시/Pub·Sub + MinIO 데이터 레이크
