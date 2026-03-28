"""test/unit/test_blog_client.py — BloggerClient 유닛 테스트."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.blog_client import (
    BloggerClient,
    BlogPost,
    BlogPostResult,
    get_blog_client,
)


@pytest.fixture
def client() -> BloggerClient:
    return BloggerClient(
        blog_id="123456",
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )


@pytest.fixture
def sample_post() -> BlogPost:
    return BlogPost(
        title="[agents-investing] Test Post",
        content_html="<p>Hello World</p>",
        labels=["agents-investing", "test"],
        is_draft=False,
    )


class TestBlogPost:
    def test_create(self) -> None:
        post = BlogPost(title="t", content_html="<p>c</p>")
        assert post.title == "t"
        assert post.labels == []
        assert post.is_draft is False

    def test_with_labels(self) -> None:
        post = BlogPost(title="t", content_html="<p>c</p>", labels=["a", "b"])
        assert post.labels == ["a", "b"]


class TestBlogPostResult:
    def test_create(self) -> None:
        r = BlogPostResult(post_id="1", url="http://x", platform="blogger", published_at="2026-01-01")
        assert r.post_id == "1"
        assert r.platform == "blogger"


class TestBloggerClientTokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_access_token(self, client: BloggerClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new_token"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp):
            await client._refresh_access_token()
            assert client._access_token == "new_token"


class TestBloggerClientPublish:
    @pytest.mark.asyncio
    async def test_publish_success(self, client: BloggerClient, sample_post: BlogPost) -> None:
        client._access_token = "valid_token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "999",
            "url": "https://blog.example.com/999",
            "published": "2026-03-28T10:00:00Z",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.publish(sample_post)
            assert result.post_id == "999"
            assert result.platform == "blogger"
            assert "blog.example.com" in result.url

    @pytest.mark.asyncio
    async def test_publish_retry_on_401(self, client: BloggerClient, sample_post: BlogPost) -> None:
        client._access_token = "expired_token"

        # 첫 번째 호출: 401, 토큰 갱신 후 재시도: 200
        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "id": "1000",
            "url": "https://blog.example.com/1000",
            "published": "2026-03-28T10:00:00Z",
        }
        resp_200.raise_for_status = MagicMock()

        # 토큰 갱신 응답
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "refreshed_token"}
        token_resp.raise_for_status = MagicMock()

        # post 호출 순서: publish(401) → refresh(200) → publish(200)
        with patch.object(
            client._http,
            "post",
            new_callable=AsyncMock,
            side_effect=[resp_401, token_resp, resp_200],
        ):
            result = await client.publish(sample_post)
            assert result.post_id == "1000"
            assert client._access_token == "refreshed_token"

    @pytest.mark.asyncio
    async def test_publish_draft(self, client: BloggerClient) -> None:
        client._access_token = "valid"
        draft_post = BlogPost(title="Draft", content_html="<p>d</p>", is_draft=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "d1", "url": "", "published": ""}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await client.publish(draft_post)
            # isDraft=true 파라미터가 전달되었는지 확인
            call_kwargs = mock_post.call_args
            assert call_kwargs.kwargs.get("params", {}).get("isDraft") == "true"


class TestBloggerClientFindByTitle:
    @pytest.mark.asyncio
    async def test_find_existing(self, client: BloggerClient) -> None:
        client._access_token = "valid"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "42", "title": "My Title"}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            post_id = await client.find_by_title("My Title")
            assert post_id == "42"

    @pytest.mark.asyncio
    async def test_find_not_found(self, client: BloggerClient) -> None:
        client._access_token = "valid"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            post_id = await client.find_by_title("Nonexistent")
            assert post_id is None


class TestGetBlogClient:
    def test_missing_blog_id_raises(self) -> None:
        mock_settings = MagicMock()
        mock_settings.blogger_blog_id = ""
        mock_settings.blogger_refresh_token = "x"

        with patch("src.utils.config.get_settings", return_value=mock_settings):
            with pytest.raises(ValueError, match="BLOGGER_BLOG_ID"):
                get_blog_client()

    def test_missing_refresh_token_raises(self) -> None:
        mock_settings = MagicMock()
        mock_settings.blogger_blog_id = "123"
        mock_settings.blogger_refresh_token = ""

        with patch("src.utils.config.get_settings", return_value=mock_settings):
            with pytest.raises(ValueError, match="BLOGGER_REFRESH_TOKEN"):
                get_blog_client()
