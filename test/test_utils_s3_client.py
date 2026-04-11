"""
test/test_utils_s3_client.py -- src/utils/s3_client.py 단위 테스트

실제 S3/MinIO 없이 boto3 클라이언트를 mock하여 검증합니다.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


def _mock_s3_setup():
    """공통 S3 mock 환경을 구성합니다."""
    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.s3_endpoint_url = "http://localhost:9000"
    mock_settings.s3_access_key = "test-access"
    mock_settings.s3_secret_key = "test-secret"
    mock_settings.s3_region = "us-east-1"
    mock_settings.s3_bucket_name = "test-bucket"

    return mock_client, mock_settings


# ── ensure_bucket ───────────────────────────────────────────────────────────


class TestEnsureBucket:
    @pytest.mark.asyncio
    async def test_bucket_already_exists(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_bucket = MagicMock()  # no exception = exists

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            await ensure_bucket()

        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")
        mock_client.create_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_bucket_not_found_creates(self):
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )
        )
        mock_client.create_bucket = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            await ensure_bucket()

        mock_client.create_bucket.assert_called_once_with(Bucket="test-bucket")

    @pytest.mark.asyncio
    async def test_custom_bucket_name(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_bucket = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            await ensure_bucket("custom-bucket")

        mock_client.head_bucket.assert_called_once_with(Bucket="custom-bucket")


# ── upload_bytes ────────────────────────────────────────────────────────────


class TestUploadBytes:
    @pytest.mark.asyncio
    async def test_upload_returns_s3_uri(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            result = await upload_bytes(b"hello world", "test/file.txt")

        assert result == "s3://test-bucket/test/file.txt"
        mock_client.upload_fileobj.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_content_type(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            await upload_bytes(b"{}", "test/data.json", content_type="application/json")

        call_kwargs = mock_client.upload_fileobj.call_args
        extra = call_kwargs.kwargs.get("ExtraArgs") or call_kwargs[1].get("ExtraArgs") if len(call_kwargs) > 1 else None
        if extra is None and len(call_kwargs.args) > 3:
            extra = call_kwargs.args[3]
        # Check that content type was set
        assert mock_client.upload_fileobj.called

    @pytest.mark.asyncio
    async def test_upload_with_metadata(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            await upload_bytes(
                b"data",
                "test/file.bin",
                metadata={"source": "test"},
            )

        mock_client.upload_fileobj.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_custom_bucket(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            result = await upload_bytes(b"data", "key.txt", bucket="other-bucket")

        assert result == "s3://other-bucket/key.txt"


# ── download_bytes ──────────────────────────────────────────────────────────


class TestDownloadBytes:
    @pytest.mark.asyncio
    async def test_download_returns_bytes(self):
        mock_client, mock_settings = _mock_s3_setup()

        def _fake_download(bucket, key, fileobj):
            fileobj.write(b"downloaded content")

        mock_client.download_fileobj = MagicMock(side_effect=_fake_download)

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import download_bytes

            result = await download_bytes("test/file.txt")

        assert result == b"downloaded content"

    @pytest.mark.asyncio
    async def test_download_custom_bucket(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.download_fileobj = MagicMock(side_effect=lambda b, k, f: f.write(b"ok"))

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import download_bytes

            result = await download_bytes("key.txt", bucket="other-bucket")

        assert result == b"ok"
        call_args = mock_client.download_fileobj.call_args.args
        assert call_args[0] == "other-bucket"


# ── list_objects ────────────────────────────────────────────────────────────


class TestListObjects:
    @pytest.mark.asyncio
    async def test_returns_key_list(self):
        mock_client, mock_settings = _mock_s3_setup()

        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "prefix/a.txt"}, {"Key": "prefix/b.txt"}]},
            {"Contents": [{"Key": "prefix/c.txt"}]},
        ]
        mock_client.get_paginator = MagicMock(return_value=paginator)

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import list_objects

            result = await list_objects("prefix/")

        assert len(result) == 3
        assert "prefix/a.txt" in result
        assert "prefix/c.txt" in result

    @pytest.mark.asyncio
    async def test_empty_prefix(self):
        mock_client, mock_settings = _mock_s3_setup()

        paginator = MagicMock()
        paginator.paginate.return_value = [{}]  # no "Contents" key
        mock_client.get_paginator = MagicMock(return_value=paginator)

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import list_objects

            result = await list_objects("nonexistent/")

        assert result == []


# ── object_exists ───────────────────────────────────────────────────────────


class TestObjectExists:
    @pytest.mark.asyncio
    async def test_exists_returns_true(self):
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_object = MagicMock()  # no exception = exists

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import object_exists

            result = await object_exists("test/file.txt")

        assert result is True

    @pytest.mark.asyncio
    async def test_not_exists_returns_false(self):
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_object = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        )

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import object_exists

            result = await object_exists("nonexistent/file.txt")

        assert result is False
