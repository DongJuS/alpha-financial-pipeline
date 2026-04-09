# Secret 관리 — SOPS + age

> Cluster Secret 의 단일 진실 원천(Single Source of Truth)은 git 의
> `k8s/secrets/*.enc.yaml` 입니다. 평문 값은 git 에 절대 들어가지 않습니다.

## 왜 SOPS + age 인가

- **확장성** — 1인 → 2-3인 협업 시 `.sops.yaml` 의 `age:` 줄에 recipient 를
  콤마로 추가하기만 하면 됩니다. 환경 분리(paper/prod)는 디렉토리별
  rule 로 처리합니다.
- **안전** — age 는 X25519 + ChaCha20-Poly1305 (modern AEAD). 암호화된
  파일이 git 에 그대로 들어가도 평문은 노출되지 않습니다.
- **관리 수월함** — 운영해야 할 server 0대, controller 0개, unseal 의식
  없음. DR 은 age private key 1개 백업으로 끝납니다.

자세한 결정 배경은 PR `feat/secrets-sops-age` 본문을 참고하세요.

---

## 부트스트랩 (최초 1회)

```bash
brew install sops age
bash k8s/scripts/secrets-bootstrap.sh
```

스크립트가 자동으로 수행하는 일:

1. `~/.config/sops/age/keys.txt` 에 age 키쌍 생성 (이미 있으면 skip)
2. `.sops.yaml` 의 placeholder recipient 를 실제 public key 로 치환
3. `.env` 의 cluster secret 키들을 골라
   `k8s/secrets/app-secret.enc.yaml` 을 만들고 즉시 암호화
4. `sops --decrypt` 로 round-trip 검증

> ⚠️ **부트스트랩 직후 `~/.config/sops/age/keys.txt` 를 1Password 또는 종이 백업에 즉시 저장하세요.**
> 이 키 1개가 모든 cluster secret 의 master key 입니다. 분실 시 모든
> SOPS 파일은 영구히 복호화 불가능합니다.

---

## 일상 운영

| 작업 | 명령 |
|---|---|
| secret 값 조회 | `sops --decrypt k8s/secrets/app-secret.enc.yaml` |
| secret 편집 | `bash k8s/scripts/secrets-edit.sh` |
| 클러스터 배포 | `bash k8s/scripts/deploy-local.sh` (decrypt + apply 자동) |

`secrets-edit.sh` 는 `sops` 의 인터랙티브 편집기를 띄웁니다. 디스크에
평문이 떨어지지 않으며 (mlock 된 임시 파일), 종료 시 자동 재암호화
됩니다.

---

## DB 비밀번호 rotation

```bash
# 1. postgres 에서 비번 변경
kubectl exec -n alpha-trading alpha-pg-postgresql-0 -- \
  psql -U postgres -d alpha_db \
  -c "ALTER USER alpha_user PASSWORD 'NEW_STRONG_PASSWORD'"

# 2. SOPS 파일에 동일 비번 반영
bash k8s/scripts/secrets-edit.sh
# → DATABASE_URL 의 비번을 NEW_STRONG_PASSWORD 로 수정 후 저장

# 3. 재배포 (api/worker 가 새 비번으로 재기동)
bash k8s/scripts/deploy-local.sh
```

`deploy-local.sh` 는 `kubectl rollout restart` 까지 수행하므로 옛
connection pool 을 들고 있던 파드가 강제 종료되고 새 비번으로 재연결
됩니다.

---

## 협업자 추가

1. 협업자가 자기 노트북에서 `age-keygen` 실행 → public key 공유
2. `.sops.yaml` 의 `age:` 줄에 새 recipient 를 콤마로 이어붙이기
3. `sops updatekeys k8s/secrets/*.enc.yaml` (모든 파일을 새 recipient
   set 으로 재암호화)
4. PR 머지 → 협업자가 pull 후 자기 키로 decrypt 가능

---

## DR (노트북 분실)

```bash
# 1Password 백업에서 keys.txt 복구
mkdir -p ~/.config/sops/age
chmod 700 ~/.config/sops/age
# (1Password 에서 keys.txt 내용을 ~/.config/sops/age/keys.txt 로 저장)
chmod 600 ~/.config/sops/age/keys.txt

# 검증 + 재배포
sops --decrypt k8s/secrets/app-secret.enc.yaml | head -5
bash k8s/scripts/deploy-local.sh
```

백업이 없다면: 새 age 키 생성 → 모든 secret 값을 KIS / Bitnami / AWS
등 원천에서 다시 발급 → 새 SOPS 파일 작성. **재발급 비용을 알고 있으므로
백업은 필수입니다.**

---

## 위협 모델 (현행)

| 시나리오 | 영향 | 대응 |
|---|---|---|
| GitHub repo 가 통째로 leak | 평문 노출 없음 (encrypted_regex 로 값만 가려짐) | 추가 조치 불필요 |
| 노트북 도난 + FileVault 잠긴 상태 | age private key 접근 불가 | 추가 조치 불필요 |
| 노트북 도난 + 잠금 해제 상태 | age key 접근 가능 | 1Password 2FA 백업으로 별도 보호 |
| 악의적 협업자 | secret rotation 으로 대응 | 위 rotation 절차 + `sops updatekeys` 로 새 recipient set 적용 |
| age private key 분실 + 백업 없음 | 모든 SOPS 파일 영구 brick | 종이 백업 / 1Password 백업 강제 |

---

## CI 통합 메모 (현재 미적용)

CI 는 secret 이 필요 없는 lint/test 만 돌리므로 SOPS decrypt 를
수행하지 않습니다. 향후 CI 에서 cluster apply 가 필요해지면
GitHub Actions secret 으로 age private key 를 추가하고
`sops --decrypt` 단계를 워크플로우에 넣습니다. 그때까지는
`STRICT=1 bash test/test_secrets_sops.sh` 만 실행하면 충분합니다.

---

## 관련 파일

- `.sops.yaml` — 암호화 규칙 (recipient + 경로 + encrypted_regex)
- `k8s/secrets/app-secret.enc.yaml` — 암호화된 cluster Secret (bootstrap 후 생성)
- `k8s/scripts/secrets-bootstrap.sh` — 최초 1회 + 협업자 추가 시 사용 (멱등)
- `k8s/scripts/secrets-edit.sh` — 안전한 SOPS 파일 편집 wrapper
- `k8s/scripts/deploy-local.sh` — 배포 (decrypt → apply → kustomize → rollout)
- `test/test_secrets_sops.sh` — SOPS 파이프라인 단위 테스트 (10건, merge gate)
