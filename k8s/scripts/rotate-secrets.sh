#!/bin/bash
# rotate-secrets.sh — leak 사고 후 한 번에 secret rotate + 재부트스트랩 + 재배포
#
# 동작 (순서):
#   0. 사전 검증 (sops/age/kubectl/openssl/python3/postgres pod/.env/branch)
#   1. .env 백업 (.env.bak.YYYYMMDDHHMMSS, chmod 600)
#   2. 새 KIS PAPER 키 입력 (Enter 시 현재값 유지)
#   3. 새 KIS REAL 키 입력 (Enter 시 현재값 유지)
#   4. 새 Telegram BOT TOKEN 입력 (Enter 시 현재값 유지)
#   5. JWT_SECRET 자동 재생성 (openssl rand -hex 32) — 강제
#   6. postgres alpha_user 비밀번호 재생성 + ALTER USER + 검증 — 강제
#   7. .env 원자적 업데이트 (temp → mv)
#   8. 기존 k8s/secrets/app-secret.enc.yaml 삭제
#   9. secrets-bootstrap.sh 실행 (새 .env → 새 암호화 파일)
#  10. deploy-local.sh 실행 (decrypt + apply + rollout)
#  11. api pod 검증 (Running + asyncpg pool 초기화 로그)
#  12. 최종 요약 (값 출력 없음 — 상태만)
#
# 사용법:
#   bash k8s/scripts/rotate-secrets.sh             # 실제 실행 (interactive)
#   bash k8s/scripts/rotate-secrets.sh --dry-run   # 사전 검증 + 실행 계획만 출력
#   bash k8s/scripts/rotate-secrets.sh --help      # 사용법 출력
#
# 보안 주의:
#   - 모든 secret 입력은 'read -s' 로 echo 차단.
#   - 어떠한 secret 값도 stdout/stderr 에 출력하지 않는다 (상태 메시지만).
#   - .env.bak.* 는 chmod 600. rotate 후 사용자가 직접 검수+삭제 권장.
#   - 이 스크립트는 절대 .env / 암호화 파일을 cat 하지 않는다.

set -euo pipefail

# ── 옵션 파싱 ────────────────────────────────────────────────────────
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --help|-h)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown arg '$arg' (try --help)" >&2
      exit 2
      ;;
  esac
done

# ── 비대화형 / 검증 hook 환경변수 ───────────────────────────────────
# test/test_secrets_sops.sh 의 hermetic 단위 테스트가 실제 postgres/kubectl/docker
# 없이 rotation 흐름 전체를 end-to-end 로 검증할 때 사용한다. 운영자는 이
# 변수들을 절대 직접 export 하지 말 것 (secret 입력이 컨텍스트에 노출됨).
#   ROTATE_NON_INTERACTIVE=1  → KIS/Telegram 입력을 ROTATE_* 환경변수에서 읽음
#   ROTATE_SKIP_CONFIRM=1     → 'yes' 확인 프롬프트 스킵
#   ROTATE_SKIP_POSTGRES=1    → postgres pod 사전검증 + ALTER USER 스킵
#                                (DATABASE_URL 의 비번은 그대로 유지)
#   ROTATE_SKIP_DEPLOY=1      → deploy-local.sh 호출 + api pod 검증 스킵
ROTATE_NON_INTERACTIVE="${ROTATE_NON_INTERACTIVE:-0}"
ROTATE_SKIP_CONFIRM="${ROTATE_SKIP_CONFIRM:-0}"
ROTATE_SKIP_POSTGRES="${ROTATE_SKIP_POSTGRES:-0}"
ROTATE_SKIP_DEPLOY="${ROTATE_SKIP_DEPLOY:-0}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENC_FILE="$REPO_ROOT/k8s/secrets/app-secret.enc.yaml"
NAMESPACE="alpha-trading"

cd "$REPO_ROOT"

color_red()    { printf '\033[0;31m%s\033[0m' "$1"; }
color_green()  { printf '\033[0;32m%s\033[0m' "$1"; }
color_yellow() { printf '\033[0;33m%s\033[0m' "$1"; }
say()          { printf '%s %s\n' "$(color_green '==>')" "$1"; }
warn()         { printf '%s %s\n' "$(color_yellow 'WARN:')" "$1"; }
fail()         { printf '%s %s\n' "$(color_red 'ERROR:')" "$1" >&2; exit 1; }

# ── 0. 사전 검증 ────────────────────────────────────────────────────
say "[0/11] 사전 검증"

REQUIRED_BINS=(sops age age-keygen openssl python3)
if [ "$ROTATE_SKIP_POSTGRES" != "1" ] || [ "$ROTATE_SKIP_DEPLOY" != "1" ]; then
  REQUIRED_BINS+=(kubectl)
fi
for bin in "${REQUIRED_BINS[@]}"; do
  command -v "$bin" >/dev/null 2>&1 || fail "$bin 미설치 ('brew install sops age kubectl openssl' 후 재시도)"
done
[ -f "$ENV_FILE" ] || fail "$ENV_FILE 가 없습니다"
[ -f "$REPO_ROOT/.sops.yaml" ] || fail ".sops.yaml 가 없습니다 — 먼저 secrets-bootstrap.sh 한 번 돌렸는지 확인"
[ -x "$SCRIPT_DIR/secrets-bootstrap.sh" ] || fail "$SCRIPT_DIR/secrets-bootstrap.sh 미존재 또는 실행 권한 없음"
if [ "$ROTATE_SKIP_DEPLOY" != "1" ]; then
  [ -x "$SCRIPT_DIR/deploy-local.sh" ] || fail "$SCRIPT_DIR/deploy-local.sh 미존재 또는 실행 권한 없음"
fi

# postgres pod 존재 + 살아있음 확인 (이름은 동적으로 찾는다)
PG_POD=""
PG_SUPER_PW=""
if [ "$ROTATE_SKIP_POSTGRES" = "1" ]; then
  say "  postgres 사전 검증 스킵 (ROTATE_SKIP_POSTGRES=1)"
else
  PG_POD="$(kubectl get pod -n "$NAMESPACE" -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [ -z "$PG_POD" ]; then
    PG_POD="$(kubectl get pod -n "$NAMESPACE" -o name 2>/dev/null | grep -E 'postgresql|postgres' | head -1 | sed 's|pod/||' || true)"
  fi
  [ -n "$PG_POD" ] || fail "namespace $NAMESPACE 에서 postgres pod 를 찾지 못했습니다"
  PG_PHASE="$(kubectl get pod "$PG_POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  [ "$PG_PHASE" = "Running" ] || fail "postgres pod ($PG_POD) 가 Running 상태가 아닙니다 (현재: $PG_PHASE)"
  say "  postgres pod: $PG_POD ($PG_PHASE)"

  # Bitnami postgresql 차트는 postgres 슈퍼유저에게 비번을 강제한다.
  # ALTER USER 를 실행하려면 secret 에서 superuser 비번을 읽어 PGPASSWORD 로 넘겨야 함.
  PG_SUPER_PW="$(kubectl get secret -n "$NAMESPACE" alpha-pg-postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d 2>/dev/null || true)"
  [ -n "$PG_SUPER_PW" ] || fail "postgres superuser 비번을 secret 에서 찾지 못함 (alpha-pg-postgresql/postgres-password)"
fi

# .sops.yaml 의 recipient 가 placeholder 가 아닌지 확인
if grep -q 'age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' "$REPO_ROOT/.sops.yaml"; then
  fail ".sops.yaml 가 placeholder 상태입니다 — 먼저 'bash k8s/scripts/secrets-bootstrap.sh' 로 age 키 부트스트랩을 끝내야 합니다"
fi

if [ "$DRY_RUN" = true ]; then
  say "[DRY-RUN] 사전 검증 통과"
  cat <<EOF

  실행 계획:
    1. $ENV_FILE 백업 (chmod 600)
    2. KIS PAPER / KIS REAL / Telegram 새 값 입력 (선택적)
    3. JWT_SECRET 재생성 (강제)
    4. postgres alpha_user 비밀번호 재생성 + ALTER USER (강제)
    5. .env 원자적 업데이트
    6. $ENC_FILE 삭제
    7. secrets-bootstrap.sh 실행
    8. deploy-local.sh 실행
    9. api pod Running + DB 연결 검증

  실제 실행은 --dry-run 없이 다시 호출하세요.
EOF
  exit 0
fi

if [ "$ROTATE_SKIP_CONFIRM" != "1" ]; then
  echo ""
  warn "이 스크립트는 다음을 강제로 변경합니다:"
  echo "  - JWT_SECRET (재생성)"
  echo "  - postgres alpha_user 비밀번호 (ALTER USER + .env 동기화)"
  echo "  - 입력한 KIS / Telegram 키 (사용자가 Enter 안 친 항목)"
  echo ""
  printf "계속 진행할까요? [yes 입력 시 진행, 그 외 중단]: "
  read -r CONFIRM
  [ "$CONFIRM" = "yes" ] || fail "사용자가 중단했습니다"
fi

# ── 1. .env 백업 ────────────────────────────────────────────────────
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
BACKUP_FILE="$ENV_FILE.bak.$TIMESTAMP"
cp "$ENV_FILE" "$BACKUP_FILE"
chmod 600 "$BACKUP_FILE"
say "[1/11] .env 백업: $BACKUP_FILE (chmod 600)"

# ── 2-4. KIS / Telegram 새 값 수집 ─────────────────────────────────
if [ "$ROTATE_NON_INTERACTIVE" = "1" ]; then
  say "[2/11] KIS PAPER 키 (ROTATE_KIS_PAPER_* 환경변수에서 읽음)"
  KIS_PAPER_APP_KEY_NEW="${ROTATE_KIS_PAPER_APP_KEY:-}"
  KIS_PAPER_APP_SECRET_NEW="${ROTATE_KIS_PAPER_APP_SECRET:-}"

  say "[3/11] KIS REAL 키 (ROTATE_KIS_REAL_* 환경변수에서 읽음)"
  KIS_REAL_APP_KEY_NEW="${ROTATE_KIS_REAL_APP_KEY:-}"
  KIS_REAL_APP_SECRET_NEW="${ROTATE_KIS_REAL_APP_SECRET:-}"

  say "[4/11] Telegram BOT TOKEN (ROTATE_TELEGRAM_BOT_TOKEN 환경변수에서 읽음)"
  TELEGRAM_BOT_TOKEN_NEW="${ROTATE_TELEGRAM_BOT_TOKEN:-}"
else
  say "[2/11] KIS PAPER 키 입력 (Enter 시 현재값 유지)"
  echo "  → KIS Developers 포털 → 모의투자 앱 → 키 재발급 후 붙여넣기"
  printf "  KIS_PAPER_APP_KEY     : "
  read -rs KIS_PAPER_APP_KEY_NEW; echo
  printf "  KIS_PAPER_APP_SECRET  : "
  read -rs KIS_PAPER_APP_SECRET_NEW; echo

  say "[3/11] KIS REAL 키 입력 (Enter 시 현재값 유지)"
  echo "  → KIS Developers 포털 → 실거래 앱 → 키 재발급 후 붙여넣기"
  printf "  KIS_REAL_APP_KEY      : "
  read -rs KIS_REAL_APP_KEY_NEW; echo
  printf "  KIS_REAL_APP_SECRET   : "
  read -rs KIS_REAL_APP_SECRET_NEW; echo

  say "[4/11] Telegram BOT TOKEN 입력 (Enter 시 현재값 유지)"
  echo "  → @BotFather → /revoke → /newtoken → 봇 선택 후 붙여넣기"
  printf "  TELEGRAM_BOT_TOKEN    : "
  read -rs TELEGRAM_BOT_TOKEN_NEW; echo

  # 입력에서 control character (ESC/CR/탭/NUL 등) 제거.
  # 사고 사례: 사용자가 'Enter 만 쳤다' 고 인식했지만 실제로는 화살표/ESC 키가
  # 한 번 눌려 0x1b 1바이트가 입력값으로 잡혔고, Python rewriter 가 "비어있지
  # 않음" 으로 판단해 .env 의 원래 값을 0x1b 로 덮어써 SOPS YAML 인코딩 단계
  # ('control characters are not allowed') 에서 사고 발생. (2026-04-08)
  for var in KIS_PAPER_APP_KEY_NEW KIS_PAPER_APP_SECRET_NEW \
             KIS_REAL_APP_KEY_NEW KIS_REAL_APP_SECRET_NEW \
             TELEGRAM_BOT_TOKEN_NEW; do
    cleaned="$(printf '%s' "${!var}" | LC_ALL=C tr -d '[:cntrl:]')"
    printf -v "$var" '%s' "$cleaned"
  done
fi

# ── 5. JWT_SECRET 재생성 ───────────────────────────────────────────
say "[5/11] JWT_SECRET 재생성"
JWT_SECRET_NEW="$(openssl rand -hex 32)"
echo "  ✓ 새 JWT_SECRET 생성 (값은 출력되지 않음)"

# ── 6. postgres 비밀번호 재생성 + ALTER USER ──────────────────────
PG_PW_NEW=""
if [ "$ROTATE_SKIP_POSTGRES" = "1" ]; then
  say "[6/11] postgres ALTER USER 스킵 (ROTATE_SKIP_POSTGRES=1)"
  echo "  → DATABASE_URL 의 비번은 변경되지 않습니다"
else
  say "[6/11] postgres alpha_user 비밀번호 재생성 + ALTER USER"
  PG_PW_NEW="$(openssl rand -hex 24)"
  echo "  새 비번 생성. ALTER USER 실행..."
  ALTER_ERR="$(kubectl exec -n "$NAMESPACE" "$PG_POD" -- \
       env "PGPASSWORD=$PG_SUPER_PW" psql -U postgres -d alpha_db -v ON_ERROR_STOP=1 \
       -c "ALTER USER alpha_user PASSWORD '$PG_PW_NEW'" 2>&1 >/dev/null)" || {
    unset PG_PW_NEW JWT_SECRET_NEW KIS_PAPER_APP_KEY_NEW KIS_PAPER_APP_SECRET_NEW \
          KIS_REAL_APP_KEY_NEW KIS_REAL_APP_SECRET_NEW TELEGRAM_BOT_TOKEN_NEW PG_SUPER_PW
    echo "  ── psql stderr ──" >&2
    printf '%s\n' "$ALTER_ERR" | sed 's/^/    /' >&2
    fail "ALTER USER 실패. 원래 .env 그대로. 백업: $BACKUP_FILE"
  }

  # 새 비번이 실제로 통하는지 검증
  VERIFY_ERR="$(kubectl exec -n "$NAMESPACE" "$PG_POD" -- \
       env "PGPASSWORD=$PG_PW_NEW" psql -h localhost -U alpha_user -d alpha_db \
       -v ON_ERROR_STOP=1 -c "SELECT 1" 2>&1 >/dev/null)" || {
    unset PG_PW_NEW JWT_SECRET_NEW KIS_PAPER_APP_KEY_NEW KIS_PAPER_APP_SECRET_NEW \
          KIS_REAL_APP_KEY_NEW KIS_REAL_APP_SECRET_NEW TELEGRAM_BOT_TOKEN_NEW PG_SUPER_PW
    echo "  ── psql stderr ──" >&2
    printf '%s\n' "$VERIFY_ERR" | sed 's/^/    /' >&2
    fail "ALTER USER 후 새 비번 검증 실패. 수동 복구 필요. 백업: $BACKUP_FILE"
  }
  unset PG_SUPER_PW
  echo "  ✓ ALTER USER 성공 + 새 비번 검증 OK"
fi

# ── 7. .env 원자적 업데이트 ────────────────────────────────────────
say "[7/11] .env 원자적 업데이트"
# python3 로 안전하게 in-place rewrite (sed -i 는 macOS/Linux 차이 있음)
KIS_PAPER_APP_KEY_NEW="$KIS_PAPER_APP_KEY_NEW" \
KIS_PAPER_APP_SECRET_NEW="$KIS_PAPER_APP_SECRET_NEW" \
KIS_REAL_APP_KEY_NEW="$KIS_REAL_APP_KEY_NEW" \
KIS_REAL_APP_SECRET_NEW="$KIS_REAL_APP_SECRET_NEW" \
TELEGRAM_BOT_TOKEN_NEW="$TELEGRAM_BOT_TOKEN_NEW" \
JWT_SECRET_NEW="$JWT_SECRET_NEW" \
PG_PW_NEW="$PG_PW_NEW" \
ENV_FILE="$ENV_FILE" \
python3 - <<'PY'
import os
import re
import sys
import tempfile

env_path = os.environ["ENV_FILE"]

# 빈 문자열이면 "Enter 친 것" → 변경 없음
updates = {
    "KIS_PAPER_APP_KEY":    os.environ["KIS_PAPER_APP_KEY_NEW"],
    "KIS_PAPER_APP_SECRET": os.environ["KIS_PAPER_APP_SECRET_NEW"],
    "KIS_REAL_APP_KEY":     os.environ["KIS_REAL_APP_KEY_NEW"],
    "KIS_REAL_APP_SECRET":  os.environ["KIS_REAL_APP_SECRET_NEW"],
    "TELEGRAM_BOT_TOKEN":   os.environ["TELEGRAM_BOT_TOKEN_NEW"],
    # JWT/PG 는 항상 강제
    "JWT_SECRET":           os.environ["JWT_SECRET_NEW"],
}
pg_pw_new = os.environ["PG_PW_NEW"]

with open(env_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# DATABASE_URL 의 비번만 교체 (host/port/db 는 보존)
db_url_re = re.compile(r"^(DATABASE_URL=postgresql://[^:]+:)[^@]*(@.*)$")

seen = set()
new_lines = []
for line in lines:
    stripped = line.rstrip("\n")
    matched = False
    for key, val in updates.items():
        if val == "":
            continue  # Enter — 유지
        if stripped.startswith(f"{key}="):
            new_lines.append(f"{key}={val}\n")
            seen.add(key)
            matched = True
            break
    if matched:
        continue
    if pg_pw_new:
        m = db_url_re.match(stripped)
        if m:
            new_lines.append(f"{m.group(1)}{pg_pw_new}{m.group(2)}\n")
            seen.add("DATABASE_URL")
            continue
    new_lines.append(line)

# 원래 .env 에 없던 키는 끝에 append
for key, val in updates.items():
    if val and key not in seen:
        new_lines.append(f"{key}={val}\n")

# 원자적 쓰기
fd, tmp_path = tempfile.mkstemp(
    prefix=".env.tmp.", dir=os.path.dirname(env_path) or ".",
)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, env_path)
except Exception:
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    raise

# 갱신된 항목 (상태만, 값 출력 X)
print("  ✓ .env updated:")
for k in sorted(seen):
    print(f"    - {k}")
PY

# 메모리에서 비밀 즉시 제거
unset PG_PW_NEW JWT_SECRET_NEW KIS_PAPER_APP_KEY_NEW KIS_PAPER_APP_SECRET_NEW \
      KIS_REAL_APP_KEY_NEW KIS_REAL_APP_SECRET_NEW TELEGRAM_BOT_TOKEN_NEW

# ── 8. 기존 암호화 파일 삭제 ───────────────────────────────────────
say "[8/11] 기존 암호화 파일 삭제"
if [ -f "$ENC_FILE" ]; then
  rm "$ENC_FILE"
  echo "  ✓ $ENC_FILE 삭제"
else
  echo "  (이미 없음)"
fi

# ── 9. secrets-bootstrap.sh 실행 ──────────────────────────────────
say "[9/11] secrets-bootstrap.sh 실행"
bash "$SCRIPT_DIR/secrets-bootstrap.sh"

# ── 10. deploy-local.sh 실행 ──────────────────────────────────────
if [ "$ROTATE_SKIP_DEPLOY" = "1" ]; then
  say "[10/11] deploy-local.sh 스킵 (ROTATE_SKIP_DEPLOY=1)"
else
  say "[10/11] deploy-local.sh 실행"
  bash "$SCRIPT_DIR/deploy-local.sh"
fi

# ── 11. api pod 검증 ──────────────────────────────────────────────
if [ "$ROTATE_SKIP_DEPLOY" = "1" ]; then
  say "[11/11] api pod 검증 스킵 (ROTATE_SKIP_DEPLOY=1)"
else
  say "[11/11] api pod 검증"
  sleep 5
  if ! kubectl rollout status deployment/api -n "$NAMESPACE" --timeout=180s; then
    warn "api rollout 미완료 — 'kubectl logs deploy/api -n $NAMESPACE --tail=50' 로 확인하세요"
    exit 1
  fi
  echo ""
  echo "── api pod 최근 로그 (5줄) ──"
  kubectl logs deployment/api -n "$NAMESPACE" --tail=5 2>/dev/null | sed 's/^/  /' || true
  echo ""

  # DB 연결 에러 검출
  if kubectl logs deployment/api -n "$NAMESPACE" --tail=200 2>/dev/null \
     | grep -qiE 'InvalidPasswordError|password authentication failed'; then
    fail "api 로그에 InvalidPasswordError 가 여전히 보입니다 — 수동 확인 필요"
  fi
fi

# ── 최종 요약 ─────────────────────────────────────────────────────
echo ""
say "✅ rotation + 재배포 완료"
cat <<EOF

다음 작업 (사용자 직접):
  1. 터미널 scrollback 정리: clear && printf '\\033[3J'
  2. 백업 파일 검수 후 삭제 (이전 leak 본 포함):
     ls -lh $BACKUP_FILE
     # 정상이면: rm $BACKUP_FILE
  3. PR #104 에 새 .sops.yaml + app-secret.enc.yaml 커밋:
     git add .sops.yaml k8s/secrets/app-secret.enc.yaml
     git commit -m "chore(secrets): rotate + bootstrap after leak incident"
     # push 는 .github/GIT_PUSH.md 절차

주의: .env 와 .env.bak.* 는 .gitignore 되어 있어 git 에 올라가지 않습니다.
      .sops.yaml 의 'age1...' recipient 는 public key 라 rotation 대상 아닙니다.
EOF
