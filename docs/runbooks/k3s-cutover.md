# k3s 컷오버 런북 (Phase 5c → 6)

`k3s-migration-plan.md` 의 Phase 5c, 5d, 6 의 실행 절차. Phase 1~5b 완료
시점부터 시작.

## Phase 5c — alpha 의 k3s 첫 deploy

### 사용자 사전 셋업 (자동 불가)

**1) Infisical UI 에서 alpha 프로젝트 + 시크릿 import**

브라우저로 `http://<운영_OCI_IP>:80` 접속 (현재 docker compose 의 Infisical).

- 로그인 → Organization → **New Project**
  - 이름: `alpha-financial-pipeline`
  - 환경: `prod` 만 (또는 prod/staging/dev)
- 프로젝트 진입 → **Secrets → Drop in your .env file**
  - 운영 서버의 `/home/ubuntu/alpha-financial-pipeline/.env` 를 사용자 머신
    으로 다운로드: `scp alpha-trading:/home/ubuntu/alpha-financial-pipeline/.env ~/Desktop/alpha-prod.env`
  - UI 에 drag-and-drop 또는 파일 선택 → 23 키 자동 import
  - 등록 직후 `~/Desktop/alpha-prod.env` shred / 삭제

**2) Machine Identity (Universal Auth) 발급**

- Organization → **Access Control → Machine Identities → Create**
  - Name: `alpha-k3s-operator`
- 발급된 Identity → **Roles & Permissions → Add Project Role**
  - Project: `alpha-financial-pipeline`, Role: `Viewer` (시크릿 read 만 필요)
- 같은 Identity → **Authentication Methods → Add → Universal Auth**
  - **Create Client Secret** → client ID + client secret 표시 (한 번만, 복사 필수)

**3) GH Environment 시크릿 등록**

```bash
printf '<client-id>' | gh secret set INFISICAL_CLIENT_ID \
    --repo DongJuS/alpha-financial-pipeline --env production
printf '<client-secret>' | gh secret set INFISICAL_CLIENT_SECRET \
    --repo DongJuS/alpha-financial-pipeline --env production
```

**4) GitHub PAT (`read:packages` scope) 등록 — GHCR private pull 용**

GitHub → Settings → Developer settings → Personal access tokens → Tokens
(classic) → Generate new token → scope `read:packages` 만 → 발급.

```bash
printf '<pat>' | gh secret set GHCR_PULL_TOKEN \
    --repo DongJuS/alpha-financial-pipeline --env production
```

### 자동 진행 (위 4 항목 끝 신호 후)

5. `kubectl -n alpha-trading create secret generic infisical-universal-auth`
   `--from-literal=clientId=$INFISICAL_CLIENT_ID --from-literal=clientSecret=$INFISICAL_CLIENT_SECRET`
6. `kubectl -n alpha-trading create secret docker-registry ghcr-pull-secret`
   `--docker-server=ghcr.io --docker-username=DongJuS --docker-password=$GHCR_PULL_TOKEN`
7. alpha 의 `deploy.yml` (K3s) `workflow_dispatch` 트리거
8. helm install 후 pod 상태 확인 — api / worker / tick-collector / ui /
   postgres / redis 모두 Running, db-init-migrate Job Succeeded
9. InfisicalStaticSecret CR 동작 확인:
   `kubectl -n alpha-trading describe infisicalstaticsecret alpha-secrets-sync`
10. 동작 확인: pod 안에서 `printenv KIS_REAL_APP_KEY` 등으로 값 주입 검증

### Phase 5c 검증 통과 기준

- 4 Deployment + 2 StatefulSet 모두 Running
- db-init-migrate Job Succeeded (Helm hook)
- alpha-trading-secrets Secret 이 Operator 에 의해 자동 생성 + 23 키 포함
- api 의 `/healthz` 200 응답
- docker compose 의 alpha 컨테이너 5 종 여전히 동작 (dual-run)

## Phase 5d — 점진 cutover (트래픽 전환)

### 현재 외부 트래픽

- UI: cloudflared Quick Tunnel → docker compose 의 ui (5173)
- OpenClaw: cloudflared Quick Tunnel → docker openclaw (18789)

### 전환 절차

1. k3s 안의 alpha ui 가 healthy 확인 (`kubectl -n alpha-trading get pod -l app.kubernetes.io/component=ui`)
2. k3s 의 ui Service NodePort 또는 ingress 노출 결정 (Phase 4 의 ingress
   controller 가 안 깔린 상태 — nginx-ingress 또는 단순 NodePort)
3. `scripts/oci/cloudflared_tunnel.sh` 의 `CF_TUNNEL_PORT` 를 5173 → k3s 의
   NodePort (예: 30080) 또는 ingress 의 80 으로 변경
4. systemd: `sudo systemctl restart cloudflared-tunnel-investing.service`
5. 새 trycloudflare.com URL 이 Telegram 으로 통보됨
6. 외부 접근 → k3s 의 ui 가 응답 확인 (스모크 테스트)
7. 1~2 일 모니터링: helm release ready, pod restart 0, 에러 로그 0

### 롤백 (전환 실패 시)

`cloudflared_tunnel.sh` 의 포트를 다시 5173 으로 + systemd restart → 즉시
docker ui 로 복귀. k3s alpha 는 그대로 두고 추후 진단.

## Phase 6 — docker compose 종료 + 최종 cleanup

### 사전 확인

- Phase 5c, 5d 완료
- 24 시간 이상 k3s 트래픽 안정 (에러율 < 0.1%)
- 운영자가 명시적 OK (G10 게이트)

### 절차

```bash
ssh alpha-trading

# alpha docker compose 종료 (volume 보존)
cd /home/ubuntu/alpha-financial-pipeline
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# Infisical docker compose 종료 (k3s Infisical 로 완전 전환된 후만)
cd /home/ubuntu/infisical
docker compose down

# openclaw 는 별도 (k3s 이전 작업 시 추가 phase. 본 작업 범위 외)

# volume 백업 → OCI Archive
for v in $(docker volume ls -q | grep -E '^(alpha-financial-pipeline|infisical)_'); do
  docker run --rm -v "$v:/data" -v /tmp:/backup alpine tar -czf "/backup/$v.tar.gz" -C /data .
  source ~/deploy/.env.bootstrap
  /usr/local/bin/aws --endpoint-url "$OCI_BACKUP_ENDPOINT" --region ap-chuncheon-1 \
      s3 cp "/tmp/$v.tar.gz" "s3://$OCI_BACKUP_BUCKET/alpha/volumes-final/$v.tar.gz" \
      --no-progress
  rm -f "/tmp/$v.tar.gz"
done

# volume 삭제
docker volume rm $(docker volume ls -q | grep -E '^(alpha-financial-pipeline|infisical)_')

# 이미지 정리
docker system prune -a --volumes
```

### 그리고

- `deploy-prod.yml` (docker compose 워크플로우) 비활성 또는 제거 (별도 PR)
- 운영 브랜치 `infra/oci-monitoring-and-budget` 삭제 (G10 — 사용자 명시)
- `docs/runbooks/deploy-cutover.md` 의 docker compose 안내 → k3s 안내로 교체
  (또는 `deploy-cutover.md` 폐기, `k3s-cutover.md` 가 갈음)

### 롤백 (Phase 6 완료 후 문제 발견)

`docker compose -f ... up -d` 한 줄로 컨테이너 복귀. 그러나 volume 백업
파일 OCI Archive 에서 다운로드 → 복원 필요.
