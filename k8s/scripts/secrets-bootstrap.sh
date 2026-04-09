#!/bin/bash
# secrets-bootstrap.sh — SOPS + age 최초 부트스트랩 (멱등)
#
# 동작:
#   1. age 키쌍이 없으면 생성하고 1Password 백업 콜아웃을 띄운다.
#   2. .sops.yaml 의 placeholder recipient 를 실제 public key 로 치환한다.
#   3. .env 의 cluster secret 키들을 골라 k8s/secrets/app-secret.enc.yaml 을
#      만들고 즉시 암호화한다.
#   4. 마지막으로 sops --decrypt 로 round-trip 검증을 한 번 돌린다.
#
# 사용법:
#   bash k8s/scripts/secrets-bootstrap.sh
#
# 운영 가이드: docs/secrets.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
SOPS_CONFIG="$REPO_ROOT/.sops.yaml"
SECRETS_DIR="$REPO_ROOT/k8s/secrets"
ENC_FILE="$SECRETS_DIR/app-secret.enc.yaml"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

# 0. 필수 바이너리 존재 확인
for bin in sops age age-keygen; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: $bin 미설치. 'brew install sops age' 후 재실행하세요." >&2
    exit 1
  fi
done

mkdir -p "$(dirname "$AGE_KEY_FILE")" "$SECRETS_DIR"
chmod 700 "$(dirname "$AGE_KEY_FILE")" 2>/dev/null || true

# 1. age 키
if [ ! -f "$AGE_KEY_FILE" ]; then
  echo "=== age 키쌍 생성 ($AGE_KEY_FILE) ==="
  age-keygen -o "$AGE_KEY_FILE"
  chmod 600 "$AGE_KEY_FILE"
  echo ""
  echo "WARNING: $AGE_KEY_FILE 를 1Password 또는 안전한 백업에 즉시 저장하세요."
  echo "         분실 시 모든 SOPS 파일은 영구히 복호화 불가능합니다."
  echo ""
fi

PUB="$(grep -m1 "public key:" "$AGE_KEY_FILE" | sed 's/.*: //')"
if [ -z "$PUB" ]; then
  echo "ERROR: $AGE_KEY_FILE 에서 public key 를 추출하지 못했습니다." >&2
  exit 1
fi
echo "age recipient: $PUB"

# 2. .sops.yaml placeholder 치환 (최초 1회만, 이후 멱등)
if grep -q 'age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' "$SOPS_CONFIG"; then
  # macOS / GNU sed 호환을 위해 -i.bak 사용 후 백업 파일 즉시 제거
  sed -i.bak "s|age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx|$PUB|" "$SOPS_CONFIG"
  rm -f "$SOPS_CONFIG.bak"
  echo "  $SOPS_CONFIG recipient 업데이트 완료"
else
  echo "  $SOPS_CONFIG recipient 이미 채워짐 (skip)"
fi

# 3. .env → app-secret.enc.yaml (최초 1회만 생성)
if [ ! -f "$ENC_FILE" ]; then
  if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE 없음 — 먼저 .env 를 채우거나 ENC_FILE 을 직접 작성하세요." >&2
    exit 1
  fi

  TMP="$(mktemp)"
  trap 'rm -f "$TMP"' EXIT

  cat > "$TMP" <<'YAML'
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
  namespace: alpha-trading
type: Opaque
stringData:
YAML

  # .env 에서 cluster secret 키만 추출. 빈 값은 skip (kubectl apply 시
  # 의도치 않은 빈 secret value 가 들어가지 않도록).
  for key in JWT_SECRET DATABASE_URL S3_ACCESS_KEY S3_SECRET_KEY \
             KIS_IS_PAPER_TRADING KIS_PAPER_APP_KEY KIS_PAPER_APP_SECRET KIS_PAPER_ACCOUNT_NUMBER \
             KIS_REAL_APP_KEY KIS_REAL_APP_SECRET KIS_REAL_ACCOUNT_NUMBER REAL_TRADING_CONFIRMATION_CODE \
             TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
    # -a 로 binary mode 회피: .env 에 우연히 NUL 등 이 박혀도 텍스트로 취급해서
    # 라인을 정상적으로 뽑아낸다. 뒤이어 control char strip 을 거치므로 안전.
    val="$(grep -aE "^${key}=" "$ENV_FILE" | head -1 | cut -d'=' -f2- || true)"
    # 양 끝의 따옴표 제거
    val="${val%\"}"
    val="${val#\"}"
    val="${val%\'}"
    val="${val#\'}"
    # 방어적 sanitization: control character (CR/LF/탭/ESC/NUL 등) 제거.
    # SOPS 가 'control characters are not allowed' 로 거부하는 사고 방지.
    # secret 값은 원천적으로 printable ASCII 라 손해 없음. (2026-04-08)
    val="$(printf '%s' "$val" | LC_ALL=C tr -d '[:cntrl:]')"
    if [ -z "$val" ]; then
      continue
    fi
    # DATABASE_URL 의 host 가 localhost / 127.0.0.1 이면 k8s 컨텍스트의
    # 서비스 DNS 로 치환한다. .env 는 로컬 개발용이라 localhost 가 박혀 있지만
    # k8s 안에서는 alpha-pg-postgresql 서비스로 가야 한다.
    if [ "$key" = "DATABASE_URL" ]; then
      val="$(printf '%s' "$val" | sed -E 's#@(localhost|127\.0\.0\.1)(:[0-9]+)?/#@alpha-pg-postgresql:5432/#')"
    fi
    # YAML 의 single-quoted scalar 로 출력해 string 타입 강제 (true / 8203915188
    # 같은 값이 bool/int 로 자동 추론되지 않게). single-quote 자체는 두 개로 escape.
    escaped="${val//\'/\'\'}"
    printf "  %s: '%s'\n" "$key" "$escaped" >> "$TMP"
  done

  # sops 의 creation_rules 매칭은 --filename-override 로 가짜 경로를 넘겨 한다
  # (실제 입력 파일 경로는 매칭에 쓰이지 않음). 출력은 별도 임시 파일에 받아
  # mv 로 최종 위치에 옮긴다 (shellcheck SC2094 회피).
  TMP_OUT="$(mktemp)"
  sops --encrypt --config "$SOPS_CONFIG" --input-type yaml --output-type yaml \
       --filename-override "$ENC_FILE" "$TMP" > "$TMP_OUT"
  mv "$TMP_OUT" "$ENC_FILE"
  echo "  $ENC_FILE 생성 완료 (암호화됨)"
else
  echo "  $ENC_FILE 이미 존재 (skip — 갱신은 secrets-edit.sh 로)"
fi

# 4. 검증
if SOPS_AGE_KEY_FILE="$AGE_KEY_FILE" sops --decrypt "$ENC_FILE" > /dev/null; then
  echo "  decrypt 검증 OK"
else
  echo "ERROR: $ENC_FILE decrypt 검증 실패" >&2
  exit 1
fi

echo ""
echo "=== 부트스트랩 완료 ==="
echo "다음 단계: bash k8s/scripts/deploy-local.sh"
