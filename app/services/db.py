"""PostgreSQL connection helpers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg
from pgvector.psycopg import register_vector


class DatabaseNotConfigured(RuntimeError):
    """Raised when DATABASE_URL is missing."""


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL environment variable is not set."
        )
    return url


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Yield a PostgreSQL connection with pgvector support registered."""

    conn = psycopg.connect(_get_database_url())
    try:
        register_vector(conn)
    except Exception:  # pragma: no cover - double registration is safe
        pass
    try:
        yield conn
    finally:
        conn.close()


def is_configured() -> bool:
    """Return True if DATABASE_URL is set."""

    return bool(os.getenv("DATABASE_URL"))
