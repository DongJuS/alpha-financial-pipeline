# Benchmark Scripts

Alpha Trading System 인프라 성능을 측정하는 벤치마크 스크립트 모음입니다.

## 사전 요구사항

```bash
# macOS 기준
brew install libpq fio k6 python@3.11 kubectl
pip install asyncpg

# libpq 도구(psql, pgbench)가 PATH에 없으면:
echo 'export PATH="/opt/homebrew/opt/libpq/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### K8s 접속 환경
- K3s (Colima) 또는 원격 클러스터에 `kubectl` 접근이 가능해야 합니다.
- 네임스페이스: `alpha-trading`

## 빠른 시작

```bash
# 전체 벤치마크 실행 (port-forward 자동 설정)
./scripts/benchmark/run_all.sh

# DB 벤치마크만 실행
./scripts/benchmark/run_all.sh --db-only

# fio 또는 k6 제외
./scripts/benchmark/run_all.sh --skip-fio
./scripts/benchmark/run_all.sh --skip-k6
```

## 개별 스크립트

### 1. pgbench_ohlcv.sh — PostgreSQL TPS 측정

```bash
./scripts/benchmark/pgbench_ohlcv.sh
```

ohlcv_daily 테이블 대상으로 SELECT/INSERT TPS를 측정합니다.

| 테스트 | 설명 |
|--------|------|
| SELECT 30일 | 단일 종목 최근 30일 조회 (파티션 프루닝 활용) |
| SELECT 집계 | 전체 종목 최신 종가 TOP 50 |
| INSERT + ROLLBACK | 쓰기 TPS (데이터 오염 없음) |

**핵심 지표:** TPS (Transactions Per Second), 평균 레이턴시(ms)

### 2. sysbench_partition.sh — 파티셔닝 효과 측정

```bash
./scripts/benchmark/sysbench_partition.sh
```

ohlcv_daily의 연도별 파티셔닝(2010~2027)이 쿼리 성능에 미치는 효과를
EXPLAIN ANALYZE로 비교합니다.

| 테스트 | 파티션 프루닝 | 예상 결과 |
|--------|:---:|------|
| 최근 30일 | O | 1~2개 파티션만 스캔 |
| 2025년 데이터 | O | ohlcv_daily_2025만 스캔 |
| 날짜 조건 없음 | X | 모든 파티션(18개) 순회 |
| 3년 범위 집계 | 부분 | 3개 파티션 스캔 |

**해석 포인트:**
- `Seq Scan on ohlcv_daily_2026` → 해당 파티션만 스캔 (프루닝 작동)
- `Append` 노드 하위에 파티션이 적을수록 프루닝 효과 큼
- Buffers shared hit이 높으면 캐시 적중

### 3. k6_api_load.js — FastAPI 부하 테스트

```bash
k6 run scripts/benchmark/k6_api_load.js

# JSON 결과 저장
k6 run --out json=scripts/benchmark/results/k6_result.json scripts/benchmark/k6_api_load.js

# 환경변수 오버라이드
API_BASE_URL=http://localhost:18000 k6 run scripts/benchmark/k6_api_load.js
```

| 시나리오 | 동시 사용자 | 시간 |
|----------|:---------:|:----:|
| Warmup | 10 VU | 30s |
| Medium | 50 VU | 30s |
| Heavy | 100 VU | 30s |

**테스트 엔드포인트:**
- `GET /health` — 헬스체크 (인증 불필요)
- `GET /api/v1/portfolio/positions` — 포트폴리오 포지션
- `GET /api/v1/market/tickers` — 종목 목록
- `GET /api/v1/marketplace/stocks` — 마켓플레이스
- `GET /api/v1/system/overview` — 시스템 상태

**핵심 지표:** p50/p95/p99 레이턴시, RPS, 에러율

### 4. fio_disk.sh — 디스크 I/O 측정

```bash
./scripts/benchmark/fio_disk.sh

# 커스텀 설정
FIO_SIZE=1G FIO_RUNTIME=30 ./scripts/benchmark/fio_disk.sh
```

| 테스트 | 블록 사이즈 | PostgreSQL 대응 패턴 |
|--------|:---------:|------|
| Sequential Read | 128k | WAL replay, COPY, pg_dump |
| Sequential Write | 128k | WAL write, COPY |
| Random Read | 4k | Index scan, B-tree lookup |
| Random Write | 4k | Checkpoint, dirty page flush |
| Mixed R/W | 4k | OLTP 혼합 (70/30) |
| Sequential Write | 4k | WAL 쓰기 패턴 |

**핵심 지표:** Bandwidth(MB/s), IOPS, p99 레이턴시(us)

**해석 가이드:**
- Random Read 4k IOPS > 50,000 → SSD 정상
- Sequential Write 128k BW > 500 MB/s → 대량 INSERT 성능 양호
- Mixed R/W p99 latency < 1ms → OLTP 워크로드 적합

### 5. python_insert.py — asyncpg INSERT 처리량

```bash
python3 scripts/benchmark/python_insert.py

# 행 수 지정
python3 scripts/benchmark/python_insert.py --rows 10000 50000 100000
```

executemany와 COPY 방식을 비교합니다. 모든 INSERT는 트랜잭션 ROLLBACK 처리됩니다.

**핵심 지표:** rows/sec

**해석 가이드:**
- COPY가 executemany보다 3~10x 빠른 것이 일반적
- 10만 행 기준 COPY > 100,000 rows/sec 이면 양호

### 6. python_query.py — 쿼리 성능 벤치마크

```bash
python3 scripts/benchmark/python_query.py
```

| 쿼리 | 설명 |
|------|------|
| A. 단일 종목 30일 | 파티션 프루닝 확인 |
| B. 전체 최신 종가 | 서브쿼리 + 정렬 성능 |
| C. N+1 vs 배치 | ANY 연산자 효과 |
| D. 프루닝 vs 전체 | 파티셔닝 속도 차이 |

**핵심 지표:** 평균 실행시간(ms), 속도 개선 배수

## 결과 파일

`scripts/benchmark/results/` 디렉토리에 저장됩니다:

```
results/
  pgbench_select.log       # pgbench SELECT 결과
  pgbench_agg.log          # pgbench 집계 결과
  pgbench_insert.log       # pgbench INSERT 결과
  partition_analysis.txt   # 파티셔닝 EXPLAIN ANALYZE
  fio_*.json               # fio JSON 상세 결과
  k6_result_*.json         # k6 JSON 상세 결과
  run_all_*.log            # 전체 실행 로그
```

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DB_HOST` | localhost | PostgreSQL 호스트 |
| `DB_PORT` | 5432 | PostgreSQL 포트 |
| `DB_NAME` | alpha_db | 데이터베이스명 |
| `DB_USER` | alpha_user | DB 사용자 |
| `DB_PASS` | alpha_pass | DB 비밀번호 |
| `API_BASE_URL` | http://localhost:18000 | API 서버 주소 |
| `API_EMAIL` | admin@alpha-trading.com | 로그인 이메일 |
| `API_PASSWORD` | admin | 로그인 비밀번호 |
| `K8S_NAMESPACE` | alpha-trading | K8s 네임스페이스 |
| `FIO_SIZE` | 256M | fio 테스트 파일 크기 |
| `FIO_RUNTIME` | 15 | fio 테스트 시간(초) |

## 트러블슈팅

### pgbench "relation does not exist"
port-forward가 올바른 DB를 가리키는지 확인:
```bash
kubectl port-forward svc/alpha-pg-postgresql 5432:5432 -n alpha-trading
psql -h localhost -U alpha_user -d alpha_db -c "SELECT count(*) FROM ohlcv_daily"
```

### k6 로그인 실패
API 서버가 실행 중인지, admin 계정이 존재하는지 확인:
```bash
kubectl port-forward svc/api 18000:8000 -n alpha-trading
curl -X POST http://localhost:18000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@alpha-trading.com","password":"admin"}'
```

### fio permission denied
`/tmp/fio_benchmark` 디렉토리 권한 확인. 다른 경로 사용:
```bash
FIO_DIR=~/fio_test ./scripts/benchmark/fio_disk.sh
```
