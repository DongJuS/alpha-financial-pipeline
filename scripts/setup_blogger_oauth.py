#!/usr/bin/env python3
"""
scripts/setup_blogger_oauth.py — Google Blogger OAuth 2.0 초기 설정

이 스크립트는 1회만 실행하면 됩니다.
브라우저에서 Google 계정 인증 후 refresh_token을 자동으로 .env에 기록합니다.

사전 준비:
  1. https://console.cloud.google.com/ 에서 프로젝트 생성
  2. Blogger API v3 활성화
  3. OAuth 2.0 클라이언트 ID 생성 (유형: 데스크톱 앱)
  4. .env에 BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET 설정

사용법:
    python scripts/setup_blogger_oauth.py
"""

from __future__ import annotations

import http.server
import re
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import httpx  # noqa: E402

REDIRECT_PORT = 8085
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"

# .env에서 클라이언트 자격 증명 읽기
import os  # noqa: E402

CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET", "")


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """OAuth 콜백을 처리하는 간단한 HTTP 핸들러."""

    auth_code: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>OK!</h2>"
                b"<p>Google Blogger OAuth completed. You can close this tab.</p>"
                b"</body></html>"
            )
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>Error: {error}</h2></body></html>".encode())

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress noisy logs


def _update_env_file(key: str, value: str) -> None:
    """`.env` 파일에 key=value를 추가하거나 업데이트합니다."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    content = env_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(f"{key}={value}", content)
    else:
        content = content.rstrip("\n") + f"\n{key}={value}\n"
    env_path.write_text(content, encoding="utf-8")


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("BLOGGER_CLIENT_ID와 BLOGGER_CLIENT_SECRET을 .env에 먼저 설정하세요.")
        print("Google Cloud Console → API 및 서비스 → 사용자 인증 정보에서 생성합니다.")
        sys.exit(1)

    # 1. 인증 URL 생성
    auth_params = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": BLOGGER_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })
    auth_url = f"{GOOGLE_AUTH_URL}?{auth_params}"

    # 2. 로컬 서버 시작
    server = http.server.HTTPServer(("", REDIRECT_PORT), _OAuthCallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    # 3. 브라우저 열기
    print(f"\n브라우저에서 Google 계정 인증을 진행합니다...")
    print(f"자동으로 열리지 않으면 아래 URL을 직접 열어주세요:\n")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)

    # 4. 콜백 대기
    thread.join(timeout=120)
    server.server_close()

    auth_code = _OAuthCallbackHandler.auth_code
    if not auth_code:
        print("인증 코드를 받지 못했습니다. 다시 시도해주세요.")
        sys.exit(1)

    print("인증 코드 수신 완료. 토큰 교환 중...")

    # 5. authorization code → tokens 교환
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
    )

    if resp.status_code != 200:
        print(f"토큰 교환 실패: {resp.status_code} {resp.text}")
        sys.exit(1)

    tokens = resp.json()
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        print("refresh_token이 없습니다. Google Cloud Console에서 consent screen을")
        print("'production'으로 설정하거나 다시 인증해주세요.")
        sys.exit(1)

    # 6. .env에 refresh_token 저장
    _update_env_file("BLOGGER_REFRESH_TOKEN", refresh_token)

    print(f"\nBlogger OAuth 설정 완료!")
    print(f"  BLOGGER_REFRESH_TOKEN이 .env에 저장되었습니다.")
    print(f"\n이제 아래 명령으로 블로그 포스팅을 테스트할 수 있습니다:")
    print(f"  python scripts/post_discussion_to_blog.py --dry-run")


if __name__ == "__main__":
    main()
