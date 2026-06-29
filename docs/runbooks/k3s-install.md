# k3s 단일 노드 설치 (OCI Ampere ARM64)

`k3s-migration-plan.md` 의 Phase 1 에서 한 작업의 정확한 명령/검증 기록.
docker compose 스택이 운영 중인 상태에서 무중단으로 k3s 를 옆에 띄운다.

## 사전 확인 (운영 영향 X)

```bash
ssh alpha-trading

# 자원 여유 확인
df -h /                       # 60 GB+ 여유 필요
free -h                       # k3s 자체 ~500 MB, system 4 GB 예상

# 점유 포트 확인 — k3s 가 쓰려는 포트와 충돌 없는지
sudo ss -tlnp | grep -E ":(80|443|6443|2379|2380|10250|10257|10259)\s"

# 기대: 80 만 Infisical 점유, 나머지는 비어있음
```

## 설치

```bash
# k3s 설치 (Traefik / ServiceLB 비활성)
# - Traefik: 80/443 점유 → 기존 Infisical 80 과 충돌 → 비활성. ingress controller 는 후 phase 에서.
# - ServiceLB (klipper-lb): LoadBalancer service 가 host network 점유 → 단일 노드라 사용 X.
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="server --disable traefik --disable servicelb --write-kubeconfig-mode=644" \
  sh -
```

## kubectl + helm 셋업

```bash
# kubectl: k3s 가 내장한 것을 PATH 에 (또는 ubuntu 사용자에 kubeconfig 복사)
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown ubuntu:ubuntu ~/.kube/config
chmod 600 ~/.kube/config
sudo ln -sf /usr/local/bin/k3s /usr/local/bin/kubectl

# helm v3 — apt 저장소는 GPG 인증 이슈가 있어 공식 install script 사용
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 -o /tmp/get-helm.sh
chmod +x /tmp/get-helm.sh
sudo /tmp/get-helm.sh
rm /tmp/get-helm.sh
```

## 검증

```bash
# 노드 + 시스템 pod 가 Ready / Running
kubectl get nodes -o wide
kubectl get pods -A

# 기대 결과:
# - 1 node, Ready, control-plane, ARM64
# - kube-system 에 coredns, local-path-provisioner, metrics-server 3개 Running

# docker compose 영향 0
docker ps --format "table {{.Names}}\t{{.Status}}"
# 기대: 기존 10 컨테이너 모두 그대로 Healthy
```

## 외부 kubectl 접근 (선택)

```bash
# 로컬 머신에서 (Windows/Mac):
scp alpha-trading:~/.kube/config ~/.kube/alpha-k3s.yaml

# 127.0.0.1 → 운영 IP 로 치환 (kubeconfig 안의 server 필드)
sed -i 's|127\.0\.0\.1|<OCI_PUBLIC_IP>|' ~/.kube/alpha-k3s.yaml

# 사용
export KUBECONFIG=~/.kube/alpha-k3s.yaml
kubectl get nodes
```

⚠️ `<OCI_PUBLIC_IP>` 가 외부에서 6443 포트로 접근 가능해야 한다. OCI
Security List 에 6443 inbound 허용 + iptables/ufw 동기화 필요. 본 Phase 1
에서는 셋업 안 함 (외부 노출은 G8 와 함께 검토).

## 롤백

```bash
# k3s 만 깨끗하게 제거 (docker compose 영향 0)
sudo /usr/local/bin/k3s-uninstall.sh
# kubectl/helm 도 제거하려면
sudo rm /usr/local/bin/kubectl /usr/local/bin/helm
```

## Phase 1 이후

다음 단계 (Phase 2: Infisical 을 k3s 로) 부터는 `agents-investing-infisical`
repo 에서 진행. 본 repo (alpha) 의 helm chart 는 Phase 3 에서 작성.
