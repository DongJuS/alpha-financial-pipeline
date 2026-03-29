# Step 4 CI/CD — 로컬 환경 제약으로 미검증 항목

> 생성일: 2026-03-29
> 관련 PR: #36

---

## 1. CI 워크플로우 실제 실행 미검증

- **상태:** `.github/workflows/ci.yml` 작성 완료, 실제 GitHub Actions 실행은 미확인
- **제약:** 로컬 환경에서 `act` 등 없이 워크플로우 문법/동작 검증 불가
- **리스크:**
  - `services:` 블록의 postgres/redis healthcheck 타이밍 이슈 가능
  - `ruff` 패키지가 requirements.txt에 없음 — CI에서 별도 설치 (`pip install ruff`)하는데, 버전 미고정
  - `pytest --ignore` 목록이 하드코딩됨 — 깨진 테스트 파일이 추가/제거되면 CI도 갱신 필요
- **확인 방법:** main push 후 Actions 탭에서 첫 실행 결과 확인

## 2. Deploy 워크플로우 secrets 미설정

- **상태:** `.github/workflows/deploy.yml` 작성 완료, secrets 미등록
- **제약:** K3s 호스트가 아직 구성되지 않음
- **필요 secrets:**
  - `K3S_HOST` — K3s 노드 IP/도메인
  - `K3S_USER` — SSH 접속 사용자
  - `K3S_SSH_KEY` — SSH 프라이빗 키
- **리스크:**
  - `appleboy/ssh-action@v1` 버전 고정 — 향후 breaking change 가능
  - Helm 경로 `~/agents-investing/k8s/helm/alpha-trading`가 K3s 호스트에 존재해야 함

## 3. Dockerfile prod 타겟 런타임 미검증

- **상태:** `docker build --target prod` 빌드 성공 확인
- **미검증:**
  - 실제 `docker run` 후 API 기동 여부 (DB 연결 없이 컨테이너 기동 테스트 불가)
  - `HEALTHCHECK` 엔드포인트 `/health`가 앱에 구현되어 있는지 미확인
  - `--workers 2` 설정이 메모리 1G 제한에서 안정적인지 부하 테스트 필요
  - non-root 사용자 `alpha`의 파일 접근 권한 문제 가능성 (특히 `/app/scripts/` 실행)
- **확인 방법:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  curl http://localhost:8000/health
  ```

## 4. docker-compose.prod.yml 오버라이드 검증

- **상태:** 문법적으로 작성 완료
- **미검증:**
  - `profiles: [gen-testing]`으로 gen/gen-collector 비활성화가 실제로 동작하는지
  - `volumes: []`로 dev 볼륨 마운트를 오버라이드하면 빈 리스트가 올바르게 적용되는지 (compose 버전에 따라 동작 다를 수 있음)
  - `deploy.resources.limits`는 `docker compose up`에서는 무시될 수 있음 (swarm 모드 전용) — K3s에서는 Helm의 resources로 대체
- **확인 방법:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml config
  ```

## 5. Prometheus/Grafana 실제 연동 미검증

- **상태:** config/dashboard JSON 작성 완료
- **미검증:**
  - 앱에 `/metrics` 엔드포인트가 아직 없음 (prometheus_client 미설치)
  - `kubernetes_sd_configs`는 K3s 클러스터 내에서만 동작
  - Grafana 대시보드의 metric 이름(`alpha_orchestrator_cycle_total` 등)이 앱에서 실제 export되는지
- **리스크:** 앱에 prometheus metrics instrumentation이 추가되기 전까지는 대시보드가 빈 상태
- **선행 작업:** `pip install prometheus-client` + FastAPI middleware 추가

## 6. Python 3.9 vs 3.11 호환성

- **상태:** 로컬 테스트는 Python 3.9.6 (macOS system python)으로 실행
- **Dockerfile/CI:** Python 3.11 기준
- **리스크:**
  - 로컬에서 통과한 테스트가 3.11에서 실패할 가능성 낮지만, `match` 문 등 3.10+ 문법 사용 시 역방향 호환성 문제 가능
  - 기존 47개 실패 중 4개는 Python 3.9의 `X | None` union type 미지원 (`TypeError: unsupported operand type(s) for |`) — 3.11에서는 통과할 것으로 예상

## 7. Helm chart 검증 상태 (E)

- **helm lint:** 통과 ✅ (icon 권장 INFO만)
- **helm template:** 전체 렌더링 정상 ✅
- **실제 K3s dry-run:** 미검증 (클러스터 없음)
- **수정 사항:**
  - worker.yaml: readiness probe 추가, RL 데이터 PVC + volumeMounts 추가
  - values.yaml: `rlDataStorage: 5Gi` 추가
- **잔여 리스크:**
  - `local-path` StorageClass가 K3s에서 기본 제공되지만, 커스텀 설정 시 변경 필요
  - worker PVC `ReadWriteOnce` → replicas > 1이면 `ReadWriteMany` 또는 별도 PVC 필요

## 8. readiness.py ↔ Helm chart 정합 (H)

- **DNS 서비스명:** `postgres`, `redis`, `minio` → Helm chart Service name과 일치 ✅
- **볼륨 마운트:** `/data/rl/models`, `/data/rl/experiments` → worker.yaml에 PVC로 마운트 ✅
- **ServiceAccount 토큰:** 표준 경로 `/var/run/secrets/kubernetes.io/serviceaccount/token` ✅
- **수정 사항:** MinIO DNS 체크 추가

---

*이 파일은 위 항목이 모두 검증되면 MEMORY.md에 요약 후 삭제합니다.*
