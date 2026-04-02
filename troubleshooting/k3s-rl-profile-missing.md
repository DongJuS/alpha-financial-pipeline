# K3s RL 부트스트랩 — profile JSON 파일 누락

> 발생일: 2026-03-30
> 상태: 해결 (임시: kubectl cp, 영구: Dockerfile COPY 또는 PVC)

---

## 증상

K3s에서 RL 부트스트랩 실행 시:
```
profile tabular_q_v2_momentum 없음
```
3종목 전부 학습 실패.

## 원인

`artifacts/rl/profiles/*.json` 파일이 Docker 이미지에 포함되지 않음.
Dockerfile의 `COPY` 구문이 `src/`와 `scripts/`만 복사하고 `artifacts/`는 빠져있음.

```dockerfile
COPY src ./src
COPY scripts ./scripts
# artifacts/ 복사 없음 ← 이것이 원인
```

## 해결 (임시)

```bash
WORKER_POD=$(kubectl get pod -n alpha-trading -l app=worker -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n alpha-trading $WORKER_POD -- mkdir -p /app/artifacts/rl/profiles
kubectl cp artifacts/rl/profiles/tabular_q_v2_momentum.json alpha-trading/$WORKER_POD:/app/artifacts/rl/profiles/
kubectl cp artifacts/rl/profiles/tabular_q_v1_baseline.json alpha-trading/$WORKER_POD:/app/artifacts/rl/profiles/
```

## 영구 해결 (TODO)

Dockerfile dev 스테이지에 추가:
```dockerfile
COPY artifacts ./artifacts
```

또는 RL 모델/프로파일 전용 PVC를 마운트.

## 추가 이슈: kubectl cp 디렉토리 중첩

`kubectl cp dir/ pod:/path/dir/` 실행 시 `/path/dir/dir/`로 중첩 복사됨.
파일 단위로 복사해야 함.

---
