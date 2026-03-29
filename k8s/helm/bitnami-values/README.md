# Bitnami Helm 인프라 설치 가이드

인프라(PostgreSQL, Redis, MinIO)는 Bitnami Helm chart로 별도 설치합니다.
앱(api, worker, ui)은 `k8s/helm/alpha-trading/` 또는 Kustomize로 배포합니다.

## 사전 준비

```bash
# Bitnami repo 추가
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# namespace 생성
kubectl create namespace alpha-trading
```

## 설치 순서

```bash
cd k8s/helm/bitnami-values

# 1. PostgreSQL
helm install postgresql bitnami/postgresql \
  -n alpha-trading -f postgres-values.yaml

# 2. Redis
helm install redis bitnami/redis \
  -n alpha-trading -f redis-values.yaml

# 3. MinIO
helm install minio bitnami/minio \
  -n alpha-trading -f minio-values.yaml

# 4. 상태 확인
kubectl get pods -n alpha-trading
```

## 서비스명 (앱에서 참조)

| 서비스 | 호스트명 | 포트 |
|---|---|---|
| PostgreSQL | `postgresql` | 5432 |
| Redis | `redis-master` | 6379 |
| MinIO | `minio` | 9000 |

## 삭제

```bash
helm uninstall minio redis postgresql -n alpha-trading
```

## 업그레이드

```bash
helm upgrade postgresql bitnami/postgresql -n alpha-trading -f postgres-values.yaml
helm upgrade redis bitnami/redis -n alpha-trading -f redis-values.yaml
helm upgrade minio bitnami/minio -n alpha-trading -f minio-values.yaml
```
