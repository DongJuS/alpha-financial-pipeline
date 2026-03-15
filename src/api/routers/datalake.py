"""
src/api/routers/datalake.py — 데이터 레이크(S3/MinIO) 관리 라우터
"""

import asyncio
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.api.deps import get_admin_user, get_current_user
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.s3_client import _get_s3_client

router = APIRouter()
logger = get_logger(__name__)


class DataLakeOverview(BaseModel):
    bucket_name: str
    total_objects: int
    total_size_bytes: int
    total_size_display: str
    prefixes: list[dict[str, Any]]


class S3ObjectItem(BaseModel):
    key: str
    size: int
    size_display: str
    last_modified: Optional[str] = None
    storage_class: Optional[str] = None


class S3ObjectListResponse(BaseModel):
    prefix: str
    objects: list[S3ObjectItem]
    common_prefixes: list[str]
    total: int


class S3ObjectDetail(BaseModel):
    key: str
    size: int
    size_display: str
    content_type: Optional[str] = None
    last_modified: Optional[str] = None
    metadata: dict[str, str]


def _format_size(size_bytes: int) -> str:
    """바이트를 읽기 쉬운 형식으로 변환합니다."""
    val = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"


@router.get("/overview", response_model=DataLakeOverview)
async def get_datalake_overview(
    _: Annotated[dict, Depends(get_current_user)],
) -> DataLakeOverview:
    """데이터 레이크 개요 (총 객체 수, 크기, 접두사별 분류)를 반환합니다."""
    settings = get_settings()
    bucket = settings.s3_bucket_name
    client = _get_s3_client()

    def _scan():
        total_objects = 0
        total_size = 0
        prefix_stats: dict[str, dict[str, int]] = {}
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                total_objects += 1
                total_size += obj.get("Size", 0)
                key = obj["Key"]
                top_prefix = key.split("/")[0] if "/" in key else "(root)"
                if top_prefix not in prefix_stats:
                    prefix_stats[top_prefix] = {"count": 0, "size": 0}
                prefix_stats[top_prefix]["count"] += 1
                prefix_stats[top_prefix]["size"] += obj.get("Size", 0)
        return total_objects, total_size, prefix_stats

    total_objects, total_size, prefix_stats = await asyncio.to_thread(_scan)

    prefixes = [
        {
            "prefix": p,
            "count": stats["count"],
            "size": stats["size"],
            "size_display": _format_size(stats["size"]),
        }
        for p, stats in sorted(prefix_stats.items())
    ]

    return DataLakeOverview(
        bucket_name=bucket,
        total_objects=total_objects,
        total_size_bytes=total_size,
        total_size_display=_format_size(total_size),
        prefixes=prefixes,
    )


@router.get("/objects", response_model=S3ObjectListResponse)
async def list_datalake_objects(
    _: Annotated[dict, Depends(get_current_user)],
    prefix: str = Query(default="", description="S3 키 접두사"),
    limit: int = Query(default=100, ge=1, le=1000),
    delimiter: str = Query(default="/", description="경로 구분자"),
) -> S3ObjectListResponse:
    """접두사 아래의 객체 및 하위 폴더를 반환합니다."""
    settings = get_settings()
    bucket = settings.s3_bucket_name
    client = _get_s3_client()

    def _list():
        resp = client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            Delimiter=delimiter,
            MaxKeys=limit,
        )
        objects = []
        for obj in resp.get("Contents", []):
            objects.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "size_display": _format_size(obj["Size"]),
                    "last_modified": obj["LastModified"].isoformat()
                    if obj.get("LastModified")
                    else None,
                    "storage_class": obj.get("StorageClass"),
                }
            )
        common_prefixes = [cp["Prefix"] for cp in resp.get("CommonPrefixes", [])]
        return objects, common_prefixes

    objects, common_prefixes = await asyncio.to_thread(_list)

    return S3ObjectListResponse(
        prefix=prefix,
        objects=[S3ObjectItem(**o) for o in objects],
        common_prefixes=common_prefixes,
        total=len(objects),
    )


@router.get("/object-info", response_model=S3ObjectDetail)
async def get_object_info(
    _: Annotated[dict, Depends(get_current_user)],
    key: str = Query(..., description="S3 오브젝트 키"),
) -> S3ObjectDetail:
    """단일 S3 오브젝트의 메타데이터를 반환합니다."""
    settings = get_settings()
    bucket = settings.s3_bucket_name
    client = _get_s3_client()

    def _head():
        try:
            return client.head_object(Bucket=bucket, Key=key)
        except Exception:
            return None

    resp = await asyncio.to_thread(_head)
    if resp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"오브젝트 '{key}'를 찾을 수 없습니다.",
        )

    return S3ObjectDetail(
        key=key,
        size=resp.get("ContentLength", 0),
        size_display=_format_size(resp.get("ContentLength", 0)),
        content_type=resp.get("ContentType"),
        last_modified=resp["LastModified"].isoformat()
        if resp.get("LastModified")
        else None,
        metadata=resp.get("Metadata", {}),
    )


@router.delete("/objects")
async def delete_object(
    _: Annotated[dict, Depends(get_admin_user)],
    key: str = Query(..., description="삭제할 S3 오브젝트 키"),
) -> dict:
    """S3 오브젝트를 삭제합니다 (관리자 전용)."""
    settings = get_settings()
    bucket = settings.s3_bucket_name
    client = _get_s3_client()

    def _delete():
        client.delete_object(Bucket=bucket, Key=key)

    await asyncio.to_thread(_delete)
    logger.info("S3 오브젝트 삭제: s3://%s/%s", bucket, key)
    return {"message": f"오브젝트 '{key}'가 삭제되었습니다."}
