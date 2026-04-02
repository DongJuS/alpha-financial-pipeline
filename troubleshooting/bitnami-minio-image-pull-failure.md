# Bitnami MinIO 이미지 pull 실패

> 발생일: 2026-03-30
> 상태: 해결 완료

---

## 증상

K3s에서 MinIO pod가 `ImagePullBackOff` 상태.

```
Failed to pull image "docker.io/bitnami/minio-object-browser:2.0.2-debian-12-r3"
```

## 원인

Bitnami MinIO chart가 참조하는 `minio-object-browser` console 이미지가 레지스트리에 존재하지 않음.

Bitnami 이미지 유료화(2024년 말) 이후 일부 이미지가 공개 레지스트리에서 제거된 것으로 추정.

## 해결

Bitnami chart를 포기하고 공식 `minio/minio:latest` 이미지로 직접 Deployment 작성.

```yaml
# k8s/helm/bitnami-values/minio-values.yaml → 직접 Deployment로 전환
image: minio/minio:latest
command: ["minio", "server", "/data", "--console-address", ":9001"]
```

## 재발 방지

- Bitnami chart 사용 시 이미지 가용성을 `helm template`으로 사전 검증
- 인프라 컴포넌트는 공식 이미지 우선 사용 원칙

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
