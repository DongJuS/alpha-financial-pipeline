#!/usr/bin/env bash
# scripts/oci/cloudflared_tunnel.sh — Cloudflare Quick Tunnel + Telegram URL 알림
#
# Quick Tunnel로 로컬 포트를 외부에 노출하고,
# 발급된 trycloudflare.com URL을 Telegram으로 전송합니다.
# 서비스 재시작 시 새 URL이 발급되며, 매번 Telegram으로 알림합니다.
#
# 환경변수:
#   CF_TUNNEL_LABEL     — 터널 식별 이름 (기본: default)
#   CF_TUNNEL_PORT      — 터널 대상 포트 (기본: 5173)
#   CF_TUNNEL_AUTH_FILE — 로그인 정보가 담긴 JSON 파일 경로 (선택)
#   CF_TUNNEL_AUTH_KEYS — 쉼표 구분 JSON 키 경로 (예: gateway.auth.token)
#   TELEGRAM_BOT_TOKEN  — Telegram Bot 토큰 (미설정 시 알림 생략)
#   TELEGRAM_CHAT_ID    — Telegram Chat ID
#
# 주의: TUNNEL_NAME, TUNNEL_PORT 등 TUNNEL_ 접두어 변수는
#       cloudflared가 내부적으로 사용하므로 CF_ 접두어를 사용합니다.
#
# 사용 예시:
#   CF_TUNNEL_LABEL=investing CF_TUNNEL_PORT=5173 ./cloudflared_tunnel.sh
#   CF_TUNNEL_LABEL=openclaw  CF_TUNNEL_PORT=3000 ./cloudflared_tunnel.sh
#
set -uo pipefail

LABEL="${CF_TUNNEL_LABEL:-default}"
PORT="${CF_TUNNEL_PORT:-5173}"
AUTH_FILE="${CF_TUNNEL_AUTH_FILE:-}"
AUTH_KEYS="${CF_TUNNEL_AUTH_KEYS:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
TUNNEL_LOG="/tmp/cloudflared-tunnel-${LABEL}.log"

# ── 로그 초기화 ──────────────────────────────────────────────────
: > "$TUNNEL_LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cloudflare Quick Tunnel 시작 (name=${LABEL}, port=${PORT})" >> "$TUNNEL_LOG"

# ── 백그라운드: URL 감지 → Telegram 알림 ──────────────────────────
(
    for _ in $(seq 1 60); do
        sleep 1
        url=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
        if [[ -n "$url" ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Tunnel URL 감지: $url" >> "$TUNNEL_LOG"
            # AUTH_FILE이 있으면 allowedOrigins에 새 URL 자동 등록 + gateway 재시작
            if [[ -n "$AUTH_FILE" && -f "$AUTH_FILE" ]]; then
                sudo python3 -c "
import json, subprocess, os, sys
try:
    with open('$AUTH_FILE') as f:
        cfg = json.load(f)
    origins = cfg.get('gateway',{}).get('controlUi',{}).get('allowedOrigins',[])
    if '$url' not in origins:
        origins.append('$url')
        cfg['gateway']['controlUi']['allowedOrigins'] = origins
        with open('$AUTH_FILE','w') as f:
            json.dump(cfg, f, indent=2)
        os.chown('$AUTH_FILE', 1000, 1000)
        subprocess.run(['docker','compose','-f','/home/ubuntu/openclaw/docker-compose.yml','restart','openclaw-gateway'],
                       capture_output=True, timeout=30)
        print('allowedOrigins updated + gateway restarted')
    else:
        print('origin already allowed')
except Exception as e:
    print(f'WARN: {e}', file=sys.stderr)
" >> "$TUNNEL_LOG" 2>&1
            fi
            # 인증 정보 추출 (AUTH_FILE이 있으면 JSON에서 키 값 읽기)
            auth_info=""
            if [[ -n "$AUTH_FILE" && -f "$AUTH_FILE" && -n "$AUTH_KEYS" ]]; then
                IFS=',' read -ra keys <<< "$AUTH_KEYS"
                for key in "${keys[@]}"; do
                    # jq 없이 python3으로 JSON 키 추출
                    val=$(sudo python3 -c "
import json, sys
try:
    d = json.load(open('$AUTH_FILE'))
    parts = '$key'.split('.')
    for p in parts: d = d[p]
    print(d)
except: pass
" 2>/dev/null)
                    if [[ -n "$val" ]]; then
                        key_name=$(echo "$key" | awk -F. '{print $NF}')
                        auth_info="${auth_info}
${key_name}: ${val}"
                    fi
                done
            fi
            if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
                curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                    -d "chat_id=${TELEGRAM_CHAT_ID}" \
                    --data-urlencode "text=🌐 ${LABEL} Tunnel URL
${url}
포트: ${PORT}${auth_info}
시각: $(date '+%Y-%m-%d %H:%M:%S %Z')" > /dev/null || true
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Telegram 알림 발송 완료" >> "$TUNNEL_LOG"
            else
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Telegram 미설정, 알림 생략" >> "$TUNNEL_LOG"
            fi
            exit 0
        fi
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: 60초 내 Tunnel URL 감지 실패" >> "$TUNNEL_LOG"
) &

# ── 메인 프로세스: cloudflared 실행 (systemd가 이 PID를 추적) ──────
exec cloudflared tunnel --url "http://localhost:${PORT}" >> "$TUNNEL_LOG" 2>&1
