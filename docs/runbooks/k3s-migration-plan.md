# k3s 마이그레이션 계획 (manager runbook)

운영 OCI 단일 노드 docker compose 스택을 k3s 로 무중단 전환한다. 본 문서는
전체 phase 순서, 의존, 게이트, 롤백 절차를 한 곳에서 추적하는 매니저
문서다.

## 컨텍스트 (착수 시점)

- 운영 호스트: OCI Ampere ARM64 24 GB / 4 vCPU / 200 GB (Ubuntu 24.04)
- 현재: docker compose 10 컨테이너 (alpha 5 prod + ui + infisical 3 + openclaw)
- 외부 노출: cloudflared Quick Tunnel 2 종 (UI 5173 / OpenClaw 18789)
- 시크릿: 현재 `.env` 평문 → Infisical 으로 이전 진행 중
- 분리 운영: alpha repo (메인 코드, public 예정) + agents-investing-infisical
  repo (Infisical 인프라, private) + agents-investing-ops repo (운영 식별자, private)

## 원칙

- **평문 시크릿 금지** — Infisical Kubernetes Operator 또는 SOPS+age
- **무중단** — docker compose 와 k3s 가 한동안 병행, 트래픽 점진 전환
- **단계마다 검증** — helm lint / dry-run / pod ready / smoke test 통과 후 다음
- **매 단계마다 commit + PR + main merge** — 외부 독자가 이해되는 commit body

## Phase 순서

### Phase 1 — k3s 클러스터 + helm + kubectl 설치 ✅ **완료**

- 단일 노드 k3s (`--disable traefik --disable servicelb`) — 포트 80 (Infisical)
  충돌 회피, ingress controller 는 후 phase 에서 별도 설치
- helm v3 + kubectl 설치
- 산출물: `docs/runbooks/k3s-install.md` (본 PR), `progress.md` 항목
- 검증: `kubectl get nodes` Ready, 3 system pod (coredns, local-path-provisioner,
  metrics-server) Running, docker 10 컨테이너 그대로 healthy
- 롤백: `sudo /usr/local/bin/k3s-uninstall.sh` (docker 영향 0)

### Phase 2 — Infisical 을 k3s 로 (별도 repo) [예정]

대상 repo: `DongJuS/agents-investing-infisical`

- Infisical 공식 helm chart 도입 (또는 직접 작성한 manifest)
- 부트스트랩 시크릿 (ENCRYPTION_KEY, AUTH_SECRET, DB_PASSWORD, SITE_URL) 처리
  — **SOPS + age** 채택 (무료, git 안전, helm-secrets 플러그인). age 키는
  ops repo 또는 password manager 에 운영자만 보관
- k3s 의 새 Infisical 과 docker compose 의 기존 Infisical 을 **dual-run**
  (다른 namespace + 별도 PVC) 시키고 트래픽 (alpha 의 INFISICAL_API_URL)
  은 cutover 시점에 전환
- 데이터 마이그레이션: 운영 Infisical 의 PostgreSQL dump → 새 k3s 의
  StatefulSet PVC 로 복원
- CI/CD: `agents-investing-infisical` repo 의 `deploy.yml` 을 helm install /
  upgrade 호출하도록 갱신
- 검증: 새 Infisical UI 로그인, 기존 시크릿/프로젝트 가시화, alpha pod 에서
  새 endpoint 로 시크릿 받기 smoke test
- 게이트: 사용자 확인 (실제 트래픽 전환 시점)
- 롤백: helm uninstall + docker compose Infisical 계속 운영

### Phase 3 — alpha helm chart 처음부터 작성 [예정]

대상 repo: `DongJuS/alpha-financial-pipeline`

- `k8s/helm/alpha-trading/` 디렉터리가 사실상 비어있음 (Chart.yaml/values.yaml/
  templates yaml 0 개) — `docker-compose.prod.yml` 의 5 prod 서비스 + ui 를
  helm templates 로 1:1 매핑
- `templates/`:
  - `deployment-api.yaml`, `deployment-worker.yaml`, `deployment-tick-collector.yaml`
  - `deployment-ui.yaml` (nginx prod stage)
  - `job-db-init.yaml`, `job-db-init-migrate.yaml` (`helm.sh/hook: pre-install,pre-upgrade`)
  - `statefulset-postgres.yaml`, `statefulset-redis.yaml`
  - `service-*.yaml`, `ingress.yaml`
  - `infisical-secret.yaml` (InfisicalConnection + InfisicalAuth + InfisicalStaticSecret CR)
- `values.yaml`: image.repository (`ghcr.io/dongjus/alpha-financial-pipeline/api` 등),
  resources, env 비시크릿, replica
- `overlays/prod/values.yaml`: OCI prod 전용 override (replica, resource limits)
- 검증: `helm lint`, `helm template`, `helm install --dry-run`, CI 의
  helm-lint job 의미 있어짐
- 게이트: 머지 후 별도 phase 에서 실제 배포 (Phase 4)

### Phase 4 — Infisical Operator + CI/CD 갱신 [예정]

- alpha 의 k3s 네임스페이스에 Infisical Kubernetes Operator 설치 (`helm install`)
- `InfisicalConnection`, `InfisicalAuth` (Universal Auth — machine identity
  client ID/secret 은 k8s Secret), `InfisicalStaticSecret` 매니페스트 적용
  → alpha 가 사용할 23 개 시크릿이 자동으로 k8s Secret 으로 동기화
- alpha repo 의 `.github/workflows/deploy.yml` (기존 K3s 워크플로우 — 현재
  비활성) 의 image 태그 / helm chart 위치 / 시크릿 명을 현재 구조로 갱신 +
  자동 트리거 재활성 (workflow_run on build-and-push)
- 기존 `deploy-prod.yml` (docker compose 직배포) 은 보존 — phase 5 dual-run
  기간에 두 워크플로우 둘 다 동작
- 검증: GHA workflow_dispatch 로 1 회 수동 실행, alpha pod 가 startup 시
  Infisical 시크릿을 정상 수신, smoke test (`/healthz`)

### Phase 5 — 점진 cutover [예정]

- k3s 와 docker compose 가 동시에 동작하는 기간
- cloudflared Quick Tunnel 의 backend 를 docker 의 5173/18789 에서 k3s 의
  ingress (또는 NodePort/포워딩) 로 단계 전환
- 트래픽 분배 (예: 1 시간 → 1 일 → 1 주) 후 각 단계마다 메트릭/에러율 확인
- 롤백: tunnel backend 를 docker 로 복귀

### Phase 6 — docker compose 종료 + 최종 cleanup [예정]

- 모든 트래픽이 k3s 로 안정화된 후 `docker compose down` (volume 은 보존)
- 며칠 후 docker volume 들도 OCI Archive 백업 후 정리 (`docker system prune -a --volumes`)
- 옛 deploy-prod.yml (docker compose 워크플로우) 비활성 또는 제거
- 운영 브랜치 `infra/oci-monitoring-and-budget` 삭제 (G10 — 사용자가 모든
  검증 완료 후 명시)
- `docs/runbooks/` 의 docker compose 관련 안내를 k3s 안내로 교체

## 핵심 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| Infisical DB 마이그레이션 중 데이터 손실 | 시크릿 전체 분실 = alpha 정지 | Phase 2 에서 dual-run + dump 무결성 verify (행 카운트 + checksum). docker Infisical 1 주 더 유지. |
| ENCRYPTION_KEY 분실 | 기존 DB 시크릿 복호 불가 = 영구 손실 | age 키 + ENCRYPTION_KEY 백업 2 군데 (password manager + ops repo). 회전 절대 X. |
| k3s 리소스 부족 (24 GB) | OOM kill | Phase 1 에서 kubelet eviction soft/hard 설정. Phase 3 에서 resource limits 보수적 설정. metrics-server 로 모니터링. |
| Cutover 중 cloudflared tunnel 손실 | 외부 UI 접근 불가 | Phase 5 에서 새 tunnel (k3s ingress 향) 동시 운영, 둘 다 telegram 으로 URL 통보. |

## 작업 단위 추정

- 총 8 ~ 12 PR (alpha + infisical 양쪽, phase 별 1~2 PR)
- 각 PR: helm lint / dry-run / unit test + commit body 상세 작성 + main merge
- 검증 단계 ~15 개

## 진행 상태 (live tracker)

- [x] **Phase 1** — k3s + helm + kubectl 설치 (alpha #209)
- [x] **Phase 2** — Infisical k3s helm chart (SOPS+age 부트스트랩) — infisical #4
- [x] **Phase 3** — alpha helm chart 갱신 (postgres/redis StatefulSet + tick-collector
      + db-init Job) — alpha #210, #211
- [x] **Phase 4** — Infisical Kubernetes Operator (secrets-operator v0.11.2) 설치 +
      InfisicalStaticSecret CR (`templates/infisical-secret.yaml`) — alpha #211
- [x] **Phase 5** — deploy.yml (K3s) 갱신 + `--atomic` — alpha #212, #213
- [x] **Phase 5b** — Infisical k3s 실 deploy 성공 (dual-run) — infisical #5~#10
      - 디버깅 trail (실 deploy 까지 6 회 retry 끝에 동작):
        1. private repo fetch 인증 → GH_TOKEN 전달 (#5)
        2. 옛 deploy.sh 닭달걀 → workflow 가 직접 fetch (#6)
        3. namespace.yaml 과 `--create-namespace` 충돌 → 매니페스트 제거 (#7)
        4. `$(DB_PASSWORD)` forward reference → env 순서 (#8)
        5. ssh idle timeout → ServerAliveInterval (#9)
        6. helm fail state stuck → `--atomic` (#10)
- [ ] **Phase 5c** — alpha 의 k3s 실 deploy
      - **사용자 사전 셋업** 필요 (자동 불가):
        a. Infisical UI 에서 `alpha-financial-pipeline` 프로젝트 + `prod` 환경
           생성 → 운영 `.env` 의 23 시크릿 import
        b. Machine Identity (Universal Auth) 발급 → client ID + secret 받음
        c. GH Environment `production` 의 두 시크릿 등록:
           `INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`
        d. GitHub PAT (`read:packages` scope) 발급 → GH secret `GHCR_PULL_TOKEN`
      - 위 완료 후 우리가 자동 진행:
        e. `kubectl create secret generic infisical-universal-auth ...`
        f. `kubectl create secret docker-registry ghcr-pull-secret ...`
        g. alpha 의 `deploy.yml` (K3s) workflow_dispatch
- [ ] **Phase 5d** — 점진 cutover
      - Infisical address (alpha `values.yaml` 의 `infisical.address`) 를
        docker compose 의 80 에서 k3s service (`http://infisical.infisical.svc.cluster.local:8080`) 로
        전환 — 이미 default 가 k3s service
      - 운영 Infisical 의 DB dump → 새 k3s Infisical 의 postgres 에 restore (시크릿
        데이터 마이그레이션). 또는 사용자가 처음부터 새 Infisical 에 입력 (Phase
        5c 의 a 항목과 동일)
      - cloudflared tunnel backend: docker (5173) → k3s ingress (별도 phase
        에서 ingress controller 활성 + tunnel 갱신)
- [ ] **Phase 6** — docker compose 종료 + 최종 cleanup
      - 모든 트래픽 안정화 후 `docker compose -p alpha-financial-pipeline down`
      - `docker compose -p infisical down` (k3s Infisical 로 완전 전환 후)
      - openclaw 는 별도 (k3s 이전 작업 시 phase 추가)
      - docker volume 백업 → OCI Archive 후 `docker system prune -a --volumes`
      - 옛 deploy-prod.yml (docker compose) 비활성 또는 제거
      - 운영 브랜치 `infra/oci-monitoring-and-budget` 삭제 (G10)
      - 본 runbook 의 docker compose 관련 안내 → k3s 전용으로 교체
