"""Configuration for desktop worker coordination."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Set

logger = logging.getLogger(__name__)


def _parse_int(value: Optional[str], fallback: int) -> int:
    if value is None:
        return fallback
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed


def _parse_float(value: Optional[str], fallback: float) -> float:
    if value is None:
        return fallback
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed


def _parse_allowlist(value: Optional[str]) -> Optional[Set[str]]:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return set(items) if items else None


@dataclass(frozen=True)
class WorkerSettings:
    token: str
    allowlist: Optional[Set[str]]
    search_timeout_seconds: float
    topk_default: int


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    token = os.getenv("DESKTOP_WORKER_TOKEN", "").strip()
    if os.getenv("APP_ENV", "dev").lower() == "prod" and not token:
        raise RuntimeError("DESKTOP_WORKER_TOKEN is required in prod")
    if not token:
        logger.warning("Desktop worker token is not configured.")

    timeout_value = os.getenv("SEARCH_TIMEOUT_SECONDS", "30")
    topk_value = os.getenv("TOPK_DEFAULT", "20")
    allowlist_raw = os.getenv("DESKTOP_WORKER_ID_ALLOWLIST", "")

    return WorkerSettings(
        token=token,
        allowlist=_parse_allowlist(allowlist_raw),
        search_timeout_seconds=_parse_float(timeout_value, 30.0),
        topk_default=_parse_int(topk_value, 20),
    )
