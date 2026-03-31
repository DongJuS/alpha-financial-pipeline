# K8s Secret과 ConfigMap의 DATABASE_URL 중복

> 발생일: 2026-03-30
> 상태: 해결 완료

---

## 증상

K3s에서 API가 DB에 `CHANGE_ME` 패스워드로 접속 시도 → 인증 실패.

ConfigMap에는 올바른 패스워드가 있는데도 적용되지 않음.

## 원인

`secrets.yaml`과 `configmap.yaml` 둘 다 `DATABASE_URL`을 정의.

K8s 환경변수 우선순위: **Secret > ConfigMap > Pod spec**

Secret의 `DATABASE_URL` 값이 플레이스홀더(`CHANGE_ME`)였으므로, ConfigMap의 올바른 값을 덮어씀.

## 해결

`k8s/base/secrets.yaml`에서 DATABASE_URL, REDIS_URL 제거.
접속 정보는 ConfigMap에서만 관리.

## 교훈

K8s에서 같은 환경변수를 Secret과 ConfigMap 양쪽에 정의하면 Secret이 이김.
"환경변수가 어디서 오는지" 항상 `kubectl exec -- env | grep`으로 확인.

---

*이 파일은 push 후 MEMORY.md에 요약 기록 후 삭제합니다.*
