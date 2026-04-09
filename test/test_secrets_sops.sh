#!/bin/bash
# shellcheck disable=SC2329
# (test_*/setup_env/teardown_env/make_fake_repo 는 run_test 의 첫 인자
#  문자열을 통해 간접 호출되어 shellcheck 가 추적하지 못하므로 SC2329 를 끈다.)
# test/test_secrets_sops.sh — SOPS + age 파이프라인 단위 테스트 (14 cases)
#
# 본 테스트는 hermetic: 운영자의 ~/.config/sops/age/keys.txt 와
# k8s/secrets/app-secret.enc.yaml 을 절대 읽지/쓰지 않는다. 모든 케이스가
# mktemp -d 로 만든 임시 디렉토리 안에서 자체 age 키와 .sops.yaml 을 만들어
# round-trip 한다.
#
# 사용법:
#   bash test/test_secrets_sops.sh           # sops/age 미설치면 skip(0)
#   STRICT=1 bash test/test_secrets_sops.sh  # 미설치 시 hard fail (CI 용)
#
# 설계 메모:
# - bats-core 의존을 피하기 위해 plain bash + 함수 형태로 구현. 각 테스트
#   함수는 0/1 을 반환하고 run_test 가 카운터를 갱신한다.
# - 각 테스트는 자기만의 TMP 디렉토리/환경 변수를 setup_env() 로 만들고
#   teardown_env() 에서 정리한다 (케이스 간 격리).
# - 케이스 8/9 는 secrets-bootstrap.sh 를 fake repo 트리에 복사해 실행한다.
#   실제 REPO_ROOT 의 .sops.yaml/k8s/secrets/ 는 절대 건드리지 않는다.
# - 케이스 6/7 은 deploy-local.sh 를 --skip-build 모드로 실행한다.
#   --skip-build 는 docker build 만 건너뛰고 SOPS 검증 단계까지 진행해
#   age key/sops binary 부재로 step [3/6] 에서 exit 1 한다 (kubectl 단계
#   진입 전에 차단되므로 운영 클러스터에 부수 효과 없음).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PASS=0
FAIL=0
FAILED_NAMES=()

color_red()   { printf '\033[0;31m%s\033[0m' "$1"; }
color_green() { printf '\033[0;32m%s\033[0m' "$1"; }
color_yellow(){ printf '\033[0;33m%s\033[0m' "$1"; }

# ── 사전 점검: sops + age 바이너리 ────────────────────────────────────
check_binaries() {
  local missing=()
  for bin in sops age age-keygen; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      missing+=("$bin")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    if [ "${STRICT:-0}" = "1" ]; then
      color_red "FAIL: missing required binaries: ${missing[*]}"
      echo ""
      echo "  STRICT=1 set — install with 'brew install sops age'."
      exit 1
    fi
    color_yellow "SKIP: ${missing[*]} not installed — skipping SOPS unit tests."
    echo ""
    echo "  Install with: brew install sops age"
    echo "  (set STRICT=1 to convert this skip into a hard failure)"
    exit 0
  fi
}

# ── 공통 setup/teardown ─────────────────────────────────────────────
# setup_env: 임시 디렉토리, 임시 age 키, 임시 .sops.yaml, 샘플 평문/암호문 생성
# 호출 후 다음 변수를 export 한다:
#   T_TMPDIR        — 케이스 전용 임시 디렉토리
#   T_AGE_KEY_FILE  — 새로 생성한 age private key 경로
#   T_PUBKEY        — 위 키의 public recipient
#   T_SOPS_CONFIG   — 임시 .sops.yaml (recipient 채워짐)
#   T_PLAIN_FILE    — 샘플 평문 Secret manifest
#   T_ENC_FILE      — 위 파일을 SOPS 로 암호화한 결과
setup_env() {
  T_TMPDIR="$(mktemp -d -t sops_test.XXXXXX)"
  T_AGE_KEY_FILE="$T_TMPDIR/keys.txt"
  T_SOPS_CONFIG="$T_TMPDIR/.sops.yaml"
  T_PLAIN_FILE="$T_TMPDIR/app-secret.plain.yaml"
  T_ENC_FILE="$T_TMPDIR/app-secret.enc.yaml"

  age-keygen -o "$T_AGE_KEY_FILE" >/dev/null 2>&1
  chmod 600 "$T_AGE_KEY_FILE"
  T_PUBKEY="$(grep -m1 'public key:' "$T_AGE_KEY_FILE" | sed 's/.*: //')"

  cat > "$T_SOPS_CONFIG" <<EOF
creation_rules:
  - path_regex: .*\\.enc\\.yaml\$
    encrypted_regex: '^(data|stringData)\$'
    age: $T_PUBKEY
EOF

  cat > "$T_PLAIN_FILE" <<'YAML'
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
  namespace: alpha-trading
type: Opaque
stringData:
  JWT_SECRET: hermetic-test-jwt-secret
  DATABASE_URL: postgresql://alpha_user:hermetic-pass@alpha-pg-postgresql:5432/alpha_db
  S3_ACCESS_KEY: hermetic-s3-key
  S3_SECRET_KEY: hermetic-s3-secret
  KIS_PAPER_APP_KEY: hermetic-kis-app-key
  KIS_PAPER_APP_SECRET: hermetic-kis-app-secret
YAML

  # shellcheck disable=SC2094
  # --filename-override 는 sops 의 creation_rules 매칭용 가짜 경로일 뿐
  # 실제 입출력 경로와 다르므로 read/write 충돌이 없다.
  local enc_tmp="$T_TMPDIR/.enc.tmp"
  SOPS_AGE_KEY_FILE="$T_AGE_KEY_FILE" sops \
    --encrypt \
    --config "$T_SOPS_CONFIG" \
    --input-type yaml --output-type yaml \
    --filename-override "$T_ENC_FILE" \
    "$T_PLAIN_FILE" > "$enc_tmp"
  mv "$enc_tmp" "$T_ENC_FILE"
}

teardown_env() {
  if [ -n "${T_TMPDIR:-}" ] && [ -d "$T_TMPDIR" ]; then
    rm -rf "$T_TMPDIR"
  fi
  unset T_TMPDIR T_AGE_KEY_FILE T_PUBKEY T_SOPS_CONFIG T_PLAIN_FILE T_ENC_FILE
}

# ── 가짜 REPO 생성 (case 8, 9 전용) ─────────────────────────────────
# secrets-bootstrap.sh 는 SCRIPT_DIR 기준 REPO_ROOT 를 계산하므로
# 임시 트리 안에 k8s/scripts/secrets-bootstrap.sh 를 복사해 둔다.
make_fake_repo() {
  local fake="$1"
  mkdir -p "$fake/k8s/scripts" "$fake/k8s/secrets"
  cp "$REPO_ROOT/k8s/scripts/secrets-bootstrap.sh" "$fake/k8s/scripts/"
  chmod +x "$fake/k8s/scripts/secrets-bootstrap.sh"
  # 항상 placeholder 가 들어간 .sops.yaml 을 직접 작성한다.
  # (운영자가 이미 부트스트랩을 돌려 실제 repo 의 .sops.yaml 이 진짜 recipient 로
  #  치환된 상태여도 hermetic 테스트가 영향받지 않도록 — cp 하면 안 됨.)
  cat > "$fake/.sops.yaml" <<'EOF'
creation_rules:
  - path_regex: k8s/secrets/.*\.enc\.yaml$
    encrypted_regex: '^(data|stringData)$'
    age: >-
      age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EOF
}

# ── 테스트 케이스들 ──────────────────────────────────────────────────

# 1. .sops.yaml 의 recipient 가 placeholder 가 아닌 실제 age public key 형식인지
test_sops_config_has_valid_recipient() {
  setup_env
  local rc=0
  # placeholder 문자열 부재
  if grep -q 'age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' "$T_SOPS_CONFIG"; then
    echo "    placeholder still present in $T_SOPS_CONFIG"
    rc=1
  fi
  # age1 + 58 chars 형식
  local r
  r="$(grep -E 'age:' "$T_SOPS_CONFIG" | head -1 | sed -E 's/.*age:[[:space:]]*//')"
  if ! printf '%s' "$r" | grep -Eq '^age1[0-9a-z]{58}$'; then
    echo "    recipient '$r' does not match ^age1[0-9a-z]{58}$"
    rc=1
  fi
  teardown_env
  return "$rc"
}

# 2. 암호화→복호화→재암호화→복호화 round-trip 의 평문이 동일한지
test_app_secret_decrypts_round_trip() {
  setup_env
  local rc=0
  local out1 out2
  out1="$T_TMPDIR/decrypt1.yaml"
  out2="$T_TMPDIR/decrypt2.yaml"
  if ! SOPS_AGE_KEY_FILE="$T_AGE_KEY_FILE" sops --decrypt "$T_ENC_FILE" > "$out1" 2>"$T_TMPDIR/err1"; then
    echo "    first decrypt failed: $(cat "$T_TMPDIR/err1")"
    teardown_env
    return 1
  fi
  # 재암호화 후 다시 복호화
  local re_enc="$T_TMPDIR/re-encrypted.enc.yaml"
  local re_enc_tmp="$T_TMPDIR/re-encrypted.tmp"
  # shellcheck disable=SC2094
  SOPS_AGE_KEY_FILE="$T_AGE_KEY_FILE" sops \
    --encrypt --config "$T_SOPS_CONFIG" \
    --input-type yaml --output-type yaml \
    --filename-override "$re_enc" \
    "$out1" > "$re_enc_tmp"
  mv "$re_enc_tmp" "$re_enc"
  if ! SOPS_AGE_KEY_FILE="$T_AGE_KEY_FILE" sops --decrypt "$re_enc" > "$out2" 2>"$T_TMPDIR/err2"; then
    echo "    second decrypt failed: $(cat "$T_TMPDIR/err2")"
    teardown_env
    return 1
  fi
  if ! diff -q "$out1" "$out2" >/dev/null 2>&1; then
    echo "    round-trip plaintext mismatch"
    diff "$out1" "$out2" | sed 's/^/      /' | head -10
    rc=1
  fi
  teardown_env
  return "$rc"
}

# 3. decrypt 결과의 stringData 에 필수 키가 모두 존재하고 빈 값이 아닌지
test_app_secret_contains_required_keys() {
  setup_env
  local rc=0
  local plain="$T_TMPDIR/decrypted.yaml"
  if ! SOPS_AGE_KEY_FILE="$T_AGE_KEY_FILE" sops --decrypt "$T_ENC_FILE" > "$plain" 2>/dev/null; then
    echo "    decrypt failed"
    teardown_env
    return 1
  fi
  for key in JWT_SECRET DATABASE_URL S3_ACCESS_KEY KIS_PAPER_APP_KEY; do
    # "KEY: value" 형식이고 value 가 비어있지 않은지
    if ! grep -E "^[[:space:]]+${key}:[[:space:]]+[^[:space:]]+" "$plain" >/dev/null; then
      echo "    missing or empty: $key"
      rc=1
    fi
  done
  teardown_env
  return "$rc"
}

# 4. decrypt 결과에 알려진 placeholder 문자열이 포함되어 있지 않은지 (drift 회귀 방지)
test_app_secret_no_placeholder_values() {
  setup_env
  local rc=0
  local plain="$T_TMPDIR/decrypted.yaml"
  SOPS_AGE_KEY_FILE="$T_AGE_KEY_FILE" sops --decrypt "$T_ENC_FILE" > "$plain" 2>/dev/null
  for bad in "change-me" "change-this" "alpha_pass"; do
    if grep -q "$bad" "$plain"; then
      echo "    placeholder found in decrypted output: $bad"
      rc=1
    fi
  done
  teardown_env
  return "$rc"
}

# 5. kubectl kustomize k8s/base/ 가 빌드되고 app-secret 이 출력에 포함되지 않는지
test_kustomize_build_clean_after_secrets_yaml_removed() {
  if ! command -v kubectl >/dev/null 2>&1; then
    echo "    kubectl not installed — cannot validate kustomize build"
    return 1
  fi
  local out err
  out="$(mktemp)"
  err="$(mktemp)"
  if ! kubectl kustomize "$REPO_ROOT/k8s/base/" > "$out" 2>"$err"; then
    echo "    kustomize build failed:"
    sed 's/^/      /' "$err"
    rm -f "$out" "$err"
    return 1
  fi
  local rc=0
  # app-secret 이라는 이름의 Secret 리소스가 만들어지면 안 됨
  # (envFrom 의 secretRef 는 별도의 metadata.name 이 아니라 OK)
  # awk 로 "kind: Secret" 블록의 metadata.name 만 추출.
  local names
  names="$(awk '
    /^---/ { kind=""; name=""; next }
    /^kind:/ { kind=$2 }
    /^metadata:/ { in_meta=1; next }
    in_meta && /^  name:/ { if (kind=="Secret") print $2; in_meta=0 }
    /^[a-zA-Z]/ && !/^kind:/ && !/^metadata:/ { in_meta=0 }
  ' "$out")"
  if echo "$names" | grep -q '^app-secret$'; then
    echo "    'app-secret' Secret should NOT be in kustomize output"
    rc=1
  fi
  if ! echo "$names" | grep -q '^llm-credentials$'; then
    echo "    'llm-credentials' Secret missing from kustomize output (secretGenerator broken?)"
    rc=1
  fi
  rm -f "$out" "$err"
  return "$rc"
}

# 6. age private key 미존재 시 deploy-local.sh 가 step [3/6] 에서 exit 1 하는지
test_deploy_script_aborts_without_age_key() {
  local fake_key="/tmp/no_age_$$_$RANDOM/keys.txt"
  local out err
  out="$(mktemp)"
  err="$(mktemp)"
  # SOPS_AGE_KEY_FILE 을 존재하지 않는 경로로 가리켜 step 3 에서 abort
  set +e
  SOPS_AGE_KEY_FILE="$fake_key" \
    bash "$REPO_ROOT/k8s/scripts/deploy-local.sh" --skip-build > "$out" 2> "$err"
  local code=$?
  set -e
  local rc=0
  if [ "$code" = "0" ]; then
    echo "    expected non-zero exit, got $code"
    rc=1
  fi
  if ! grep -q 'age private key 미존재' "$err"; then
    echo "    expected 'age private key 미존재' on stderr"
    sed 's/^/      err: /' "$err" | head -10
    rc=1
  fi
  rm -f "$out" "$err"
  return "$rc"
}

# 7. sops 바이너리 미설치(=PATH 에서 제외) 시 deploy-local.sh 가 abort 하는지
test_deploy_script_aborts_without_sops_binary() {
  local out err
  out="$(mktemp)"
  err="$(mktemp)"
  # PATH 에서 sops 를 제외 (git/docker 는 /usr/bin 또는 /usr/local/bin 에서 잡힘)
  set +e
  PATH="/usr/bin:/bin:/usr/local/bin" \
    bash "$REPO_ROOT/k8s/scripts/deploy-local.sh" --skip-build > "$out" 2> "$err"
  local code=$?
  set -e
  local rc=0
  if [ "$code" = "0" ]; then
    echo "    expected non-zero exit, got $code"
    rc=1
  fi
  if ! grep -q 'sops binary 미설치' "$err"; then
    echo "    expected 'sops binary 미설치' on stderr"
    sed 's/^/      err: /' "$err" | head -10
    rc=1
  fi
  rm -f "$out" "$err"
  return "$rc"
}

# 8. secrets-bootstrap.sh 가 두 번 연속 실행해도 멱등인지
test_secrets_bootstrap_is_idempotent() {
  local fake
  fake="$(mktemp -d -t fake_repo.XXXXXX)"
  make_fake_repo "$fake"

  # hermetic age key + .env
  local age_key="$fake/age_keys.txt"
  age-keygen -o "$age_key" >/dev/null 2>&1
  chmod 600 "$age_key"
  cat > "$fake/.env" <<'EOF'
JWT_SECRET=hermetic-jwt
DATABASE_URL=postgresql://u:p@host/db
S3_ACCESS_KEY=hermetic-s3
S3_SECRET_KEY=hermetic-s3-secret
KIS_PAPER_APP_KEY=hermetic-kis-app
EOF

  local rc=0
  local first_log second_log
  first_log="$fake/first.log"
  second_log="$fake/second.log"

  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$first_log" 2>&1
  local code1=$?
  set -e
  if [ "$code1" != "0" ]; then
    echo "    first bootstrap run failed (exit $code1):"
    sed 's/^/      /' "$first_log" | head -20
    rm -rf "$fake"
    return 1
  fi

  # snapshot
  local enc_path="$fake/k8s/secrets/app-secret.enc.yaml"
  local enc_hash1 sops_hash1
  enc_hash1="$(shasum "$enc_path" | awk '{print $1}')"
  sops_hash1="$(shasum "$fake/.sops.yaml" | awk '{print $1}')"
  local enc_mtime1
  enc_mtime1="$(stat -f '%m' "$enc_path" 2>/dev/null || stat -c '%Y' "$enc_path")"

  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$second_log" 2>&1
  local code2=$?
  set -e
  if [ "$code2" != "0" ]; then
    echo "    second bootstrap run failed (exit $code2):"
    sed 's/^/      /' "$second_log" | head -20
    rm -rf "$fake"
    return 1
  fi

  local enc_hash2 sops_hash2
  enc_hash2="$(shasum "$enc_path" | awk '{print $1}')"
  sops_hash2="$(shasum "$fake/.sops.yaml" | awk '{print $1}')"
  local enc_mtime2
  enc_mtime2="$(stat -f '%m' "$enc_path" 2>/dev/null || stat -c '%Y' "$enc_path")"

  if [ "$enc_hash1" != "$enc_hash2" ]; then
    echo "    enc file content changed across runs ($enc_hash1 -> $enc_hash2)"
    rc=1
  fi
  if [ "$sops_hash1" != "$sops_hash2" ]; then
    echo "    .sops.yaml changed across runs ($sops_hash1 -> $sops_hash2)"
    rc=1
  fi
  if [ "$enc_mtime1" != "$enc_mtime2" ]; then
    echo "    enc file was rewritten on second run (mtime $enc_mtime1 -> $enc_mtime2)"
    rc=1
  fi

  # 두 번째 실행 로그에 'skip' 표시가 있어야 함
  if ! grep -q 'skip' "$second_log"; then
    echo "    second run did not log 'skip' for any step"
    sed 's/^/      /' "$second_log" | head -20
    rc=1
  fi

  rm -rf "$fake"
  return "$rc"
}

# 9. .env 의 빈 값 키는 ENC 파일에 들어가지 않는지
test_secrets_bootstrap_skips_empty_env_keys() {
  local fake
  fake="$(mktemp -d -t fake_repo.XXXXXX)"
  make_fake_repo "$fake"

  local age_key="$fake/age_keys.txt"
  age-keygen -o "$age_key" >/dev/null 2>&1
  chmod 600 "$age_key"

  # KIS_REAL_APP_KEY 는 빈 값 — ENC 파일에 들어가면 안 됨
  cat > "$fake/.env" <<'EOF'
JWT_SECRET=hermetic-jwt
DATABASE_URL=postgresql://u:p@host/db
S3_ACCESS_KEY=hermetic-s3
S3_SECRET_KEY=hermetic-s3-secret
KIS_PAPER_APP_KEY=hermetic-kis-app
KIS_REAL_APP_KEY=
KIS_REAL_APP_SECRET=
KIS_REAL_ACCOUNT_NUMBER=
EOF

  local rc=0
  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$fake/log" 2>&1
  local code=$?
  set -e
  if [ "$code" != "0" ]; then
    echo "    bootstrap run failed (exit $code):"
    sed 's/^/      /' "$fake/log" | head -20
    rm -rf "$fake"
    return 1
  fi

  local enc_path="$fake/k8s/secrets/app-secret.enc.yaml"
  local plain="$fake/decrypted.yaml"
  SOPS_AGE_KEY_FILE="$age_key" sops --decrypt "$enc_path" > "$plain" 2>/dev/null

  for empty_key in KIS_REAL_APP_KEY KIS_REAL_APP_SECRET KIS_REAL_ACCOUNT_NUMBER; do
    if grep -q "^[[:space:]]*${empty_key}:" "$plain"; then
      echo "    empty .env key '$empty_key' should not appear in decrypted ENC"
      rc=1
    fi
  done
  # 살아있는 키는 잘 들어가야 함 (sanity)
  if ! grep -q '^[[:space:]]*JWT_SECRET:' "$plain"; then
    echo "    JWT_SECRET missing from decrypted ENC (regression)"
    rc=1
  fi

  rm -rf "$fake"
  return "$rc"
}

# 9b. bool/int 처럼 보이는 값은 YAML string 으로 quote 되어야 한다
#     (kubectl Secret stringData 는 string-only — 'true', '8203915188' 같은 값이
#      bool/int 으로 자동 추론되면 'cannot convert int64 to string' 으로 거절됨.
#      2026-04-08 운영자의 첫 deploy 시도에서 KIS_IS_PAPER_TRADING / TELEGRAM_CHAT_ID
#      가 정확히 이 이유로 거절됐음 — 회귀 방지)
test_secrets_bootstrap_quotes_bool_and_int_values() {
  local fake
  fake="$(mktemp -d -t fake_repo.XXXXXX)"
  make_fake_repo "$fake"

  local age_key="$fake/age_keys.txt"
  age-keygen -o "$age_key" >/dev/null 2>&1
  chmod 600 "$age_key"

  cat > "$fake/.env" <<'EOF'
JWT_SECRET=hermetic-jwt
DATABASE_URL=postgresql://u:p@host/db
KIS_IS_PAPER_TRADING=true
TELEGRAM_BOT_TOKEN=hermetic-token
TELEGRAM_CHAT_ID=8203915188
EOF

  local rc=0
  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$fake/log" 2>&1
  local code=$?
  set -e
  if [ "$code" != "0" ]; then
    echo "    bootstrap run failed (exit $code):"
    sed 's/^/      /' "$fake/log" | head -20
    rm -rf "$fake"
    return 1
  fi

  local enc_path="$fake/k8s/secrets/app-secret.enc.yaml"
  local plain="$fake/decrypted.yaml"
  SOPS_AGE_KEY_FILE="$age_key" sops --decrypt "$enc_path" > "$plain" 2>/dev/null

  # 'true' 와 '8203915188' 모두 single-quoted YAML scalar 여야 함.
  # awk 로 KIS_IS_PAPER_TRADING / TELEGRAM_CHAT_ID 의 값을 뽑아 ' 로 시작/끝나는지 검사.
  for key in KIS_IS_PAPER_TRADING TELEGRAM_CHAT_ID; do
    local raw
    raw="$(grep -E "^[[:space:]]*${key}:" "$plain" | sed -E "s/^[[:space:]]*${key}:[[:space:]]*//")"
    if [ -z "$raw" ]; then
      echo "    $key missing from decrypted ENC"
      rc=1
      continue
    fi
    # YAML quoted scalar 여야 한다 (' 또는 " 로 감싸짐)
    if ! printf '%s' "$raw" | grep -Eq "^['\"].*['\"]\$"; then
      echo "    $key value '$raw' not YAML-quoted (would be parsed as bool/int)"
      rc=1
    fi
  done

  # kubectl 이 실제로 받아들이는지 dry-run 으로 검증 (kubectl 있을 때만).
  # client-side dry-run 은 cluster 접속 없이 schema validation 만 한다.
  if command -v kubectl >/dev/null 2>&1; then
    if ! SOPS_AGE_KEY_FILE="$age_key" sops --decrypt "$enc_path" \
         | kubectl apply --dry-run=client -f - >"$fake/dryrun.log" 2>&1; then
      echo "    kubectl --dry-run=client rejected the decrypted secret:"
      sed 's/^/      /' "$fake/dryrun.log" | head -10
      rc=1
    fi
  fi

  rm -rf "$fake"
  return "$rc"
}

# 9c. DATABASE_URL 의 localhost 가 k8s service DNS 로 치환되는지
test_secrets_bootstrap_rewrites_database_url_localhost() {
  local fake
  fake="$(mktemp -d -t fake_repo.XXXXXX)"
  make_fake_repo "$fake"

  local age_key="$fake/age_keys.txt"
  age-keygen -o "$age_key" >/dev/null 2>&1
  chmod 600 "$age_key"

  cat > "$fake/.env" <<'EOF'
JWT_SECRET=hermetic-jwt
DATABASE_URL=postgresql://alpha_user:hermetic-pass@localhost:5432/alpha_db
EOF

  local rc=0
  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$fake/log" 2>&1
  local code=$?
  set -e
  if [ "$code" != "0" ]; then
    echo "    bootstrap run failed (exit $code):"
    sed 's/^/      /' "$fake/log" | head -20
    rm -rf "$fake"
    return 1
  fi

  local plain="$fake/decrypted.yaml"
  SOPS_AGE_KEY_FILE="$age_key" sops --decrypt "$fake/k8s/secrets/app-secret.enc.yaml" > "$plain" 2>/dev/null

  if grep -q '@localhost' "$plain"; then
    echo "    DATABASE_URL still contains @localhost (should be rewritten to alpha-pg-postgresql)"
    grep DATABASE_URL "$plain" | sed 's/^/      /'
    rc=1
  fi
  if ! grep -q '@alpha-pg-postgresql:5432/' "$plain"; then
    echo "    DATABASE_URL does not contain @alpha-pg-postgresql:5432/ after rewrite"
    grep DATABASE_URL "$plain" | sed 's/^/      /'
    rc=1
  fi

  rm -rf "$fake"
  return "$rc"
}

# 9d-pre. secrets-bootstrap.sh 가 .env 의 control character (ESC/CR/탭/NUL 등) 를
#         strip 한 뒤 SOPS 인코딩에 성공하는지. 회귀 가드: 2026-04-08 사고에서
#         사용자가 read -rs 프롬프트에 ESC(0x1b) 를 1바이트로 입력하면서
#         KIS_PAPER_APP_KEY 가 0x1b 로 덮어써졌고, SOPS 가 'control characters
#         are not allowed' 로 폴더링.
test_secrets_bootstrap_strips_control_chars_from_env() {
  local fake
  fake="$(mktemp -d -t fake_repo.XXXXXX)"
  make_fake_repo "$fake"

  local age_key="$fake/age_keys.txt"
  age-keygen -o "$age_key" >/dev/null 2>&1
  chmod 600 "$age_key"

  # .env 에 일부러 control char 를 박는다:
  #   - KIS_PAPER_APP_KEY: ESC(0x1b) + 정상 hex
  #   - KIS_PAPER_APP_SECRET: NUL(0x00) + 정상 hex
  #   - TELEGRAM_BOT_TOKEN: CR(\r) 만 → strip 후 빈 값 → 누락되어야 함
  python3 - "$fake/.env" <<'PY'
import sys
path = sys.argv[1]
lines = [
    "JWT_SECRET=hermetic-jwt\n",
    "DATABASE_URL=postgresql://alpha_user:hermetic@alpha-pg-postgresql:5432/alpha_db\n",
    "KIS_PAPER_APP_KEY=\x1bcleanafterescape123456789012345678\n",
    "KIS_PAPER_APP_SECRET=\x00cleanafternul12345678901234567890\n",
    "KIS_PAPER_ACCOUNT_NUMBER=50000000\n",
    "TELEGRAM_BOT_TOKEN=\r\n",
]
with open(path, "wb") as f:
    f.writelines(line.encode("latin-1") for line in lines)
PY

  local rc=0
  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$fake/log" 2>&1
  local code=$?
  set -e
  if [ "$code" != "0" ]; then
    echo "    bootstrap failed (exit $code) — should have stripped ctrl chars and succeeded:"
    sed 's/^/      /' "$fake/log" | head -30
    rm -rf "$fake"
    return 1
  fi

  local plain="$fake/decrypted.yaml"
  if ! SOPS_AGE_KEY_FILE="$age_key" sops --decrypt "$fake/k8s/secrets/app-secret.enc.yaml" > "$plain" 2>"$fake/dec.log"; then
    echo "    sops --decrypt failed:"
    sed 's/^/      /' "$fake/dec.log"
    rm -rf "$fake"
    return 1
  fi

  # ESC/NUL 가 ENC 에 살아남아 있으면 안 됨 (python 으로 바이트 검사)
  if python3 -c "
import sys
data = open(sys.argv[1], 'rb').read()
bad = [hex(b) for b in set(data) if b < 0x20 and b not in (0x09, 0x0a, 0x0d)]
sys.exit(1 if bad else 0)
" "$plain"; then
    : # ok
  else
    echo "    decrypted yaml still contains control characters"
    rc=1
  fi
  # ESC 뒤의 정상 부분은 보존되어야 함
  if ! grep -q 'cleanafterescape123456789012345678' "$plain"; then
    echo "    KIS_PAPER_APP_KEY clean tail not preserved after strip"
    grep KIS_PAPER_APP_KEY "$plain" | sed 's/^/      /'
    rc=1
  fi
  if ! grep -q 'cleanafternul12345678901234567890' "$plain"; then
    echo "    KIS_PAPER_APP_SECRET clean tail not preserved after strip"
    rc=1
  fi
  # CR 만 있던 키는 strip 후 빈 값 → ENC 에서 누락되어야 함
  if grep -q '^[[:space:]]*TELEGRAM_BOT_TOKEN:' "$plain"; then
    echo "    TELEGRAM_BOT_TOKEN should be skipped when value is only control chars"
    grep TELEGRAM_BOT_TOKEN "$plain" | sed 's/^/      /'
    rc=1
  fi

  rm -rf "$fake"
  return "$rc"
}

# 9d. rotate-secrets.sh --help 가 비대화형으로 종료 0 인지
test_rotate_secrets_help_exits_zero() {
  local out
  out="$(mktemp)"
  set +e
  bash "$REPO_ROOT/k8s/scripts/rotate-secrets.sh" --help > "$out" 2>&1
  local code=$?
  set -e
  local rc=0
  if [ "$code" != "0" ]; then
    echo "    --help should exit 0, got $code"
    sed 's/^/      /' "$out" | head -10
    rc=1
  fi
  if ! grep -q '사용법:' "$out"; then
    echo "    --help output missing usage section"
    rc=1
  fi
  rm -f "$out"
  return "$rc"
}

# 9e. rotate-secrets.sh end-to-end (hermetic — postgres/kubectl/docker 없이)
#
#  검증 hook: ROTATE_NON_INTERACTIVE / ROTATE_SKIP_CONFIRM /
#             ROTATE_SKIP_POSTGRES / ROTATE_SKIP_DEPLOY 환경변수로
#             rotation 전 흐름을 가짜 repo 에서 돌려본다. 운영자는
#             이 변수들을 절대 직접 export 하면 안 됨 (테스트 전용).
#
#  검증 항목:
#    1. exit 0
#    2. .env JWT_SECRET 이 64 hex 로 새로 생성됨 (원본과 다름)
#    3. .env KIS_PAPER_APP_KEY 가 ROTATE_KIS_PAPER_APP_KEY 값으로 갱신됨
#    4. ROTATE_KIS_REAL_APP_KEY 가 빈 문자열일 때 .env 에 추가되지 않음
#    5. ROTATE_SKIP_POSTGRES=1 이면 .env DATABASE_URL 의 비번이 보존됨
#    6. .env.bak.* 백업 파일이 생성됨
#    7. 새 app-secret.enc.yaml 이 만들어지고 sops --decrypt 가 성공함
#    8. decrypted ENC 에 새 KIS 값이 들어 있고 원래 값은 leak 되지 않음
test_rotate_secrets_end_to_end_hermetic() {
  local fake
  fake="$(mktemp -d -t fake_repo.XXXXXX)"
  make_fake_repo "$fake"

  # rotate-secrets.sh 도 가짜 repo 의 k8s/scripts/ 에 복사
  cp "$REPO_ROOT/k8s/scripts/rotate-secrets.sh" "$fake/k8s/scripts/"
  chmod +x "$fake/k8s/scripts/rotate-secrets.sh"

  # hermetic age key
  local age_key="$fake/age_keys.txt"
  age-keygen -o "$age_key" >/dev/null 2>&1
  chmod 600 "$age_key"

  # 초기 .env (rotate 전 값) — 일부러 localhost 그대로 둬서 ROTATE_SKIP_POSTGRES
  # 시 DATABASE_URL 보존을 검증한다
  cat > "$fake/.env" <<'EOF'
JWT_SECRET=hermetic-original-jwt
DATABASE_URL=postgresql://alpha_user:hermetic-original-pass@localhost:5432/alpha_db
S3_ACCESS_KEY=hermetic-s3
S3_SECRET_KEY=hermetic-s3-secret
KIS_PAPER_APP_KEY=hermetic-original-paper-key
KIS_PAPER_APP_SECRET=hermetic-original-paper-secret
KIS_IS_PAPER_TRADING=true
TELEGRAM_BOT_TOKEN=hermetic-original-telegram
TELEGRAM_CHAT_ID=8203915188
EOF

  local rc=0

  # ── 1) 초기 부트스트랩 (rotate 의 .sops.yaml placeholder pre-check 통과용) ──
  set +e
  SOPS_AGE_KEY_FILE="$age_key" ENV_FILE="$fake/.env" \
    bash "$fake/k8s/scripts/secrets-bootstrap.sh" > "$fake/bootstrap1.log" 2>&1
  local bcode=$?
  set -e
  if [ "$bcode" != "0" ]; then
    echo "    initial bootstrap failed (exit $bcode):"
    sed 's/^/      /' "$fake/bootstrap1.log" | head -20
    rm -rf "$fake"
    return 1
  fi

  # 원본 JWT 캡처 (rotate 후 다른지 확인용)
  local original_jwt
  original_jwt="$(grep '^JWT_SECRET=' "$fake/.env" | cut -d= -f2-)"

  # ── 2) rotate 실행 (모든 skip 플래그 + 새 KIS 값 주입) ──
  set +e
  SOPS_AGE_KEY_FILE="$age_key" \
  ROTATE_NON_INTERACTIVE=1 \
  ROTATE_SKIP_CONFIRM=1 \
  ROTATE_SKIP_POSTGRES=1 \
  ROTATE_SKIP_DEPLOY=1 \
  ROTATE_KIS_PAPER_APP_KEY=hermetic-rotated-paper-key \
  ROTATE_KIS_PAPER_APP_SECRET=hermetic-rotated-paper-secret \
  ROTATE_KIS_REAL_APP_KEY='' \
  ROTATE_KIS_REAL_APP_SECRET='' \
  ROTATE_TELEGRAM_BOT_TOKEN=hermetic-rotated-telegram \
    bash "$fake/k8s/scripts/rotate-secrets.sh" > "$fake/rotate.log" 2>&1
  local rcode=$?
  set -e
  if [ "$rcode" != "0" ]; then
    echo "    rotate-secrets.sh failed (exit $rcode):"
    sed 's/^/      /' "$fake/rotate.log" | head -40
    rm -rf "$fake"
    return 1
  fi

  # ── 3) 검증: JWT_SECRET 이 64 hex 로 새로 생성되었고 원본과 다른지 ──
  local new_jwt
  new_jwt="$(grep '^JWT_SECRET=' "$fake/.env" | cut -d= -f2-)"
  if [ "$new_jwt" = "$original_jwt" ]; then
    echo "    JWT_SECRET not rotated (unchanged)"
    rc=1
  fi
  if ! printf '%s' "$new_jwt" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "    new JWT_SECRET is not 64 hex chars: '$new_jwt'"
    rc=1
  fi

  # ── 4) KIS_PAPER_APP_KEY 가 새 값으로 갱신되었는지 ──
  local new_paper
  new_paper="$(grep '^KIS_PAPER_APP_KEY=' "$fake/.env" | cut -d= -f2-)"
  if [ "$new_paper" != "hermetic-rotated-paper-key" ]; then
    echo "    KIS_PAPER_APP_KEY not updated (got '$new_paper')"
    rc=1
  fi

  # ── 5) ROTATE_KIS_REAL_APP_KEY 가 빈 값이면 .env 에 추가되지 않아야 함 ──
  if grep -q '^KIS_REAL_APP_KEY=' "$fake/.env"; then
    echo "    KIS_REAL_APP_KEY should not be added when ROTATE_KIS_REAL_APP_KEY is empty"
    rc=1
  fi

  # ── 6) ROTATE_SKIP_POSTGRES=1 이면 DATABASE_URL 비번 보존 ──
  if ! grep -q '^DATABASE_URL=postgresql://alpha_user:hermetic-original-pass@localhost:5432/alpha_db$' "$fake/.env"; then
    echo "    DATABASE_URL should be unchanged when ROTATE_SKIP_POSTGRES=1"
    grep '^DATABASE_URL=' "$fake/.env" | sed 's/^/      /'
    rc=1
  fi

  # ── 7) .env.bak.* 백업 파일이 생성됨 ──
  if ! ls "$fake"/.env.bak.* >/dev/null 2>&1; then
    echo "    .env.bak.* backup file not created"
    rc=1
  fi

  # ── 8) 새 enc 파일이 존재하고 decrypt 가능한지 ──
  local enc_path="$fake/k8s/secrets/app-secret.enc.yaml"
  if [ ! -f "$enc_path" ]; then
    echo "    new app-secret.enc.yaml not created by rotation"
    rc=1
    rm -rf "$fake"
    return "$rc"
  fi
  local plain="$fake/decrypted.yaml"
  if ! SOPS_AGE_KEY_FILE="$age_key" sops --decrypt "$enc_path" > "$plain" 2>"$fake/decrypt.err"; then
    echo "    decrypt of rotated enc file failed:"
    sed 's/^/      /' "$fake/decrypt.err"
    rm -rf "$fake"
    return 1
  fi

  # ── 9) decrypted ENC 에 새 KIS 값이 있고 원래 값은 leak 되지 않음 ──
  if ! grep -q 'hermetic-rotated-paper-key' "$plain"; then
    echo "    decrypted ENC missing new KIS_PAPER_APP_KEY value"
    rc=1
  fi
  if grep -q 'hermetic-original-paper-key' "$plain"; then
    echo "    decrypted ENC still contains original KIS_PAPER_APP_KEY (leak)"
    rc=1
  fi
  if grep -q 'hermetic-original-jwt' "$plain"; then
    echo "    decrypted ENC still contains original JWT_SECRET (leak)"
    rc=1
  fi

  rm -rf "$fake"
  return "$rc"
}

# 10. 암호화 후에도 metadata/kind/type 은 평문이고 stringData.* 는 ENC[...] 로 가려졌는지
test_sops_yaml_encrypted_regex_only_hits_data_fields() {
  setup_env
  local rc=0
  # 평문이어야 할 메타 필드들
  for plain_field in 'kind: Secret' 'name: app-secret' 'namespace: alpha-trading' 'type: Opaque'; do
    if ! grep -q "$plain_field" "$T_ENC_FILE"; then
      echo "    expected plaintext '$plain_field' missing from encrypted file"
      rc=1
    fi
  done
  # stringData 키 이름은 평문, 값은 ENC[ 로 시작
  for key in JWT_SECRET DATABASE_URL S3_ACCESS_KEY S3_SECRET_KEY KIS_PAPER_APP_KEY; do
    if ! grep -E "^[[:space:]]+${key}:[[:space:]]+ENC\\[" "$T_ENC_FILE" >/dev/null; then
      echo "    stringData.${key} not encrypted (expected ENC[...])"
      rc=1
    fi
  done
  # 평문 값이 새어나가지 않았는지
  if grep -q 'hermetic-test-jwt-secret' "$T_ENC_FILE"; then
    echo "    plaintext JWT value leaked into encrypted file"
    rc=1
  fi
  teardown_env
  return "$rc"
}

# ── 러너 ────────────────────────────────────────────────────────────
run_test() {
  local name="$1"
  local logfile
  logfile="$(mktemp -t sops_test_log.XXXXXX)"
  if "$name" > "$logfile" 2>&1; then
    color_green "  PASS"
    printf ': %s\n' "$name"
    PASS=$((PASS + 1))
  else
    color_red "  FAIL"
    printf ': %s\n' "$name"
    sed 's/^/      /' "$logfile"
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
  rm -f "$logfile"
}

main() {
  check_binaries
  echo "=== SOPS pipeline unit tests (15 cases) ==="
  echo ""
  run_test test_sops_config_has_valid_recipient
  run_test test_app_secret_decrypts_round_trip
  run_test test_app_secret_contains_required_keys
  run_test test_app_secret_no_placeholder_values
  run_test test_kustomize_build_clean_after_secrets_yaml_removed
  run_test test_deploy_script_aborts_without_age_key
  run_test test_deploy_script_aborts_without_sops_binary
  run_test test_secrets_bootstrap_is_idempotent
  run_test test_secrets_bootstrap_skips_empty_env_keys
  run_test test_secrets_bootstrap_quotes_bool_and_int_values
  run_test test_secrets_bootstrap_rewrites_database_url_localhost
  run_test test_secrets_bootstrap_strips_control_chars_from_env
  run_test test_rotate_secrets_help_exits_zero
  run_test test_rotate_secrets_end_to_end_hermetic
  run_test test_sops_yaml_encrypted_regex_only_hits_data_fields
  echo ""
  local total=$((PASS + FAIL))
  if [ "$FAIL" -gt 0 ]; then
    color_red "=== $total tests, $PASS passed, $FAIL failed ==="
    echo ""
    for n in "${FAILED_NAMES[@]}"; do
      echo "  - $n"
    done
    exit 1
  fi
  color_green "=== $total tests, $PASS passed ==="
  echo ""
  exit 0
}

main "$@"
