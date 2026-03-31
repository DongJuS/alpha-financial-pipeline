#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# pgbench_ohlcv.sh — PostgreSQL TPS 벤치마크 (ohlcv_daily 대상)
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

TMPDIR_BENCH=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BENCH"' EXIT

# ── 현재 DB 상태 확인 ─────────────────────────────────────────────
echo "================================================================"
echo "  pgbench — ohlcv_daily TPS Benchmark"
echo "================================================================"
echo ""

ROW_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT to_char(count(*), 'FM999,999,999') FROM ohlcv_daily;")
TICKER_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT to_char(count(DISTINCT instrument_id), 'FM999,999') FROM ohlcv_daily;")
echo "  DB rows  : $ROW_COUNT"
echo "  Tickers  : $TICKER_COUNT"
echo ""

# ── 테스트용 종목 목록 수집 ────────────────────────────────────────
TICKERS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT instrument_id FROM (
        SELECT DISTINCT instrument_id FROM ohlcv_daily ORDER BY instrument_id LIMIT 100
     ) t ORDER BY random() LIMIT 20;")

# ──────────────────────────────────────────────────────────────────
# 1. SELECT 벤치마크 — 단일 종목 30일 조회 (파티션 pruning 활용)
# ──────────────────────────────────────────────────────────────────
cat > "$TMPDIR_BENCH/select_ohlcv.sql" << 'EOSQL'
\set ticker random(1, 20)
SELECT instrument_id, traded_at, open, high, low, close, volume
  FROM ohlcv_daily
 WHERE instrument_id = (
       SELECT instrument_id FROM (
           SELECT DISTINCT instrument_id FROM ohlcv_daily
           ORDER BY instrument_id LIMIT 20
       ) t OFFSET :ticker - 1 LIMIT 1
   )
   AND traded_at >= CURRENT_DATE - INTERVAL '30 days'
 ORDER BY traded_at DESC;
EOSQL

echo "──────────────────────────────────────────────────────────────"
echo "  [1/3] SELECT — 단일 종목 30일 조회"
echo "──────────────────────────────────────────────────────────────"

pgbench -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -f "$TMPDIR_BENCH/select_ohlcv.sql" \
    -c 4 -j 2 -T 15 -P 5 --no-vacuum \
    2>&1 | tee "$RESULT_DIR/pgbench_select.log"

echo ""

# ──────────────────────────────────────────────────────────────────
# 2. SELECT 벤치마크 — 전체 종목 최신 종가 집계
# ──────────────────────────────────────────────────────────────────
cat > "$TMPDIR_BENCH/select_agg.sql" << 'EOSQL'
SELECT instrument_id, close, traded_at
  FROM ohlcv_daily
 WHERE traded_at = (SELECT MAX(traded_at) FROM ohlcv_daily)
 ORDER BY close DESC
 LIMIT 50;
EOSQL

echo "──────────────────────────────────────────────────────────────"
echo "  [2/3] SELECT — 전체 종목 최신 종가 집계"
echo "──────────────────────────────────────────────────────────────"

pgbench -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -f "$TMPDIR_BENCH/select_agg.sql" \
    -c 4 -j 2 -T 15 -P 5 --no-vacuum \
    2>&1 | tee "$RESULT_DIR/pgbench_agg.log"

echo ""

# ──────────────────────────────────────────────────────────────────
# 3. INSERT 벤치마크 — 트랜잭션 내 INSERT + ROLLBACK (데이터 오염 방지)
# ──────────────────────────────────────────────────────────────────
cat > "$TMPDIR_BENCH/insert_ohlcv.sql" << 'EOSQL'
BEGIN;
INSERT INTO ohlcv_daily (instrument_id, traded_at, open, high, low, close, volume, change_pct)
VALUES (
    'BENCH_TEST.KS',
    CURRENT_DATE - (random() * 365)::int * INTERVAL '1 day',
    50000 + random() * 10000,
    55000 + random() * 10000,
    45000 + random() * 10000,
    52000 + random() * 10000,
    (random() * 1000000)::bigint,
    (random() * 10 - 5)::numeric(8,4)
) ON CONFLICT (instrument_id, traded_at) DO NOTHING;
ROLLBACK;
EOSQL

echo "──────────────────────────────────────────────────────────────"
echo "  [3/3] INSERT + ROLLBACK — 쓰기 TPS 측정"
echo "──────────────────────────────────────────────────────────────"

pgbench -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -f "$TMPDIR_BENCH/insert_ohlcv.sql" \
    -c 4 -j 2 -T 15 -P 5 --no-vacuum \
    2>&1 | tee "$RESULT_DIR/pgbench_insert.log"

echo ""

# ── 결과 요약 ────────────────────────────────────────────────────
echo "================================================================"
echo "  pgbench 결과 요약"
echo "================================================================"
echo ""

for logfile in "$RESULT_DIR"/pgbench_*.log; do
    label=$(basename "$logfile" .log)
    tps=$(grep "tps = " "$logfile" | tail -1 | sed 's/.*tps = \([0-9.]*\).*/\1/')
    latency=$(grep "latency average" "$logfile" | tail -1 | sed 's/.*= \([0-9.]*\).*/\1/')
    printf "  %-25s TPS: %10s   Avg Latency: %s ms\n" "$label" "${tps:-N/A}" "${latency:-N/A}"
done

echo ""
echo "  상세 로그: $RESULT_DIR/pgbench_*.log"
echo "================================================================"
