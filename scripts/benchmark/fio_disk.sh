#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# fio_disk.sh — 디스크 I/O 벤치마크 (PostgreSQL 패턴 시뮬레이션)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RESULT_DIR="${RESULT_DIR:-$(dirname "$0")/results}"
FIO_DIR="${FIO_DIR:-/tmp/fio_benchmark}"
FIO_SIZE="${FIO_SIZE:-256M}"
FIO_RUNTIME="${FIO_RUNTIME:-15}"

mkdir -p "$RESULT_DIR" "$FIO_DIR"
trap 'rm -rf "$FIO_DIR"' EXIT

echo "================================================================"
echo "  fio — 디스크 I/O 벤치마크"
echo "================================================================"
echo ""
echo "  테스트 디렉토리 : $FIO_DIR"
echo "  파일 크기       : $FIO_SIZE"
echo "  실행 시간       : ${FIO_RUNTIME}s per test"
echo ""

# ──────────────────────────────────────────────────────────────────
# 1. Sequential Read — WAL replay, COPY, pg_dump 패턴
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────"
echo "  [1/6] Sequential Read — 128k block"
echo "──────────────────────────────────────────────────────────────"

fio --name=seq_read_128k \
    --directory="$FIO_DIR" \
    --rw=read \
    --bs=128k \
    --size="$FIO_SIZE" \
    --numjobs=4 \
    --time_based \
    --runtime="$FIO_RUNTIME" \
    --group_reporting \
    --output-format=json \
    --output="$RESULT_DIR/fio_seq_read_128k.json" \
    --ioengine=posixaio \
    --direct=1

echo "  완료."
echo ""

# ──────────────────────────────────────────────────────────────────
# 2. Sequential Write — WAL write, COPY 패턴
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────"
echo "  [2/6] Sequential Write — 128k block"
echo "──────────────────────────────────────────────────────────────"

fio --name=seq_write_128k \
    --directory="$FIO_DIR" \
    --rw=write \
    --bs=128k \
    --size="$FIO_SIZE" \
    --numjobs=4 \
    --time_based \
    --runtime="$FIO_RUNTIME" \
    --group_reporting \
    --output-format=json \
    --output="$RESULT_DIR/fio_seq_write_128k.json" \
    --ioengine=posixaio \
    --direct=1

echo "  완료."
echo ""

# ──────────────────────────────────────────────────────────────────
# 3. Random Read 4k — Index scan, B-tree lookup 패턴
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────"
echo "  [3/6] Random Read — 4k block (Index scan 패턴)"
echo "──────────────────────────────────────────────────────────────"

fio --name=rand_read_4k \
    --directory="$FIO_DIR" \
    --rw=randread \
    --bs=4k \
    --size="$FIO_SIZE" \
    --numjobs=4 \
    --time_based \
    --runtime="$FIO_RUNTIME" \
    --group_reporting \
    --output-format=json \
    --output="$RESULT_DIR/fio_rand_read_4k.json" \
    --ioengine=posixaio \
    --direct=1 \
    --iodepth=32

echo "  완료."
echo ""

# ──────────────────────────────────────────────────────────────────
# 4. Random Write 4k — checkpoint, dirty page flush 패턴
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────"
echo "  [4/6] Random Write — 4k block (Checkpoint 패턴)"
echo "──────────────────────────────────────────────────────────────"

fio --name=rand_write_4k \
    --directory="$FIO_DIR" \
    --rw=randwrite \
    --bs=4k \
    --size="$FIO_SIZE" \
    --numjobs=4 \
    --time_based \
    --runtime="$FIO_RUNTIME" \
    --group_reporting \
    --output-format=json \
    --output="$RESULT_DIR/fio_rand_write_4k.json" \
    --ioengine=posixaio \
    --direct=1 \
    --iodepth=32

echo "  완료."
echo ""

# ──────────────────────────────────────────────────────────────────
# 5. Random Read/Write Mix 4k — OLTP 혼합 패턴 (70% read / 30% write)
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────"
echo "  [5/6] Mixed Random R/W — 4k block (OLTP 패턴, 70/30)"
echo "──────────────────────────────────────────────────────────────"

fio --name=mixed_rw_4k \
    --directory="$FIO_DIR" \
    --rw=randrw \
    --rwmixread=70 \
    --bs=4k \
    --size="$FIO_SIZE" \
    --numjobs=4 \
    --time_based \
    --runtime="$FIO_RUNTIME" \
    --group_reporting \
    --output-format=json \
    --output="$RESULT_DIR/fio_mixed_rw_4k.json" \
    --ioengine=posixaio \
    --direct=1 \
    --iodepth=32

echo "  완료."
echo ""

# ──────────────────────────────────────────────────────────────────
# 6. Sequential Write 128k — Bulk INSERT / COPY 패턴
# ──────────────────────────────────────────────────────────────────
echo "──────────────────────────────────────────────────────────────"
echo "  [6/6] Sequential Write — 4k block (WAL 패턴)"
echo "──────────────────────────────────────────────────────────────"

fio --name=seq_write_4k \
    --directory="$FIO_DIR" \
    --rw=write \
    --bs=4k \
    --size="$FIO_SIZE" \
    --numjobs=1 \
    --time_based \
    --runtime="$FIO_RUNTIME" \
    --group_reporting \
    --output-format=json \
    --output="$RESULT_DIR/fio_seq_write_4k.json" \
    --ioengine=posixaio \
    --direct=1 \
    --fdatasync=1

echo "  완료."
echo ""

# ── 결과 요약 ────────────────────────────────────────────────────
echo "================================================================"
echo "  fio 결과 요약"
echo "================================================================"
echo ""

printf "  %-30s %12s %12s %12s\n" "Test" "BW (MB/s)" "IOPS" "Lat p99 (us)"
echo "  ────────────────────────────── ──────────── ──────────── ────────────"

for jsonfile in "$RESULT_DIR"/fio_*.json; do
    label=$(basename "$jsonfile" .json | sed 's/^fio_//')

    # fio JSON: .jobs[0].read or .jobs[0].write
    bw_read=$(python3 -c "
import json, sys
with open('$jsonfile') as f:
    d = json.load(f)
j = d['jobs'][0]
r = j.get('read', {})
w = j.get('write', {})
bw = (r.get('bw', 0) + w.get('bw', 0)) / 1024  # KB/s -> MB/s
print(f'{bw:.1f}')
" 2>/dev/null || echo "N/A")

    iops=$(python3 -c "
import json
with open('$jsonfile') as f:
    d = json.load(f)
j = d['jobs'][0]
r = j.get('read', {})
w = j.get('write', {})
iops = r.get('iops', 0) + w.get('iops', 0)
print(f'{iops:.0f}')
" 2>/dev/null || echo "N/A")

    lat_p99=$(python3 -c "
import json
with open('$jsonfile') as f:
    d = json.load(f)
j = d['jobs'][0]
r = j.get('read', {})
w = j.get('write', {})
clat_r = r.get('clat_ns', r.get('clat', {}))
clat_w = w.get('clat_ns', w.get('clat', {}))
p99_r = clat_r.get('percentile', {}).get('99.000000', 0)
p99_w = clat_w.get('percentile', {}).get('99.000000', 0)
p99 = max(p99_r, p99_w) / 1000  # ns -> us
print(f'{p99:.0f}')
" 2>/dev/null || echo "N/A")

    printf "  %-30s %12s %12s %12s\n" "$label" "$bw_read" "$iops" "$lat_p99"
done

echo ""
echo "  JSON 상세 결과: $RESULT_DIR/fio_*.json"
echo "================================================================"
