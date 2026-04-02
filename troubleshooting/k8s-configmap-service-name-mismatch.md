# K3s ConfigMap 서비스명 불일치 (Helm vs Kustomize)

> 발생일: 2026-03-30
> 상태: 해결 완료

---

## 증상

K3s 배포 후:
- API: `InvalidPasswordError` (PostgreSQL 인증 실패)
- Worker: `Name or service not known` (Redis 접속 실패)

## 원인

Bitnami Helm chart가 생성하는 서비스명과 Kustomize configmap의 서비스명이 다름:

| 서비스 | ConfigMap (틀림) | 실제 Helm (맞음) |
|--------|------------------|------------------|
| PostgreSQL | `postgres` | `alpha-pg-postgresql` |
| Redis | `alpha-redis-redis-master` | `alpha-redis-master` |
| MinIO | `minio` | `alpha-minio` |

## 해결

`k8s/base/configmap.yaml`의 DATABASE_URL, REDIS_URL, S3_ENDPOINT_URL을 실제 Helm release명 기준으로 수정.

## 검증

```bash
kubectl get svc -n alpha  # 실제 서비스명 확인
kubectl exec deployment/api -- env | grep DATABASE_URL  # 정합성 확인
```

## 재발 방지

- `_helpers.tpl`에 서비스 URL 헬퍼를 추가하여 values.yaml에서 중앙 관리
- Helm release명 변경 시 configmap도 자동 반영되도록 구조화

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
