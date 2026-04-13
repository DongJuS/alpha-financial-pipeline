"""
test/test_utils_s3_client.py -- src/utils/s3_client.py 단위 테스트

실제 S3/MinIO 없이 boto3 클라이언트를 mock하여 검증합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        extra = call_kwargs.kwargs.get("ExtraArgs")
        assert extra is not None, "ExtraArgs should be passed to upload_fileobj"
        assert extra["ContentType"] == "application/json"

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


# ── S3 Client 에지케이스 (Agent 4 QA Round 2) ────────────────────────────────


class TestEnsureBucketEdgeCases:
    """ensure_bucket: 비-404 에러, 재발생."""

    @pytest.mark.asyncio
    async def test_non_404_error_propagates(self):
        """404가 아닌 에러(예: 403 Forbidden)는 예외로 전파."""
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "403", "Message": "Forbidden"}},
                "HeadBucket",
            )
        )

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            with pytest.raises(ClientError):
                await ensure_bucket()

        mock_client.create_bucket.assert_not_called()


class TestEnsureBucketR2:
    """ensure_bucket: Cloudflare R2 환경 시뮬레이션.

    R2는 버킷 자동 생성을 지원하지 않아 create_bucket 시 403/409를 반환.
    ensure_bucket은 이를 경고 로그로 처리하고 예외 없이 완료해야 합니다.
    """

    @pytest.mark.asyncio
    async def test_r2_create_bucket_403_suppressed(self):
        """R2: head_bucket 404 → create_bucket 403 → 예외 없이 완료."""
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_settings.s3_endpoint_url = "https://abc123.r2.cloudflarestorage.com"
        mock_settings.s3_region = "auto"

        mock_client.head_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )
        )
        mock_client.create_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "403", "Message": "Forbidden"}},
                "CreateBucket",
            )
        )

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            # 403은 경고 로그만 남기고 예외 없이 완료
            await ensure_bucket()

    @pytest.mark.asyncio
    async def test_r2_create_bucket_409_suppressed(self):
        """R2: head_bucket 404 → create_bucket 409 (BucketAlreadyExists) → 예외 없이 완료."""
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_settings.s3_endpoint_url = "https://abc123.r2.cloudflarestorage.com"
        mock_settings.s3_region = "auto"

        mock_client.head_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )
        )
        mock_client.create_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "409", "Message": "BucketAlreadyOwnedByYou"}},
                "CreateBucket",
            )
        )

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            # 409은 경고 로그만 남기고 예외 없이 완료
            await ensure_bucket()

    @pytest.mark.asyncio
    async def test_r2_create_bucket_unexpected_error_propagates(self):
        """R2: head_bucket 404 → create_bucket 500 → 예외 전파."""
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )
        )
        mock_client.create_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "500", "Message": "Internal Server Error"}},
                "CreateBucket",
            )
        )

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            with pytest.raises(ClientError):
                await ensure_bucket()

    @pytest.mark.asyncio
    async def test_minio_create_bucket_success(self):
        """MinIO: head_bucket 404 → create_bucket 성공 (정상 플로우)."""
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_bucket = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )
        )
        mock_client.create_bucket = MagicMock()  # 성공

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import ensure_bucket

            await ensure_bucket()

        mock_client.create_bucket.assert_called_once_with(Bucket="test-bucket")


class TestUploadBytesEdgeCases:
    """upload_bytes: 빈 데이터, 특수 키 경로."""

    @pytest.mark.asyncio
    async def test_empty_bytes_upload(self):
        """빈 바이트 데이터도 정상 업로드."""
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            result = await upload_bytes(b"", "empty/file.txt")

        assert result == "s3://test-bucket/empty/file.txt"
        mock_client.upload_fileobj.assert_called_once()

    @pytest.mark.asyncio
    async def test_nested_key_path(self):
        """깊은 경로의 키도 정상 처리."""
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            key = "tick_data/2026/04/11/005930/hour_09.parquet"
            result = await upload_bytes(b"data", key)

        assert result == f"s3://test-bucket/{key}"

    @pytest.mark.asyncio
    async def test_upload_with_extra_args_structure(self):
        """ExtraArgs에 ContentType과 Metadata가 올바르게 전달."""
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.upload_fileobj = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import upload_bytes

            await upload_bytes(
                b"parquet data",
                "data.parquet",
                content_type="application/x-parquet",
                metadata={"ticker": "005930", "date": "2026-04-11"},
            )

        call_kwargs = mock_client.upload_fileobj.call_args
        extra_args = call_kwargs.kwargs.get("ExtraArgs")
        assert extra_args is not None
        assert extra_args["ContentType"] == "application/x-parquet"
        assert extra_args["Metadata"]["ticker"] == "005930"


class TestObjectExistsEdgeCases:
    """object_exists: 다양한 에러 코드."""

    @pytest.mark.asyncio
    async def test_any_client_error_returns_false(self):
        """어떤 ClientError든 False 반환 (403, 500 등)."""
        from botocore.exceptions import ClientError

        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_object = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "403", "Message": "Forbidden"}},
                "HeadObject",
            )
        )

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import object_exists

            result = await object_exists("forbidden/file.txt")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_with_custom_bucket(self):
        """커스텀 버킷에서 존재 여부 확인."""
        mock_client, mock_settings = _mock_s3_setup()
        mock_client.head_object = MagicMock()

        with (
            patch("src.utils.s3_client._get_s3_client", return_value=mock_client),
            patch("src.utils.s3_client.get_settings", return_value=mock_settings),
        ):
            from src.utils.s3_client import object_exists

            result = await object_exists("file.txt", bucket="custom-bucket")

        assert result is True
        call_kwargs = mock_client.head_object.call_args
        assert call_kwargs.kwargs.get("Bucket") == "custom-bucket"
