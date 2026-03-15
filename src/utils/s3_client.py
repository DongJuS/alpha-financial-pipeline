"""
src/utils/s3_client.py — S3/MinIO 클라이언트 유틸리티

boto3 기반 S3 클라이언트를 싱글턴으로 관리하고,
버킷 자동 생성 및 기본 업로드/다운로드 헬퍼를 제공합니다.
"""

from __future__ import annotations

import asyncio
import io
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def _get_s3_client():
    """boto3 S3 클라이언트를 싱글턴으로 반환합니다."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )


async def ensure_bucket(bucket: str | None = None) -> None:
    """버킷이 없으면 생성합니다."""
    settings = get_settings()
    bucket = bucket or settings.s3_bucket_name
    client = _get_s3_client()

    def _ensure():
        try:
            client.head_bucket(Bucket=bucket)
            logger.debug("S3 버킷 '%s' 이미 존재", bucket)
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                client.create_bucket(Bucket=bucket)
                logger.info("S3 버킷 '%s' 생성 완료", bucket)
            else:
                raise

    await asyncio.to_thread(_ensure)


async def upload_bytes(
    data: bytes,
    key: str,
    bucket: str | None = None,
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
) -> str:
    """바이트 데이터를 S3에 업로드하고, 저장된 key를 반환합니다."""
    settings = get_settings()
    bucket = bucket or settings.s3_bucket_name
    client = _get_s3_client()

    extra_args: dict[str, Any] = {"ContentType": content_type}
    if metadata:
        extra_args["Metadata"] = metadata

    def _upload():
        client.upload_fileobj(io.BytesIO(data), bucket, key, ExtraArgs=extra_args)

    await asyncio.to_thread(_upload)
    logger.debug("S3 업로드 완료: s3://%s/%s (%d bytes)", bucket, key, len(data))
    return f"s3://{bucket}/{key}"


async def download_bytes(key: str, bucket: str | None = None) -> bytes:
    """S3에서 오브젝트를 다운로드하여 bytes로 반환합니다."""
    settings = get_settings()
    bucket = bucket or settings.s3_bucket_name
    client = _get_s3_client()

    def _download():
        buf = io.BytesIO()
        client.download_fileobj(bucket, key, buf)
        return buf.getvalue()

    return await asyncio.to_thread(_download)


async def list_objects(prefix: str, bucket: str | None = None) -> list[str]:
    """주어진 prefix 아래의 오브젝트 키 목록을 반환합니다."""
    settings = get_settings()
    bucket = bucket or settings.s3_bucket_name
    client = _get_s3_client()

    def _list():
        keys: list[str] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    return await asyncio.to_thread(_list)


async def object_exists(key: str, bucket: str | None = None) -> bool:
    """S3에 해당 키의 오브젝트가 존재하는지 확인합니다."""
    settings = get_settings()
    bucket = bucket or settings.s3_bucket_name
    client = _get_s3_client()

    def _exists():
        try:
            client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    return await asyncio.to_thread(_exists)
