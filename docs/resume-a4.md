# 서동주

**Data Engineer** | didsusclzls@gmail.com | 010-2583-1899 | [github.com/DongJuS](https://github.com/DongJuS)

배치/실시간 데이터 파이프라인 설계·운영, 워크플로우 오케스트레이션, K8s 배포 자동화

---

## 기술 스택

**언어** Python · Java · SQL
**데이터** PostgreSQL · Redis · MinIO(S3) · Parquet · Delta Lake
**분산/스트리밍** Kafka · Spark · Arroyo
**인프라** K8s(K3s) · Helm · Kustomize · Docker · GitHub Actions CI/CD · Prometheus · Grafana

---

## 프로젝트

### 실시간 금융 데이터 파이프라인 설계 및 K8s 배포 자동화 (2026.03)

> GitHub: github.com/DongJuS/alpha-financial-pipeline | 266커밋 · 66 PR

한국+미국 9,363종목의 일봉 데이터를 수집·적재·분석하는 엔드-투-엔드 데이터 파이프라인을 설계하고 운영했습니다.

**데이터 파이프라인**
- 배치(FinanceDataReader) + 실시간(KIS WebSocket) 이중 수집 → PostgreSQL + S3 Parquet 적재
- 글로벌 데이터 레이크: 9,363종목 · 2,153만 행 · 연도별 파티셔닝 (NUMERIC 가격 KRW/USD 통합)
- N+1 쿼리 발견 → 배치 UPSERT 전환: **2,400 RTT → 1 RTT (DB 부하 95% 감소)**
- 720일 과거 데이터 백필 자동화, S3 Hive-style 파티셔닝 (`date=YYYY-MM-DD/`)

**워크플로우 오케스트레이션**
- APScheduler 기반 9개 스케줄 잡 (장 전/중/후 자동 운영)
- Redis SET NX 분산 락으로 멀티 Pod 중복 실행 방지 + 3회 exponential backoff 재시도
- Airflow 비교 스파이크: 수집 파이프라인을 Airflow DAG(6 태스크)로 이식 → 전체 SUCCESS

**인프라 / 운영**
- K3s 배포: Helm(Bitnami 인프라) + Kustomize(앱) 병행, CI/CD 4단계 게이트
- 557개 테스트 100% 통과 (462 → 557, event loop 오염 근본 해결)
- 8개 서비스 100% healthy, 클린 재기동 35초
- 트러블슈팅 9건 — Docker multi-stage 권한 문제 20분 해결, K8s ConfigMap 서비스명 불일치 등

### TPC-H/ClickBench 벤치마크 파이프라인 설계·수행

- TPC-H 명세서 130+ 페이지 분석 → dbgen SF10(~10GB) 22개 쿼리 Power/Throughput 성능 측정
- PostgreSQL과 분산 쿼리 엔진을 같은 인스턴스에서 실행 시 **캐시 간섭 발견** → 별도 DB 분리 설계 제안·채택
- ClickBench 43개 쿼리 cold/hot run 비교 측정, TTA 인증(GS인증) 성능 시험 시나리오 설계

### 스트리밍 엔진 기술 검토 + IoT 실시간 파이프라인

- (Quix+Arroyo) vs (Redis+Arroyo) 아키텍처 비교 → 파이프라인 관리 편의성 관점으로 기술 선택
- Modbus TCP + OpenCV + WebSocket으로 IoT 실시간 데이터 파이프라인 구현 → SCEWC 스페인 전시회 현장 시연
- 전시회 현장 장애 발생 시 이전 안정 버전으로 롤백하여 운영 유지

---

## 학력

한국기술교육대학교 — 컴퓨터공학과 (2024 ~ 재학중)

## 기타

정보처리기사 실기 준비중 | AWS Cloud Practitioner (2023) | TOEIC 835 | 병역 필 (2017~2019)
