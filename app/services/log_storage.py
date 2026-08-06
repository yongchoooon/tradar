"""Helpers for writing application logs to Cloudflare R2."""

from __future__ import annotations

import logging
import os
from typing import Optional

try:  # pragma: no cover - dependency availability is environment-specific
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover
    BotoCoreError = ClientError = Exception  # type: ignore

from app.services.r2_client import (
    R2ConfigurationError,
    get_r2_client,
    r2_enabled,
    r2_log_bucket_name,
)

logger = logging.getLogger("log_storage")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def r2_logs_enabled() -> bool:
    return r2_enabled() and _truthy(_env("R2_LOGS_ENABLED", "true"))


def get_log_storage():
    if not r2_logs_enabled():
        raise R2ConfigurationError("R2 log storage is disabled")
    return r2_log_bucket_name(), get_r2_client()


def build_log_key(key_suffix: str) -> str:
    suffix = key_suffix.lstrip("/")
    prefix = (_env("R2_LOG_PREFIX", "logs") or "logs").strip("/")
    return f"{prefix}/{suffix}" if prefix else suffix


def upload_text(key_suffix: str, text: str, content_type: str = "text/plain") -> bool:
    if not r2_logs_enabled():
        return False
    key = build_log_key(key_suffix)
    try:
        bucket, client = get_log_storage()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType=content_type,
        )
        return True
    except (ClientError, BotoCoreError, R2ConfigurationError, RuntimeError) as exc:
        logger.warning("Failed to upload log to R2 key=%s: %s", key, exc)
        return False


def upload_bytes(key_suffix: str, payload: bytes, content_type: str = "application/octet-stream") -> bool:
    if not r2_logs_enabled():
        return False
    key = build_log_key(key_suffix)
    try:
        bucket, client = get_log_storage()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
        )
        return True
    except (ClientError, BotoCoreError, R2ConfigurationError, RuntimeError) as exc:
        logger.warning("Failed to upload log to R2 key=%s: %s", key, exc)
        return False
