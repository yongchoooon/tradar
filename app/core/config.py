"""Application configuration placeholders.

This module defines the :class:`Settings` class which would normally derive
from :class:`pydantic.BaseSettings` to load environment variables.  To keep the
examples runnable in environments without Pydantic installed, we provide a
minimal fallback implementation.
"""

try:  # pragma: no cover - optional dependency
    from pydantic import BaseSettings
except Exception:  # Pydantic is not available
    class BaseSettings:  # type: ignore
        """Very small stand‑in used when Pydantic isn't installed."""


class Settings(BaseSettings):
    """Basic configuration values for the application."""

    app_name: str = "tradar"


settings = Settings()
