"""
src/utils/blog_client.py — Google Blogger API 클라이언트

논의 문서를 블로그에 자동 포스팅하기 위한 Blogger API v3 클라이언트입니다.
OAuth 2.0 refresh token 기반으로 동작합니다.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"


# ── 데이터 모델 ──────────────────────────────────────────────────────────


class BlogPost(BaseModel):
    """발행할 블로그 글."""

    title: str
    content_html: str
    labels: list[str] = []
    is_draft: bool = False


class BlogPostResult(BaseModel):
    """발행 결과."""

    post_id: str
    url: str
    platform: str
    published_at: str


# ── 프로토콜 ─────────────────────────────────────────────────────────────


@runtime_checkable
class BaseBlogClient(Protocol):
    """블로그 클라이언트 인터페이스 (추후 WordPress/Medium 등 확장용)."""

    async def publish(self, post: BlogPost) -> BlogPostResult: ...

    async def update(self, post_id: str, post: BlogPost) -> BlogPostResult: ...

    async def find_by_title(self, title: str) -> str | None:
        """제목으로 기존 글 검색. 있으면 post_id 반환, 없으면 None."""
        ...

    async def close(self) -> None: ...


# ── Blogger 구현 ─────────────────────────────────────────────────────────


class BloggerClient:
    """Google Blogger API v3 클라이언트."""

    def __init__(
        self,
        blog_id: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self._blog_id = blog_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str = ""
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _refresh_access_token(self) -> None:
        """refresh_token으로 access_token을 갱신합니다."""
        resp = await self._http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        logger.info("Blogger access token refreshed")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def publish(self, post: BlogPost) -> BlogPostResult:
        """블로그 글을 발행합니다. 401 시 토큰 갱신 후 1회 재시도."""
        if not self._access_token:
            await self._refresh_access_token()

        url = f"{BLOGGER_API_BASE}/blogs/{self._blog_id}/posts"
        params: dict[str, str] = {}
        if post.is_draft:
            params["isDraft"] = "true"

        body = {
            "kind": "blogger#post",
            "title": post.title,
            "content": post.content_html,
            "labels": post.labels,
        }

        resp = await self._http.post(
            url, json=body, headers=self._auth_headers(), params=params
        )

        # 401 → 토큰 갱신 후 1회 재시도
        if resp.status_code == 401:
            logger.warning("Blogger 401 — refreshing token and retrying")
            await self._refresh_access_token()
            resp = await self._http.post(
                url, json=body, headers=self._auth_headers(), params=params
            )

        resp.raise_for_status()
        data = resp.json()

        result = BlogPostResult(
            post_id=data["id"],
            url=data.get("url", ""),
            platform="blogger",
            published_at=data.get("published", ""),
        )
        logger.info("Blog post published: %s → %s", result.post_id, result.url)
        return result

    async def update(self, post_id: str, post: BlogPost) -> BlogPostResult:
        """기존 글을 업데이트합니다."""
        if not self._access_token:
            await self._refresh_access_token()

        url = f"{BLOGGER_API_BASE}/blogs/{self._blog_id}/posts/{post_id}"
        body = {
            "kind": "blogger#post",
            "title": post.title,
            "content": post.content_html,
            "labels": post.labels,
        }

        resp = await self._http.put(
            url, json=body, headers=self._auth_headers()
        )

        if resp.status_code == 401:
            await self._refresh_access_token()
            resp = await self._http.put(
                url, json=body, headers=self._auth_headers()
            )

        resp.raise_for_status()
        data = resp.json()

        return BlogPostResult(
            post_id=data["id"],
            url=data.get("url", ""),
            platform="blogger",
            published_at=data.get("updated", data.get("published", "")),
        )

    async def find_by_title(self, title: str) -> str | None:
        """제목으로 기존 글을 검색합니다. 중복 방지용."""
        if not self._access_token:
            await self._refresh_access_token()

        url = f"{BLOGGER_API_BASE}/blogs/{self._blog_id}/posts/search"
        resp = await self._http.get(
            url, params={"q": title}, headers=self._auth_headers()
        )

        if resp.status_code == 401:
            await self._refresh_access_token()
            resp = await self._http.get(
                url, params={"q": title}, headers=self._auth_headers()
            )

        if resp.status_code == 404 or resp.status_code == 200 and not resp.json().get("items"):
            return None

        resp.raise_for_status()
        items = resp.json().get("items", [])
        for item in items:
            if item.get("title", "").strip() == title.strip():
                return item["id"]
        return None

    async def close(self) -> None:
        await self._http.aclose()


# ── 팩토리 ───────────────────────────────────────────────────────────────


def get_blog_client() -> BloggerClient:
    """Settings에서 Blogger 자격 증명을 읽어 클라이언트를 반환합니다."""
    from src.utils.config import get_settings

    s = get_settings()
    if not s.blogger_blog_id:
        raise ValueError("BLOGGER_BLOG_ID가 설정되지 않았습니다. .env를 확인하세요.")
    if not s.blogger_refresh_token:
        raise ValueError(
            "BLOGGER_REFRESH_TOKEN이 설정되지 않았습니다. "
            "scripts/setup_blogger_oauth.py로 초기 설정을 완료하세요."
        )

    return BloggerClient(
        blog_id=s.blogger_blog_id,
        client_id=s.blogger_client_id,
        client_secret=s.blogger_client_secret,
        refresh_token=s.blogger_refresh_token,
    )
