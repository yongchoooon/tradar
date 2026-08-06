from __future__ import annotations

import pytest

from app.services.worker_settings import get_worker_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_worker_settings.cache_clear()
    yield
    get_worker_settings.cache_clear()


def test_worker_settings_are_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("DESKTOP_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("DESKTOP_WORKER_ID_ALLOWLIST", "desktop-1, desktop-2")
    monkeypatch.setenv("SEARCH_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("TOPK_DEFAULT", "18")

    settings = get_worker_settings()

    assert settings.token == "worker-secret"
    assert settings.allowlist == {"desktop-1", "desktop-2"}
    assert settings.search_timeout_seconds == 120.0
    assert settings.topk_default == 18


def test_worker_token_is_required_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("DESKTOP_WORKER_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="DESKTOP_WORKER_TOKEN"):
        get_worker_settings()
