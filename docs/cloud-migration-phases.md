# 클라우드 마이그레이션 — Phase 0~4 실행 가이드

> 로컬 K3s → Oracle Always Free + Cloudflare R2 이전 절차.
> 원본 논의: `.agent/discussions/20260411-cloud-migration-execution-plan.md` (gitignore 대상이라 영구 보존을 위해 본 문서로 추출).

---

## 결정 사항 (요약)

- **배포 방식**: Docker Compose (`docker-compose.prod.yml`) — K8s 매니페스트는 보존하되 단일 노드 운영에는 Compose가 단순/안전/관리 수월
- **이전 방식**: Cold migration (모의투자 단계라 다운타임 허용)
- **S3 스토리지**: Cloudflare R2 우선, 호환성 문제 시 Hetzner MinIO fallback

---

## Phase 0 — 사전 준비 (✅ PR #188로 완료)

| 항목 | 변경 대상 | 완료 기준 |
|------|----------|----------|
| R2 호환성 (`ensure_bucket()` graceful) | `src/utils/s3_client.py` | 403/409 응답 시 경고 로그만, 서비스 크래시 방지 |
| MinIO profile 비활성화 | `docker-compose.prod.yml` | MinIO 블록 profile=local-only, R2 endpoint로 분리 |
| tick-collector prod override | `docker-compose.prod.yml` | resource limits + restart=always + 외부 환경변수 주입 |
| RL 학습 비활성화 | `docker-compose.prod.yml` | `ORCH_ENABLE_RL_AUTO_RETRAIN=false` (학습은 로컬, 추론만 서버) |
| `.env.example` R2 섹션 | `.env.example` | S3_ENDPOINT_URL/ACCESS_KEY/SECRET_KEY/BUCKET 예시 |
| K3s 원복 매뉴얼 | `k8s/README.md` | Compose→K3s 8단계 가이드 |

---

## Phase 1 — 서버 세팅

| 항목 | 명령/완료 기준 |
|------|----------------|
| Oracle Always Free 인스턴스 생성 | `scripts/oci_instance_retry.sh` (5분 크론), 성공 시 `/tmp/oci_instance_created.txt`에 OCID |
| SSH 접속 확인 | `ssh -i ~/.ssh/id_ed25519 ubuntu@<공개IP>` |
| Timezone | `sudo timedatectl set-timezone Asia/Seoul` |
| Docker + Compose | Ubuntu 24.04 ARM 기준 `apt-get install docker.io docker-compose-v2` |
| Docker group | `sudo usermod -aG docker ubuntu` |
| 방화벽 | OCI Security List에 22(SSH)만 오픈, 80/443은 후속 |
| swap (선택) | Always Free 24GB RAM이라 swap 불필요 (Hetzner CX22 fallback일 때만 2GB) |

---

## Phase 2 — 데이터 이전

### 2.1 R2 버킷 + Object 데이터

```bash
# 1) Cloudflare 콘솔에서 R2 버킷 생성 (alpha-datalake) — API 불가
# 2) MinIO → R2 동기화 (rclone)
rclone sync minio:alpha-lake r2:alpha-datalake --checksum --progress
rclone check minio:alpha-lake r2:alpha-datalake     # 무결성 검증
```

### 2.2 PostgreSQL 이전

로컬 → 서버:

```bash
# 로컬에서 dump
bash scripts/db/backup.sh --output /tmp/alpha_db.dump

# 서버로 전송
scp /tmp/alpha_db.dump ubuntu@<서버IP>:/tmp/alpha_db.dump

# 서버에서 복원
ssh ubuntu@<서버IP>
cd ~/alpha-financial-pipeline
docker compose -f docker-compose.prod.yml up -d postgres
bash scripts/db/restore.sh --input /tmp/alpha_db.dump
```

### 2.3 DB 마이그레이션 4단계 (필수)

`pg_restore` 직후 반드시 순차 실행. 누락 시 instruments/trading_universe 비어 있어 서비스 즉시 실패.

```bash
docker compose -f docker-compose.prod.yml run --rm api python scripts/migrate_to_v2_instruments.py
docker compose -f docker-compose.prod.yml run --rm api python scripts/migrate_ohlcv_minute.py
docker compose -f docker-compose.prod.yml run --rm api python scripts/seed_all_instruments.py
docker compose -f docker-compose.prod.yml run --rm api python scripts/seed_trading_universe.py
```

검증: `instruments` 2,773건 (KOSPI 950 + KOSDAQ 1,823), `trading_universe` 3건 (paper 스코프).

---

## Phase 3 — 기동 및 검증

```bash
# .env 배포 (사용자가 scp로 전송, 서버에서 chmod 600)
ssh ubuntu@<서버IP> 'chmod 600 ~/alpha-financial-pipeline/.env'

# 서비스 기동
cd ~/alpha-financial-pipeline
docker compose -f docker-compose.prod.yml up -d

# 검증
docker compose -f docker-compose.prod.yml exec api python scripts/health_check.py
docker compose -f docker-compose.prod.yml exec api python scripts/smoke_test.py --skip-telegram
docker compose -f docker-compose.prod.yml exec api python -c "from src.utils.s3_client import get_s3_client; c=get_s3_client(); print('R2 OK', c.list_objects_v2(Bucket='alpha-datalake', MaxKeys=1).get('KeyCount', 0))"
```

데이터 검증: `market_data` 행 수 일치, R2 파일 수 일치.

---

## Phase 4 — 안정화

| 항목 | 완료 기준 |
|------|----------|
| 1사이클 완주 | 수집 → 분석 → 시그널 → 알림 정상 |
| 48시간 로그 모니터링 | 에러 0건 |
| 로컬 환경 2주 유지 | 롤백 불필요 확인 후 로컬 K3s 해제 |

---

## 메모리 예산 (참고)

Oracle Always Free 24GB RAM 기준 — 여유 충분. RL 학습도 서버에서 가능.
Hetzner CX22 fallback 시 4GB RAM이라 RL 학습은 로컬에서만 수행.

| 구성요소 | 예상 사용량 |
|----------|-----------|
| OS + Docker | ~300MB |
| PostgreSQL | ~512MB |
| Redis | ~128MB |
| FastAPI (api) | ~256MB |
| Worker (orchestrator) | ~700MB (RL 추론) |
| tick-collector | ~150MB |
| UI | ~128MB |
| **합계** | ~2.2GB |

---

## 롤백 전략

| 실패 시나리오 | 대응 |
|-------------|------|
| 서비스 기동 실패 | `docker compose logs`로 원인 파악 후 재기동 |
| R2 호환성 문제 | Hetzner CX22 + MinIO 설치로 fallback (200GB Oracle 디스크 활용) |
| 데이터 불일치 | `scripts/db/backup.sh`로 보관한 dump 파일로 재복원 |
| 전체 롤백 | 로컬 K3s 환경 2주간 유지, `kubectl apply -k k8s/overlays/dev`로 즉시 복귀 |

---

## 참조

- `scripts/db/backup.sh` / `scripts/db/restore.sh` — pg_dump/pg_restore 헬퍼
- `docker-compose.prod.yml` — 프로덕션 Compose 정의
- `src/utils/s3_client.py` — R2 graceful 처리
- `docs/oracle-cloud-setup.md` — Oracle 인스턴스 생성 가이드
- `finance/cloudflare-r2.md` — R2 비용 + 구독 정보
- `k8s/README.md` — Compose↔K3s 원복 매뉴얼
