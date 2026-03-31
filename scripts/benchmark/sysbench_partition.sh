#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# sysbench_partition.sh — ohlcv_daily 파티셔닝 효과 측정
# ─────────────────────────────────────────────────────────────────────
# PostgreSQL의 연도별 파티셔닝(2010~2027)이 쿼리 성능에 미치는 효과를
# EXPLAIN ANALYZE로 직접 비교합니다.
# (sysbench는 MySQL 전용이므로, psql EXPLAIN ANALYZE 기반으로 측정)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-alpha_db}"
DB_USER="${DB_USER:-alpha_user}"
DB_PASS="${DB_PASS:-alpha_pass}"

export PGPASSWORD="$DB_PASS"

RESULT_DIR="${RESULT_DIR:-$(dirname "$0")/results}"
mkdir -p "$RESULT_DIR"
OUTFILE="$RESULT_DIR/partition_analysis.txt"

PSQL="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"

# ── 샘플 종목 선택 ────────────────────────────────────────────────
SAMPLE_TICKER=$($PSQL -tAc \
    "SELECT instrument_id FROM ohlcv_daily
     GROUP BY instrument_id
     HAVING count(*) > 1000
     ORDER BY random() LIMIT 1;")

if [ -z "$SAMPLE_TICKER" ]; then
    SAMPLE_TICKER=$($PSQL -tAc \
        "SELECT instrument_id FROM ohlcv_daily LIMIT 1;")
fi

echo "================================================================" | tee "$OUTFILE"
echo "  파티셔닝 효과 분석 — ohlcv_daily"                                  | tee -a "$OUTFILE"
echo "================================================================" | tee -a "$OUTFILE"
echo "" | tee -a "$OUTFILE"
echo "  테스트 종목: $SAMPLE_TICKER" | tee -a "$OUTFILE"
echo "" | tee -a "$OUTFILE"

# ── 파티션 구조 확인 ──────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [INFO] 파티션 목록"                                            | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "SELECT schemaname, tablename,
            pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS size
       FROM pg_tables
      WHERE tablename LIKE 'ohlcv_daily_%'
      ORDER BY tablename;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ── 테이블 전체 통계 ─────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [INFO] 테이블 통계"                                            | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "SELECT
         to_char(count(*), 'FM999,999,999') AS total_rows,
         to_char(count(DISTINCT instrument_id), 'FM999,999') AS unique_tickers,
         min(traded_at) AS min_date,
         max(traded_at) AS max_date,
         pg_size_pretty(pg_total_relation_size('ohlcv_daily')) AS total_size
       FROM ohlcv_daily;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ──────────────────────────────────────────────────────────────────
# 테스트 1: 파티션 프루닝이 작동하는 쿼리 (단일 연도 범위)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [TEST 1] 파티션 프루닝 — 단일 종목, 최근 30일"                    | tee -a "$OUTFILE"
echo "  예상: 해당 연도 파티션만 스캔 (pruning 작동)"                      | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
     SELECT instrument_id, traded_at, open, high, low, close, volume
       FROM ohlcv_daily
      WHERE instrument_id = '$SAMPLE_TICKER'
        AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
      ORDER BY traded_at DESC;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ──────────────────────────────────────────────────────────────────
# 테스트 2: 특정 연도 범위 쿼리 (프루닝 작동)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [TEST 2] 파티션 프루닝 — 단일 종목, 2025년 데이터"              | tee -a "$OUTFILE"
echo "  예상: ohlcv_daily_2025 파티션만 스캔"                          | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
     SELECT instrument_id, traded_at, open, high, low, close, volume
       FROM ohlcv_daily
      WHERE instrument_id = '$SAMPLE_TICKER'
        AND traded_at >= '2025-01-01' AND traded_at < '2026-01-01'
      ORDER BY traded_at DESC;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ──────────────────────────────────────────────────────────────────
# 테스트 3: 전체 스캔 (프루닝 불가 — traded_at 조건 없음)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [TEST 3] 전체 스캔 — 단일 종목, 날짜 조건 없음"                  | tee -a "$OUTFILE"
echo "  예상: 모든 파티션 스캔 (pruning 불가)"                          | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
     SELECT instrument_id, traded_at, open, high, low, close, volume
       FROM ohlcv_daily
      WHERE instrument_id = '$SAMPLE_TICKER'
      ORDER BY traded_at DESC;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ──────────────────────────────────────────────────────────────────
# 테스트 4: 집계 쿼리 — 전체 종목 최근 종가 (프루닝 vs 전체)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [TEST 4] 집계 쿼리 — 가장 최근 거래일의 전 종목 종가"            | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
     SELECT instrument_id, close, volume
       FROM ohlcv_daily
      WHERE traded_at = (SELECT MAX(traded_at) FROM ohlcv_daily)
      ORDER BY close DESC
      LIMIT 50;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ──────────────────────────────────────────────────────────────────
# 테스트 5: 연도 범위가 넓은 쿼리 (여러 파티션 스캔)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [TEST 5] 다중 파티션 — 3년 범위 집계"                          | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
$PSQL -c \
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
     SELECT date_trunc('month', traded_at) AS month,
            avg(close) AS avg_close,
            sum(volume) AS total_volume
       FROM ohlcv_daily
      WHERE instrument_id = '$SAMPLE_TICKER'
        AND traded_at >= '2023-01-01' AND traded_at < '2026-01-01'
      GROUP BY month
      ORDER BY month;" 2>&1 | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"

# ──────────────────────────────────────────────────────────────────
# 반복 실행 — 실행시간 통계 (5회 반복)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"
echo "  [BENCH] 반복 실행 통계 (5회)"                                  | tee -a "$OUTFILE"
echo "──────────────────────────────────────────────────────────────" | tee -a "$OUTFILE"

declare -a PRUNED_TIMES
declare -a FULL_TIMES

for i in $(seq 1 5); do
    # 프루닝 쿼리 (30일)
    t=$($PSQL -tAc \
        "EXPLAIN (ANALYZE, FORMAT TEXT)
         SELECT * FROM ohlcv_daily
         WHERE instrument_id = '$SAMPLE_TICKER'
           AND traded_at >= CURRENT_DATE - INTERVAL '30 days';" \
        | grep "Execution Time" | sed 's/.*: \([0-9.]*\).*/\1/')
    PRUNED_TIMES+=("$t")

    # 전체 스캔 쿼리 (날짜 조건 없음)
    t=$($PSQL -tAc \
        "EXPLAIN (ANALYZE, FORMAT TEXT)
         SELECT * FROM ohlcv_daily
         WHERE instrument_id = '$SAMPLE_TICKER';" \
        | grep "Execution Time" | sed 's/.*: \([0-9.]*\).*/\1/')
    FULL_TIMES+=("$t")
done

echo "" | tee -a "$OUTFILE"
printf "  %-12s" "Run #" | tee -a "$OUTFILE"
printf "%-20s" "Pruned (30d) ms" | tee -a "$OUTFILE"
printf "%-20s\n" "Full Scan ms" | tee -a "$OUTFILE"
echo "  ────────── ──────────────────── ────────────────────" | tee -a "$OUTFILE"

for i in $(seq 0 4); do
    printf "  %-12s" "$((i + 1))" | tee -a "$OUTFILE"
    printf "%-20s" "${PRUNED_TIMES[$i]:-N/A}" | tee -a "$OUTFILE"
    printf "%-20s\n" "${FULL_TIMES[$i]:-N/A}" | tee -a "$OUTFILE"
done

echo "" | tee -a "$OUTFILE"
echo "================================================================" | tee -a "$OUTFILE"
echo "  결론: traded_at 조건이 있으면 파티션 프루닝이 작동하여"           | tee -a "$OUTFILE"
echo "  해당 연도 파티션만 스캔합니다. 날짜 조건 없는 쿼리는"              | tee -a "$OUTFILE"
echo "  모든 파티션(2010~2027)을 순회하므로 성능이 저하됩니다."           | tee -a "$OUTFILE"
echo "================================================================" | tee -a "$OUTFILE"
echo ""
echo "  상세 결과: $OUTFILE"
