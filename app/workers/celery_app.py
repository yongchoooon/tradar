"""Celery application placeholder."""

try:  # pragma: no cover
    from celery import Celery
except Exception:  # Celery not installed
    class Celery:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass


celery_app = Celery("tradar")
