"""Celery tasks wrapping the TradePilot pipeline."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .celery_app import celery_app

logger = logging.getLogger("tradepilot.tasks")


@celery_app.task(bind=True, name="tradepilot.run_pipeline")
def run_pipeline_task(
    self,
    *,
    raw_text: str | None = None,
    source_path: str | None = None,
    original_filename: str | None = None,
) -> dict[str, Any]:
    """Async wrapper around services.pipeline.run_pipeline."""
    self.update_state(state="STARTED", meta={"progress": 5, "stage": "start"})
    from .services.pipeline import run_pipeline

    kwargs: dict[str, Any] = {"original_filename": original_filename}
    if raw_text is not None:
        kwargs["raw_text"] = raw_text
    if source_path:
        kwargs["source_path"] = Path(source_path)
    self.update_state(state="STARTED", meta={"progress": 20, "stage": "pipeline"})
    result = run_pipeline(**kwargs)
    self.update_state(state="SUCCESS", meta={"progress": 100, "stage": "done"})
    return result


def celery_available() -> bool:
    """Probe broker; return False if Redis/Celery unreachable."""
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    if not settings.celery_on:
        return False
    try:
        with celery_app.connection_or_acquire() as conn:
            conn.ensure_connection(max_retries=1)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Celery broker unavailable: %s", exc)
        return False


def enqueue_pipeline(
    *,
    raw_text: str | None = None,
    source_path: str | None = None,
    original_filename: str | None = None,
) -> dict[str, Any] | None:
    """Enqueue if Celery enabled + broker up; else return None (caller runs sync)."""
    if not celery_available():
        return None
    async_result = run_pipeline_task.delay(
        raw_text=raw_text,
        source_path=str(source_path) if source_path else None,
        original_filename=original_filename,
    )
    return {
        "async": True,
        "task_id": async_result.id,
        "status": "PENDING",
        "poll_url": f"/api/tasks/{async_result.id}",
        "ws_url": f"/ws/tasks/{async_result.id}",
    }


def task_status(task_id: str) -> dict[str, Any]:
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    state = result.state or "PENDING"
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": state,
        "ready": result.ready(),
        "successful": bool(result.successful()) if result.ready() else None,
    }
    if state == "STARTED" and isinstance(result.info, dict):
        payload["meta"] = result.info
    if result.ready():
        if result.successful():
            payload["result"] = result.result
        else:
            payload["error"] = str(result.result)
    return payload
