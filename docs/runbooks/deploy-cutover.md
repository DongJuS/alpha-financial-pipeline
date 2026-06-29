# Deploy 컷오버 런북

GitHub `main` → OCI 서버 자동 배포 파이프라인 활성화 시점에 따라야 할 절차.

## 사전 조건 (모두 완료돼 있어야 함)

- [ ] PR-1 (`feat/server-runtime-capture`) 머지 — 운영 dirty 변경 캡처
- [ ] PR-2 (`feat/ops-branch-rebased`) 머지 — 운영 브랜치의 잔여 변경 흡수
- [ ] PR-public-prep (`chore/public-prep`) 머지 — IP/호스트명 격리
- [ ] PR-cicd (`feat/cicd-pipeline`) 머지 — 본 워크플로우 / deploy 스크립트
- [ ] PR-compose-registry 머지 — `docker-compose.prod.yml` 의 `build` 와 `image` 병기
- [ ] GitHub Environment `production` 생성 + secret 등록 (`OCI_SSH_*`, `TELEGRAM_BOT_TOKEN_DEPLOY` 등)
- [ ] Infisical 시크릿 마이그레이션 + 부트스트랩 `~/deploy/.env.bootstrap` 작성 + `infisical` CLI 설치 + `render-env.sh` 동작 확인

## 서버측 1회 셋업

```bash
# OCI 서버 ssh 접속
ssh alpha-trading

# deploy 스크립트 위치 (repo 의 scripts/deploy 를 symlink)
mkdir -p ~/deploy
ln -sf /home/ubuntu/alpha-financial-pipeline/scripts/deploy/deploy.sh       ~/deploy/deploy.sh
ln -sf /home/ubuntu/alpha-financial-pipeline/scripts/deploy/wait-healthy.sh ~/deploy/wait-healthy.sh
ln -sf /home/ubuntu/alpha-financial-pipeline/scripts/deploy/render-env.sh   ~/deploy/render-env.sh
ln -sf /home/ubuntu/alpha-financial-pipeline/scripts/deploy/pg_dump_to_r2.sh ~/deploy/pg_dump_to_r2.sh

# Infisical bootstrap (값은 Infisical 에서 발급 후 채움)
cat > ~/deploy/.env.bootstrap <<'EOF'
INFISICAL_TOKEN=<machine-identity-token>
INFISICAL_PROJECT_ID=<project-id>
INFISICAL_ENV=prod
INFISICAL_API_URL=http://127.0.0.1:80
EOF
chmod 600 ~/deploy/.env.bootstrap

# Infisical CLI 설치 (Ubuntu)
curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | sudo -E bash
sudo apt update && sudo apt install -y infisical

# DB 백업 cron (KST 23:00)
( crontab -l 2>/dev/null; echo "0 23 * * * /home/ubuntu/deploy/pg_dump_to_r2.sh" ) | crontab -

# 워킹트리를 main 으로 정렬 (운영 브랜치 폐기는 G10 단계)
cd /home/ubuntu/alpha-financial-pipeline
git fetch origin main
git checkout main
git reset --hard origin/main
```

## 첫 자동 배포 (수동 트리거로 검증)

1. GitHub Actions → `build-and-push` → `Run workflow` → main
2. 빌드 성공 확인 (GHCR `api`, `ui` 이미지 SHA 태그 가시화)
3. GitHub Actions → `deploy-prod` → `Run workflow` → image_tag 비워둠 (= main HEAD SHA)
4. SSH 단계 성공 → 서버에서 `docker compose ps` 4개 healthy 확인
5. Telegram 알림 도착 확인

## 자동 트리거 활성 (G9)

`deploy-prod.yml` 의 `on:` 블록에 다음 추가:

```yaml
on:
  workflow_run:
    workflows: [build-and-push]
    types: [completed]
    branches: [main]
```

조건문 추가:

```yaml
jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
```

이후 main push → build 성공 → 자동 deploy.

## 롤백

```bash
# 직전 성공 태그 확인
cat ~/deploy/.last_good_tag

# 임의 SHA 로 롤백 (예: 5분 전 SHA)
ssh alpha-trading "~/deploy/deploy.sh <previous-sha>"
```

`deploy.sh` 의 health check 실패 시 자동 롤백은 현재 미구현 — 수동 롤백 필요.

## 운영 브랜치 폐기 (G10)

main 정렬이 검증된 후:

```bash
# 로컬
gh api -X DELETE repos/DongJuS/alpha-financial-pipeline/git/refs/heads/infra/oci-monitoring-and-budget

# 서버
ssh alpha-trading 'cd /home/ubuntu/alpha-financial-pipeline && git branch -D infra/oci-monitoring-and-budget'
```
