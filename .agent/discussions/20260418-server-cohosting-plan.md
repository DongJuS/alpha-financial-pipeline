# 서버 동거 계획: alpha-financial-pipeline + OpenClaw 단일 서버 운영

status: open
created_at: 2026-04-18
topic_slug: server-cohosting-plan
related_files:
- docker-compose.prod.yml
- CLAUDE.md
- docs/oracle-cloud-setup.md
- progress.md
- scripts/oci/setup_monitoring.sh
- scripts/oci/disk_monitor.sh (신규)

## 1. 핵심 질문

Oracle Cloud ARM A1 Flex 인스턴스 1대(4 OCPU, 24 GB RAM)에서 alpha-financial-pipeline(트레이딩)과 OpenClaw(AI 에이전트 오케스트레이션) 두 프로젝트를 Docker Compose 기반으로 안전하게 동거 운영하려면 리소스 분배, 격리, 모니터링을 어떻게 설계해야 하는가?

## 2. 배경

### 2.1 프로젝트 개요

alpha-financial-pipeline은 한국 KOSPI/KOSDAQ 시장을 대상으로 한 멀티 에이전트 자동 투자 시스템이다. Python 3.11+, FastAPI, PostgreSQL, Redis, React 18 + TypeScript + Vite, KIS Developers API, FinanceDataReader, Claude/OpenAI/Gemini 등을 사용한다. 전략 A/B + RL Trading을 조합한 blend 모드로 운영하며, Docker Compose로 6개 서비스(postgres, redis, api, worker, tick-collector, ui)를 배포한다.

### 2.2 현재 서버 상태

- **인스턴스**: Oracle Cloud Always Free ARM A1 Flex, ap-chuncheon-1 리전
- **스펙**: 4 OCPU, 24 GB RAM, 200 GB boot volume
- **실사용량**: CPU 약 2%, RAM 약 1.3 GB (전체의 약 6%)
- **IP**: 리사이징 과정에서 ephemeral IP(152.67.223.37)를 reserved IP(134.185.110.214)로 전환 완료
- **서비스 구성**: Docker Compose로 postgres, redis, api, worker, tick-collector, ui 6개 서비스 운영
- **현재 리소스 제한(docker-compose.prod.yml)**:
  - postgres: 512M / 0.5 CPU
  - redis: 256M / 0.25 CPU
  - api: 1G / 1.0 CPU
  - worker: 1G / 1.0 CPU
  - tick-collector: 256M / 0.25 CPU
  - ui: 256M / 0.25 CPU
  - 합계: 약 3.25 GB RAM

### 2.3 새 서버가 필요한 이유

OpenClaw는 AI agent/가상 비서 오케스트레이션 프로젝트로, API 호출 기반 에이전트 오케스트레이션을 수행한다. 로컬 LLM 추론은 아직 미정이며, 별도 서버에서 운영할 필요가 있다.

### 2.4 별도 인스턴스 확보 시도와 실패

1. **Oracle Always Free ARM A1 할당 제한**: 총 4 OCPU / 24 GB가 상한이며, 현재 인스턴스가 전량(4 OCPU / 24 GB)을 사용 중이다. 새 인스턴스를 추가 생성할 여유가 없다.

2. **리사이징 시도 실패**: 인스턴스를 STOP한 뒤 shape config를 3 OCPU / 21 GB로 축소 시도했으나, "Out of host capacity" 에러가 발생했다. Chuncheon 리전의 ARM 용량이 부족한 것이 원인이다. 원래 4/24 스펙으로 복구에는 성공했다.

3. **완전 삭제 후 재생성 방식**: 기존 인스턴스를 terminate하고, 크론 스크립트(scripts/oci_instance_retry.sh 패턴)로 3 OCPU/21 GB + 1 OCPU/3 GB 두 개를 재생성하는 방법이 있으나, 서버 공백 기간이 수 시간에서 수 일까지 발생할 수 있고, 데이터 손실 리스크가 크다.

4. **AMD Micro(VM.Standard.E2.1.Micro)**: 2개까지 무료로 사용 가능하지만, 1 OCPU / 1 GB RAM으로 서버 워크로드를 감당하기에 부족하다.

5. **외부 호스팅(Hetzner)**: CAX11이 약 4,500원/월, CX32가 약 9,000원/월로 예산(월 5,000~10,000원) 내에 들어오지만, 관리 포인트가 분산되고 운영 복잡도가 증가한다.

### 2.5 최종 결정: 기존 서버 동거

현재 서버의 CPU 2% / RAM 6% 사용률을 감안하면 리소스가 충분히 남아 있다. 두 프로젝트를 Docker Compose로 분리하여 같은 서버에서 운영하는 것이 가장 현실적이다. 사용자는 처음에 격리(별도 서버)를 선호했으나, 리사이징 실패와 비용/복잡도를 종합적으로 고려하여 동거를 수용했다.

### 2.6 IP 변경

리사이징 과정에서 기존 ephemeral IP(152.67.223.37)를 reserved IP(134.185.110.214)로 전환했다. 이유: 인스턴스를 중지(STOP)하면 ephemeral IP가 해제되어 다시 기동 시 IP가 바뀐다. reserved IP는 인스턴스의 stop/start 사이클에서도 유지되므로 운영 안정성이 높아진다.

## 3. 제약 조건

1. **Oracle Always Free Tier 범위 내 운영**: 추가 비용 없이 기존 4 OCPU / 24 GB / 200 GB 디스크만 사용.
2. **월 운영비 5,000~10,000원 이내**: 인프라 + API 비용 합산 기준.
3. **1인 개발자 운영**: 모니터링, 장애 대응, 배포 모두 1인이 처리할 수 있는 수준의 복잡도.
4. **트레이딩 서비스 무중단**: alpha-financial-pipeline은 장중(09:00~15:30 KST) 실시간 데이터 수집과 주기적 오케스트레이션 사이클을 수행하므로, OpenClaw 배포/장애가 트레이딩에 영향을 주면 안 됨.
5. **Docker Compose 기반 배포 유지**: K3s 경로는 로컬 개발/롤백용으로만 유지하며, 프로덕션은 Docker Compose 사용.
6. **데이터 격리**: 두 프로젝트가 서로의 DB/Redis에 접근하지 않아야 함.

## 4. 선택지 비교

| 선택지 | 장점 | 단점 | 비용/복잡도 |
|--------|------|------|------------|
| A. 기존 서버 동거 (Docker Compose 분리) | 추가 비용 0원, 단일 서버 관리, 즉시 시작 가능 | Docker 데몬 단일 장애점, 디스크 공유 | 낮음 |
| B. 인스턴스 terminate → 2개 재생성 | 완전한 인스턴스 격리 | 서버 공백 수 시간~수 일, 데이터 손실 리스크, 용량 부족으로 실패 가능 | 높음 (리스크) |
| C. Hetzner CX32 추가 | 완전한 물리적 격리, 독립 관리 | 월 9,000원 추가 비용, 관리 포인트 분산 | 중간 (비용) |
| D. AMD Micro 2개 활용 | 무료, 별도 인스턴스 | 1 OCPU/1 GB로 성능 부족, ARM 빌드 호환 문제 | 낮음 (비용) / 높음 (제약) |

## 5. 결정 사항

### 5.1 결정

**선택지 A: 기존 서버 동거(Docker Compose 분리)**를 채택한다.

3축 평가 (프로젝트 실제 규모 기준):

- **확장성**: 나중에 OpenClaw의 리소스가 커지면 별도 서버로 이전이 용이하다. Docker Compose 프로젝트 단위로 관리되므로, compose 파일과 볼륨 데이터만 옮기면 된다. 현 단계에서는 API 호출 기반 오케스트레이션이라 리소스 소모가 크지 않을 것으로 예상된다.
- **안전**: Docker cgroup 리소스 제한(mem_limit, cpus)으로 서비스별 자원 사용 상한을 강제한다. 트레이딩 서비스는 이미 docker-compose.prod.yml에서 리소스 제한이 설정되어 있다. 별도 Docker bridge network로 네트워크 격리가 기본 적용된다.
- **관리 수월함**: 1인 개발자가 단일 서버에서 두 프로젝트를 독립적으로 운영할 수 있다. 모니터링과 알람은 기존 OCI 인프라(setup_monitoring.sh)와 Telegram 알림을 재활용한다.

### 5.2 트레이드오프

이 결정으로 감수하는 리스크:

1. **Docker 데몬 단일 장애점**: Docker 데몬 자체가 크래시하면 양쪽 프로젝트 모두 영향을 받는다. 다만 Docker 데몬 크래시는 극히 드문 이벤트이며, systemd restart로 자동 복구된다.

2. **OS 재부팅 시 동시 다운**: 서버 재부팅 시 두 프로젝트가 동시에 내려간다. `restart: always` 설정으로 자동 복구되며, 양쪽 모두 상태를 DB에 영속하므로 데이터 손실은 없다.

3. **디스크 200 GB 공유**: 두 프로젝트가 같은 200 GB 디스크를 사용한다. PostgreSQL WAL, Docker 이미지 레이어, 로그 등이 누적되면 디스크 부족이 발생할 수 있다. 이를 모니터링 2단계(OCI 알람 + Docker 레벨 셸 스크립트)로 대응한다.

## 6. 실행 계획

| 순서 | 항목 | 변경 대상 파일 | 완료 기준 |
|------|------|---------------|----------|
| 1 | IP 주소 업데이트 (152.67.223.37 → 134.185.110.214) | `CLAUDE.md`, `docs/oracle-cloud-setup.md`, `progress.md` | grep으로 구 IP(152.67.223.37) 검색 결과 0건 |
| 2 | 트레이딩 서비스 리소스 제한 증가 | `docker-compose.prod.yml` | postgres 1536M, redis 512M, api 2G, worker 3G, tick-collector 512M, ui 256M 반영. 파일 상단 주석의 "Hetzner"를 "Oracle"로 변경 |
| 3 | 디스크 모니터링 스크립트 작성 | `scripts/oci/disk_monitor.sh` (신규 생성) | `bash -n` 문법 검사 통과, 수동 실행 시 디스크 사용량 리포트 출력 |
| 4 | 서버 배포 | (서버 ssh 작업) | `docker compose ps` 6개 서비스 healthy, 새 메모리 제한 적용 확인 (`docker stats --no-stream`) |
| 5 | OCI 모니터링 부트스트랩 실행 | `scripts/oci/setup_monitoring.sh` (서버에서 실행) | CPU/Memory/Disk 알람 3종 + Budget alert 생성 확인 |
| 6 | 디스크 모니터링 크론 등록 | (서버 crontab) | `crontab -l`에 disk_monitor.sh 항목 확인, 매일 09:00 KST 실행 |
| 7 | OpenClaw 디렉토리 준비 | (서버 ~/openclaw/) | 디렉토리 존재 확인, git clone 완료 |

### 리소스 분배 상세

#### 트레이딩 서비스 (docker-compose.prod.yml 변경)

| 서비스 | 현재 | 변경 후 | 변경 이유 |
|--------|------|---------|----------|
| postgres | 512M | 1536M | 20종목 틱 데이터 + ohlcv_minute 파티션 테이블 성능 향상. shared_buffers 확대 가능 |
| redis | 256M | 512M | 20종목 캐시/pubsub 여유 확보. 장중 틱 데이터 버퍼링 안정화 |
| api | 1G | 2G | LLM CLI 호출(Claude/Gemini) 시 메모리 스파이크 대응. subprocess 포크 오버헤드 포함 |
| worker | 1G | 3G | orchestrator + RL 학습 가능하도록 확보. torch + SB3 + Optuna가 약 3GB 소모. 서버 RL 학습 활성화 가능 |
| tick-collector | 256M | 512M | 20종목 WebSocket 동시 연결 시 버퍼링 메모리 여유 확보 |
| ui | 256M | 256M | 변경 없음. 정적 파일 서빙으로 현재도 충분 |
| **합계** | **~3.25 GB** | **~7.75 GB** | +4.5 GB 증가 |

#### OpenClaw 가이드라인

| 항목 | 값 | 비고 |
|------|------|------|
| mem_limit | 8G | API 호출 기반 오케스트레이션 기준. 로컬 LLM 추론 도입 시 재조정 필요 |
| cpus | 2.0 | 4 OCPU 중 절반 할당. 트레이딩은 나머지 2 OCPU 내에서 충분 |

#### 전체 서버 리소스 현황

| 구분 | RAM |
|------|-----|
| 트레이딩 서비스 합계 | ~7.75 GB |
| OpenClaw 가이드라인 | ~8.0 GB |
| **컨테이너 합계** | **~15.75 GB** |
| OS + 페이지 캐시 여유분 | ~8.25 GB |
| **서버 전체** | **24.0 GB** |

### 동거 격리 방식

1. **디렉토리 분리**: `~/alpha-financial-pipeline/`과 `~/openclaw/`는 별도 git repo로 관리한다.
2. **Docker 네트워크 격리**: 각 Docker Compose 프로젝트는 별도 bridge network를 자동 생성한다(`alpha-financial-pipeline_default`, `openclaw_default`). 서로 다른 네트워크에 속한 컨테이너는 기본적으로 통신할 수 없다.
3. **포트 분리**: 트레이딩 서비스는 8000(API), 5173(UI) 포트를 사용한다. OpenClaw는 3000~3999 범위를 사용하도록 규약한다.
4. **리소스 cgroup 제한**: 각 서비스별로 `mem_limit`과 `cpus`를 설정하여 한 서비스가 다른 서비스의 리소스를 침범하지 못하도록 한다.

### 디스크 모니터링 전략 (2단계)

**1단계: OCI 알람** (setup_monitoring.sh)
- FilesystemUtilization > 80% (WARNING) 시 이메일 알림 발송
- 이미 스크립트가 작성되어 있으나 서버에서 아직 실행하지 않은 상태
- CPU > 90%, Memory > 90% 알람도 동시에 생성

**2단계: Docker 레벨 셸 스크립트 크론** (disk_monitor.sh 신규 작성)
- Docker 볼륨별 사용량을 점검하여 50 GB 초과 시 기존 Telegram 알림 인프라로 경고 발송
- 매일 09:00 KST 실행 (crontab 등록)
- Telegram curl 패턴은 `scripts/oci_instance_retry.sh`의 성공 알림 코드를 참고

## 7. 참조

### 7.1 참고 파일

- `docker-compose.prod.yml` — 현재 서비스별 리소스 제한 확인 (postgres 512M, redis 256M, api 1G, worker 1G, tick-collector 256M, ui 256M). 프로덕션 오버라이드 구조와 MinIO 비활성화, RL 자동 재학습 비활성화 설정 참고
- `docker-compose.yml` — base 서비스 정의. 포트 매핑(8000, 5173, 5432, 6379), 볼륨(postgres_data, redis_data), 네트워크 구조, healthcheck 설정 확인
- `scripts/oci/setup_monitoring.sh` — OCI 알람 부트스트랩 스크립트. ONS topic, email subscription, CPU/Memory/Disk 알람 3종, monthly budget + alert rule 생성. 멱등 설계로 재실행 안전
- `scripts/oci_instance_retry.sh` — 기존 인스턴스 생성 크론 스크립트. Telegram curl 패턴(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 환경변수 사용)을 disk_monitor.sh에서 재활용
- `.env.example` — 포트, Telegram 토큰, S3 설정 등 환경변수 목록. OpenClaw 포트 충돌 방지를 위한 참고
- `CLAUDE.md:18` — 서버 IP "152.67.223.37" 참조 (134.185.110.214로 업데이트 대상)
- `docs/oracle-cloud-setup.md` — 인스턴스 IP 및 서버 설정 가이드 (IP 업데이트 대상)
- `progress.md` — 서버 IP 참조 (IP 업데이트 대상)

### 7.2 참고 소스

- Oracle Cloud Always Free Tier 공식 문서 — ARM A1 총 4 OCPU / 24 GB, 최대 4개 인스턴스까지 분할 가능. AMD Micro는 VM.Standard.E2.1.Micro로 1 OCPU / 1 GB, 2개 무료
- 이전 세션 토론 결과 — 서버 확보를 위한 8개 옵션 브레인스토밍(리사이징, terminate+재생성, AMD Micro, Hetzner, Vultr, DigitalOcean, 동거, K3s on Micro) 및 4라운드 의사결정 과정

### 7.3 영향받는 파일

- `docker-compose.prod.yml` — 서비스별 리소스 제한(mem_limit) 변경, 파일 상단 주석에서 "Hetzner CX22"를 "Oracle ARM A1"로 변경
- `CLAUDE.md` — 배포 서버 IP 주소를 152.67.223.37에서 134.185.110.214로 변경
- `docs/oracle-cloud-setup.md` — 인스턴스 IP 주소 변경
- `progress.md` — IP 주소 변경 및 서버 동거 작업 완료 기록
- `scripts/oci/disk_monitor.sh` — 신규 생성. Docker 볼륨 디스크 사용량 모니터링 + Telegram 알림

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
