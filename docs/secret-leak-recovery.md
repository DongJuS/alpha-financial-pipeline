# Secret Leak 사고 대응

> Secret 값이 터미널 / 채팅 / 로그 / git 등 어디든 노출됐을 때.
> 일상 운영(rotation 이 아닌 편집/배포)은 `docs/secrets.md` 참조.

## 한 번에 끝내기

```bash
bash k8s/scripts/rotate-secrets.sh
```

스크립트가 자동 수행:

1. `.env` 백업 (`.env.bak.<timestamp>`, chmod 600)
2. KIS PAPER / KIS REAL / Telegram 새 키 입력 (Enter = 유지)
3. `JWT_SECRET` 재생성 (`openssl rand -hex 32`)
4. postgres `alpha_user` 비번 재생성 + `ALTER USER` + 검증
5. `.env` 원자적 업데이트
6. 기존 `k8s/secrets/app-secret.enc.yaml` 삭제 + `secrets-bootstrap.sh` 재실행
7. `deploy-local.sh` 호출 (decrypt → apply → rollout)
8. api pod Running + DB 연결 검증

## 스크립트 실행 *전* — 사용자가 직접

leak 된 키를 **각 원천에서** 새로 발급해 두기:

| Secret | 발급처 |
|---|---|
| KIS PAPER 키 | KIS Developers 포털 → 모의투자 앱 → 키 재발급 |
| KIS REAL 키 | KIS Developers 포털 → 실거래 앱 → 키 재발급 |
| Telegram BOT TOKEN | @BotFather → `/revoke` → `/newtoken` |
| JWT / postgres 비번 | (스크립트가 자동 재생성) |

## 스크립트 실행 *후* — 사용자가 직접

```bash
# 1. 터미널 scrollback 정리 (이전 leak 본 제거)
clear && printf '\033[3J'

# 2. 백업 파일 검수 후 삭제
ls -lh .env.bak.*
rm .env.bak.*

# 3. 새 .sops.yaml + app-secret.enc.yaml 커밋
git add .sops.yaml k8s/secrets/app-secret.enc.yaml
git commit -m "chore(secrets): rotate after leak incident"
# push 는 .github/GIT_PUSH.md 절차
```

## 검증 hook (개발자용)

`test/test_secrets_sops.sh` case 14 (`test_rotate_secrets_end_to_end_hermetic`)
가 가짜 repo + hermetic age key 로 rotation 흐름 전체를 실제 postgres /
kubectl / docker 없이 end-to-end 검증한다. `ROTATE_NON_INTERACTIVE`,
`ROTATE_SKIP_CONFIRM`, `ROTATE_SKIP_POSTGRES`, `ROTATE_SKIP_DEPLOY` 환경
변수는 **테스트 전용** — 운영자는 절대 직접 export 하지 말 것.

## 관련 파일

- `k8s/scripts/rotate-secrets.sh` — 한 번에 회전 + 재배포
- `k8s/scripts/secrets-bootstrap.sh` — 부트스트랩 (rotate 가 자동 호출)
- `k8s/scripts/deploy-local.sh` — 배포 (rotate 가 자동 호출)
- `test/test_secrets_sops.sh` — SOPS 파이프라인 단위 테스트 (14건, merge gate)
- `docs/secrets.md` — 일상 운영 가이드
