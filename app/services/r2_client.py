"""Cloudflare R2 S3-compatible client configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

try:  # pragma: no cover - dependency availability is environment-specific
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None
    Config = None


class R2ConfigurationError(RuntimeError):
    """Raised when required R2 runtime configuration is missing."""


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


def r2_enabled() -> bool:
    return _truthy(_env("R2_ENABLED", "false"))


def r2_bucket_name() -> str:
    bucket = _env("R2_BUCKET")
    if not bucket:
        raise R2ConfigurationError("R2_BUCKET is required when R2_ENABLED=true")
    return bucket


def r2_log_bucket_name() -> str:
    return _env("R2_LOG_BUCKET") or r2_bucket_name()


@lru_cache(maxsize=1)
def get_r2_client():
    if boto3 is None or Config is None:
        raise R2ConfigurationError("boto3 and botocore are required for R2")

    endpoint_url = _env("R2_ENDPOINT_URL")
    access_key_id = _env("R2_ACCESS_KEY_ID")
    secret_access_key = _env("R2_SECRET_ACCESS_KEY")
    region = _env("R2_REGION", "auto")

    missing = [
        name
        for name, value in (
            ("R2_ENDPOINT_URL", endpoint_url),
            ("R2_ACCESS_KEY_ID", access_key_id),
            ("R2_SECRET_ACCESS_KEY", secret_access_key),
        )
        if not value
    ]
    if missing:
        raise R2ConfigurationError(
            "Missing required R2 environment variables: " + ", ".join(missing)
        )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def clear_r2_client_cache() -> None:
    """Clear the cached client, primarily for tests and credential rotation."""

    get_r2_client.cache_clear()
