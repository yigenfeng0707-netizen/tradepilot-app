"""Celery application — optional; CELERY_ENABLED=0 keeps sync pipeline."""
from __future__ import annotations

from celery import Celery

from .config import get_settings

settings = get_settings()

celery_app = Celery(
    "tradepilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
)

# Worker: celery -A app.celery_app.celery_app worker --loglevel=info
# (run from backend/ so package `app` resolves)
celery_app.conf.imports = ("app.tasks",)
