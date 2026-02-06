"""Helpers for loading configuration values from AWS SSM Parameter Store."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover - boto3 missing in dev
    boto3 = None
    BotoCoreError = ClientError = Exception  # type: ignore


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _ssm_enabled() -> bool:
    if _truthy(os.getenv("TRADAR_DISABLE_SSM")):
        return False
    app_env = os.getenv("APP_ENV", "dev").lower()
    if app_env == "prod":
        return True
    return _truthy(os.getenv("TRADAR_USE_SSM"))


@lru_cache(maxsize=1)
def _get_ssm_client():
    if boto3 is None:
        raise RuntimeError("boto3 is not installed")
    return boto3.client("ssm")


@lru_cache(maxsize=128)
def _get_ssm_value(name: str) -> Optional[str]:
    if not name:
        return None
    if boto3 is None:
        logger.warning("SSM lookup skipped (boto3 missing) for %s", name)
        return None
    try:
        client = _get_ssm_client()
        response = client.get_parameter(Name=name, WithDecryption=True)
        param = response.get("Parameter", {})
        return param.get("Value")
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        logger.warning("SSM lookup failed for %s: %s", name, exc)
        return None


def resolve_param(
    env_key: Optional[str],
    ssm_path: Optional[str],
    *,
    default: Optional[str] = None,
    required: bool = False,
) -> Optional[str]:
    """Resolve a value from env or SSM, falling back to default."""
    value = os.getenv(env_key) if env_key else None
    if value:
        return value
    if ssm_path and _ssm_enabled():
        ssm_value = _get_ssm_value(ssm_path)
        if ssm_value:
            return ssm_value
    if required:
        raise RuntimeError(
            f"Missing required setting: env={env_key or '<none>'} ssm={ssm_path or '<none>'}"
        )
    return default
