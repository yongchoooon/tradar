"""Helpers for writing logs locally and/or uploading them to S3."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

try:  # pragma: no cover - optional dependency
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None
    BotoCoreError = ClientError = Exception  # type: ignore


logger = logging.getLogger("log_storage")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _bucket_name() -> Optional[str]:
    return _env("LOGS_S3_BUCKET") or _env("TRADAR_DATA_BUCKET")


def s3_logs_enabled() -> bool:
    return bool(_bucket_name())


@lru_cache(maxsize=1)
def _s3_client():
    if boto3 is None:
        raise RuntimeError("boto3 is not available for S3 logging")
    region = _env("LOGS_S3_REGION") or _env("AWS_REGION")
    endpoint_url = _env("LOGS_S3_ENDPOINT_URL")
    return boto3.client("s3", region_name=region, endpoint_url=endpoint_url)


def _build_key(key_suffix: str) -> str:
    prefix = _env("LOGS_S3_PREFIX", "logs") or "logs"
    suffix = key_suffix.lstrip("/")
    return f"{prefix.rstrip('/')}/{suffix}"


def upload_text(key_suffix: str, text: str, content_type: str = "text/plain") -> bool:
    if not s3_logs_enabled():
        return False
    bucket = _bucket_name()
    if not bucket:
        return False
    key = _build_key(key_suffix)
    try:
        client = _s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType=content_type,
        )
        return True
    except (ClientError, BotoCoreError, RuntimeError) as exc:
        logger.warning("Failed to upload log to s3 key=%s: %s", key, exc)
        return False


def upload_bytes(key_suffix: str, payload: bytes, content_type: str = "application/octet-stream") -> bool:
    if not s3_logs_enabled():
        return False
    bucket = _bucket_name()
    if not bucket:
        return False
    key = _build_key(key_suffix)
    try:
        client = _s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
        )
        return True
    except (ClientError, BotoCoreError, RuntimeError) as exc:
        logger.warning("Failed to upload log to s3 key=%s: %s", key, exc)
        return False
