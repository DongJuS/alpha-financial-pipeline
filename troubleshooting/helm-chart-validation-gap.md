# Helm Chart 검증 미완료 항목

> 생성일: 2026-03-29
> 상태: 미해결 (환경 제약)
> 관련 PR: #38

---

## 증상

K3s Helm Chart(`k8s/helm/alpha-trading/`)를 작성했으나, 로컬 환경에 `helm` CLI와 K3s 클러스터가 없어 실제 배포 검증을 수행하지 못함.

## 미검증 항목

### 1. `helm template` 렌더링 검증
- **문제:** `helm`이 설치되어 있지 않아 `helm template .` 명령으로 Go 템플릿이 올바르게 렌더링되는지 확인 불가
- **수행한 대체 검증:** Chart.yaml/values.yaml YAML 파서 통과, 10개 템플릿의 `{{ }}` 열림/닫힘 균형 확인
- **남은 리스크:**
  - `_helpers.tpl`의 `define`/`include` 참조가 실제로 resolve되는지 미확인
  - `toYaml`, `nindent`, `quote` 등 Helm 내장 함수 호출 결과 미확인
  - `range` 루프 (`configmap.yaml`의 `worker.env` 순회) 렌더링 미확인

### 2. `helm install --dry-run` 검증
- **문제:** K3s/K8s 클러스터 없이는 dry-run 불가
- **남은 리스크:**
  - K8s API 버전 호환성 미확인 (예: `policy/v1` PDB가 K3s 버전에서 지원되는지)
  - `storageClassName: local-path`가 K3s에서 기본 제공되는지 확인 필요 (K3s 기본 제공이지만 버전별 차이 가능)

### 3. StatefulSet PVC 바인딩
- **문제:** 실제 스토리지 프로비저너 없이는 PVC가 바인딩되는지 확인 불가
- **남은 리스크:**
  - PostgreSQL 10Gi, Redis 2Gi, MinIO 20Gi PVC가 local-path provisioner에서 정상 생성되는지
  - 노드 디스크 용량 부족 시 Pod 스케줄링 실패 가능

### 4. Ingress 라우팅
- **문제:** Traefik Ingress Controller 없이는 라우팅 테스트 불가
- **남은 리스크:**
  - `traefik.ingress.kubernetes.io/router.entrypoints: web` 어노테이션이 K3s 기본 Traefik에서 동작하는지
  - `/api` prefix stripping이 필요한지 (현재 미설정)

### 5. Secrets 실제 주입
- **문제:** `secrets.yaml`의 `stringData` 값이 placeholder 상태
- **남은 리스크:**
  - 프로덕션 배포 시 실제 시크릿으로 교체 필요
  - `kubectl create secret`이나 external-secrets-operator 연동 미구현

### 6. MinIO Init Job Helm Hook
- **문제:** `helm.sh/hook: post-install,post-upgrade` 어노테이션이 정상 동작하는지 미확인
- **남은 리스크:**
  - MinIO가 ready 상태가 되기 전에 Job이 실행되면 실패 가능 (retry loop 있으나 실환경 검증 필요)

## 해결 방안

1. K3s 클러스터 구축 후 아래 순서로 검증:
   ```bash
   # 1. 템플릿 렌더링 확인
   helm template alpha-trading k8s/helm/alpha-trading/

   # 2. dry-run
   helm install alpha-trading k8s/helm/alpha-trading/ -n alpha-trading --create-namespace --dry-run

   # 3. 실제 배포
   helm install alpha-trading k8s/helm/alpha-trading/ -n alpha-trading --create-namespace

   # 4. 상태 확인
   kubectl get all -n alpha-trading
   kubectl get pvc -n alpha-trading
   ```

2. CI에서 `helm lint` + `helm template` 자동 검증 추가 (Worker 2 CI/CD 작업에서 처리)
