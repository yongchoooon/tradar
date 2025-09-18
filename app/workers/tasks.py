"""Celery task placeholders."""

from .celery_app import celery_app


@celery_app.task  # type: ignore[attr-defined]
def dummy_task() -> str:  # pragma: no cover
    return "ok"
