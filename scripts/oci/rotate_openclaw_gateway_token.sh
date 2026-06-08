#!/usr/bin/env bash
# scripts/oci/rotate_openclaw_gateway_token.sh — OpenClaw 게이트웨이 토큰 일일 회전
#
# 게이트웨이 인증 토큰(openclaw.json 의 gateway.auth.token)을 새로 발급하고,
# 게이트웨이 컨테이너를 재시작한 뒤 새 토큰을 Telegram 으로 통보합니다.
#
# ⚠️ 토큰 정본(source-of-truth)은 컨테이너 내부 /home/node/.openclaw/openclaw.json 이며,
#    이 파일은 컨테이너 node 유저(UID 1000) 소유 + mode 700 디렉토리 안에 있어
#    호스트 cron 유저(ubuntu, UID 1001)가 직접 접근할 수 없다.
#    따라서 파일 읽기/쓰기는 `docker exec -u node` 로 컨테이너 안에서 수행한다.
#
# 사용법:
#   ./scripts/oci/rotate_openclaw_gateway_token.sh        # 실제 회전
#   DRY_RUN=1 ./scripts/oci/rotate_openclaw_gateway_token.sh  # 접근 검증만(부작용 없음)
#
# 환경변수:
#   DRY_RUN             — 1 이면 쓰기/재시작/통보를 생략하고 접근 검증만 수행 (기본: 0)
#   TELEGRAM_BOT_TOKEN  — Telegram Bot 토큰 (미설정 시 알림 생략, skill .env 에서 자동 로드)
#   TELEGRAM_CHAT_ID    — Telegram Chat ID
#
# 크론 등록 (매일 04:00 KST = 전날 19:00 UTC):
#   crontab -e
#   0 4 * * * /home/ubuntu/alpha-financial-pipeline/scripts/oci/rotate_openclaw_gateway_token.sh >> /tmp/gateway_token_rotate.log 2>&1 # gateway-token-rotate
#
set -euo pipefail

CONTAINER="openclaw-openclaw-gateway-1"
CONFIG_IN_CONTAINER="/home/node/.openclaw/openclaw.json"
SKILLS_DIR="/home/ubuntu/openclaw/skills"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── 교체 지점 ① : 자격증명 로드 ──────────────────────────────────
# 현재: skill .env 에서 source. 향후(Infisical): `infisical run --` 또는
#       `infisical secrets get` 으로 대체.
load_telegram_creds() {
    local envfile
    for envfile in "${SKILLS_DIR}/geeknews-oss-brief/.env" \
                   "${SKILLS_DIR}/fintech-job-tracker/.env"; do
        if [[ -f "$envfile" ]]; then
            set -a
            # shellcheck disable=SC1090
            source "$envfile"
            set +a
            break
        fi
    done
}

# ── Telegram 전송 (자격증명/메시지는 env 로 전달 → ps 노출 방지) ──
send_telegram() {
    local msg="$1"
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        log "WARN: Telegram 자격증명 미설정 — 알림 생략"
        return 0
    fi
    TG_TOKEN="$TELEGRAM_BOT_TOKEN" TG_CHAT="$TELEGRAM_CHAT_ID" TG_MSG="$msg" python3 <<'PYEOF'
import json, os, urllib.request
token = os.environ["TG_TOKEN"]; chat = os.environ["TG_CHAT"]; msg = os.environ["TG_MSG"]
data = json.dumps({"chat_id": chat, "text": msg}).encode()
req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=data, headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        print("Telegram 전송 OK")
except Exception as e:
    print(f"Telegram 전송 실패: {e}")
PYEOF
}

# ── 컨테이너 내부에서 토큰 읽기/쓰기 (node 유저, UID 1000) ─────────
read_token() {
    docker exec -u node "$CONTAINER" python3 -c '
import json, sys
d = json.load(open("'"$CONFIG_IN_CONTAINER"'"))
sys.stdout.write(d.get("gateway", {}).get("auth", {}).get("token", ""))
'
}

write_token() {
    docker exec -e NEW_TOKEN="$1" -u node "$CONTAINER" python3 -c '
import os, json
p = "'"$CONFIG_IN_CONTAINER"'"
t = os.environ["NEW_TOKEN"]
d = json.load(open(p))
d.setdefault("gateway", {}).setdefault("auth", {})["token"] = t
with open(p, "w") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
    f.write("\n")
'
}

# ── 재시작 후 healthy 대기 ───────────────────────────────────────
wait_healthy() {
    local _ status
    for _ in $(seq 1 20); do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo unknown)"
        [[ "$status" == "healthy" ]] && return 0
        sleep 3
    done
    return 1
}

# ── 교체 지점 ② : 새 토큰 통보 ───────────────────────────────────
# 현재: Telegram 으로 새 토큰 전송. 향후(Infisical):
#       `infisical secrets set OPENCLAW_GATEWAY_TOKEN=...` 로 Infisical 을 정본 기록화.
publish_new_token() {
    local tok="$1"
    send_telegram "🔑 OpenClaw Gateway 토큰 갱신
$(date '+%Y-%m-%d %H:%M KST')

새 토큰:
${tok}

Control UI에 붙여넣기 하세요."
}

# ── 메인 ─────────────────────────────────────────────────────────
log "=== OpenClaw Gateway 토큰 회전 시작 (DRY_RUN=${DRY_RUN}) ==="
load_telegram_creds

# 1. 선행 접근 검증 — 실패 시 조용히 죽지 않고 알림 후 종료
CURRENT_TOKEN="$(read_token 2>/dev/null || true)"
if [[ -z "$CURRENT_TOKEN" ]]; then
    log "ERROR: 게이트웨이 컨테이너에서 토큰을 읽지 못함 (컨테이너 down 또는 접근 실패)"
    send_telegram "🔴 OpenClaw 토큰 회전 실패
시각: $(date '+%Y-%m-%d %H:%M KST')
원인: 게이트웨이 컨테이너 접근 불가 (${CONTAINER})"
    exit 1
fi
log "접근 OK — 현재 토큰 길이 ${#CURRENT_TOKEN} (...${CURRENT_TOKEN: -8})"

# 2. 새 토큰 생성
NEW_TOKEN="$(openssl rand -hex 24)"

# 3. DRY_RUN 이면 여기서 종료 (토큰 변경 없음)
if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN: 쓰기/재시작/통보 생략 — 접근 검증만 수행, 토큰 변경 없음"
    log "=== 완료 (DRY_RUN) ==="
    exit 0
fi

# 4. 쓰기 + 재검증 (검증 실패 시 재시작 안 함)
write_token "$NEW_TOKEN"
VERIFY_TOKEN="$(read_token 2>/dev/null || true)"
if [[ "$VERIFY_TOKEN" != "$NEW_TOKEN" ]]; then
    log "ERROR: 토큰 쓰기 검증 실패 — 재시작 중단"
    send_telegram "🔴 OpenClaw 토큰 회전 실패
시각: $(date '+%Y-%m-%d %H:%M KST')
원인: json 쓰기 검증 불일치 (재시작 안 함)"
    exit 1
fi
log "토큰 쓰기 완료: ...${NEW_TOKEN: -8}"

# 5. 게이트웨이 재시작
if docker restart "$CONTAINER" >/dev/null 2>&1; then
    log "게이트웨이 재시작됨"
else
    log "WARN: 게이트웨이 재시작 실패"
fi

# 6. 재시작 후 검증 (healthy + 토큰 유지 확인)
if wait_healthy; then
    log "게이트웨이 healthy 복귀"
else
    log "WARN: 게이트웨이 healthy 확인 실패 (타임아웃)"
fi

POST_TOKEN="$(read_token 2>/dev/null || true)"
if [[ "$POST_TOKEN" != "$NEW_TOKEN" ]]; then
    log "WARN: 재시작 후 토큰이 새 값과 불일치 — openclaw 가 config 를 되돌렸을 수 있음"
    send_telegram "⚠️ OpenClaw 토큰 회전 경고
재시작 후 토큰이 새 값과 불일치. 수동 확인 필요."
fi

# 7. 새 토큰 통보
publish_new_token "$NEW_TOKEN"
log "=== 완료 ==="
