"""OpenSearch connection helpers used for BM25 retrieval."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable
from urllib.parse import urlparse

from opensearchpy import OpenSearch


class OpenSearchNotConfigured(RuntimeError):
    """Raised when OPENSEARCH_URL is missing."""


def _get_url() -> str:
    url = os.getenv("OPENSEARCH_URL")
    if not url:
        raise OpenSearchNotConfigured(
            "OPENSEARCH_URL environment variable is not set."
        )
    return url


def is_configured() -> bool:
    """Return True if OPENSEARCH_URL is provided."""

    return bool(os.getenv("OPENSEARCH_URL"))


def get_index_name() -> str:
    """Return the OpenSearch index used for BM25 lookups."""

    return os.getenv("OPENSEARCH_INDEX", "tradar_trademarks")


def get_search_fields(default: Iterable[str] | None = None) -> list[str]:
    """Return the field list used for multi_match queries."""

    raw = os.getenv("OPENSEARCH_SEARCH_FIELDS")
    if raw:
        return [field.strip() for field in raw.split(",") if field.strip()]
    if default is None:
        default = ["title_korean^2", "title_english", "aliases^0.5"]
    return list(default)


@lru_cache(maxsize=1)
def get_client() -> OpenSearch:
    """Instantiate and cache an OpenSearch client."""

    url = _get_url()
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid OPENSEARCH_URL: {url!r}")

    use_ssl = parsed.scheme == "https"
    port = parsed.port or (443 if use_ssl else 80)
    http_auth = None
    if parsed.username:
        http_auth = (parsed.username, parsed.password or "")

    kwargs = {
        "hosts": [{"host": parsed.hostname, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": bool(int(os.getenv("OPENSEARCH_VERIFY_CERTS", "0"))) if use_ssl else False,
        "ssl_show_warn": False,
        "timeout": float(os.getenv("OPENSEARCH_TIMEOUT", "10")),
        "max_retries": int(os.getenv("OPENSEARCH_MAX_RETRIES", "3")),
        "retry_on_timeout": True,
    }
    if http_auth:
        kwargs["http_auth"] = http_auth
    if parsed.path and parsed.path != "/":
        kwargs["url_prefix"] = parsed.path.strip("/")

    return OpenSearch(**kwargs)
