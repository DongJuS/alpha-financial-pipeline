# K3s 이미지 코드 불일치 — main pull 안 하고 빌드

> 발생일: 2026-03-30
> 상태: 해결

---

## 증상

K3s worker pod에서 `MarketDataPoint`에 `instrument_id` 필드가 없다고 에러.
PR #76으로 머지했는데 K3s에 반영이 안 됨.

## 원인

1. PR #76은 **워크트리 브랜치**에서 머지 → GitHub의 origin/main에는 반영
2. **로컬 main 브랜치**는 `git pull` 안 해서 이전 코드 상태
3. `docker build`가 로컬 main의 이전 코드로 이미지 생성
4. K3s에 배포해도 이전 코드 이미지

## 해결

```bash
git checkout main && git pull origin main  # 로컬 main 최신화
docker build --target dev -t alpha-trading:v4 .  # 최신 코드로 빌드
kubectl set image deployment/worker worker=alpha-trading:v4 -n alpha-trading
```

## 재발 방지

K3s 이미지 빌드 전 반드시 `git pull origin main` 실행.
CI/CD 파이프라인이 구축되면 이 문제는 자연 해결 (GitHub Actions가 origin/main 기준으로 빌드).

---
