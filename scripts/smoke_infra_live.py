#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live infra smoke — REQUIRES Redis + MinIO (docker compose up -d).

Fails clearly if Docker infra is down. Asserts:
  - Redis broker reachable
  - MinIO bucket reachable
  - Celery async sample completes
  - At least one object lands in MinIO (PDF or upload)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Load .env so CELERY/MinIO match the running API when present
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass

# Force live expectations for this script (overrides unset defaults)
os.environ.setdefault("CELERY_ENABLED", "1")
os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
os.environ.setdefault("MINIO_ENDPOINT", "127.0.0.1:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "tradepilot")
os.environ.setdefault("MINIO_SECURE", "0")
os.environ.setdefault("AUTH_DISABLED", "1")

API = os.environ.get("TRADEPILOT_API", "http://127.0.0.1:8787").rstrip("/")


def _fail(msg: str, notes: dict | None = None) -> int:
    payload = {"ok": False, "error": msg, "notes": notes or {}}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("INFRA_LIVE_FAILED")
    print("Hint: docker compose up -d   # Redis :6379 + MinIO :9000/:9001")
    return 1


def _check_redis() -> tuple[bool, str]:
    try:
        import redis

        url = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
        r = redis.Redis.from_url(url, socket_connect_timeout=2)
        return r.ping() is True, "pong"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]


def _check_minio() -> tuple[bool, str, list[str]]:
    try:
        from minio import Minio

        endpoint = os.environ["MINIO_ENDPOINT"].strip()
        client = Minio(
            endpoint,
            access_key=os.environ["MINIO_ACCESS_KEY"].strip(),
            secret_key=os.environ["MINIO_SECRET_KEY"].strip(),
            secure=os.environ.get("MINIO_SECURE", "0").strip() in {"1", "true", "yes"},
        )
        bucket = os.environ.get("MINIO_BUCKET", "tradepilot")
        if not client.bucket_exists(bucket):
            return False, f"bucket_missing:{bucket}", []
        names = [o.object_name for o in client.list_objects(bucket, recursive=True)]
        return True, bucket, names
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200], []


def main() -> int:
    notes: dict = {"api": API}
    checks: list[tuple[str, bool]] = []

    redis_ok, redis_detail = _check_redis()
    notes["redis"] = redis_detail
    if not redis_ok:
        return _fail("Redis not reachable on broker URL (is docker compose up?)", notes)
    checks.append(("redis_up", True))

    minio_ok, minio_detail, before_objs = _check_minio()
    notes["minio"] = minio_detail
    notes["objects_before"] = len(before_objs)
    if not minio_ok:
        return _fail("MinIO not reachable / bucket missing (is docker compose up?)", notes)
    checks.append(("minio_up", True))

    # Health via HTTP (API must be running with CELERY_ENABLED=1 + MinIO env)
    try:
        import httpx

        h = httpx.get(f"{API}/api/health", timeout=10)
        health = h.json()
        notes["health"] = {
            "celery": health.get("celery"),
            "storage": health.get("storage"),
            "auth_required": health.get("auth_required"),
        }
        checks.append(("health_ok", h.status_code == 200 and health.get("ok") is True))
        checks.append(("celery_enabled", bool((health.get("celery") or {}).get("enabled"))))
        checks.append(("celery_broker_up", bool((health.get("celery") or {}).get("broker_up"))))
        storage = health.get("storage") or {}
        mode = str(storage.get("mode") or "")
        checks.append(("storage_minio", "minio" in mode and storage.get("enabled") is True))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"API health failed — start uvicorn with CELERY/MinIO env: {exc}", notes)

    # Async sample
    try:
        import httpx

        r = httpx.post(f"{API}/api/orders/sample?async=1", timeout=30)
        body = r.json()
        notes["enqueue"] = {k: body.get(k) for k in ("async", "task_id", "status", "poll_url", "ok")}
        task_id = body.get("task_id")
        if not task_id:
            return _fail(
                "async enqueue did not return task_id (Celery worker running? CELERY_ENABLED=1?)",
                notes,
            )
        checks.append(("async_enqueued", True))

        result_body = None
        for i in range(120):
            time.sleep(2)
            st = httpx.get(f"{API}/api/tasks/{task_id}", timeout=15)
            result_body = st.json()
            status = result_body.get("status")
            notes["poll_last"] = {"i": i, "status": status, "ready": result_body.get("ready")}
            if result_body.get("ready"):
                break
        else:
            return _fail("async task timed out waiting for SUCCESS", notes)

        checks.append(("async_ready", result_body.get("ready") is True))
        checks.append(("async_success", result_body.get("successful") is True or result_body.get("status") == "SUCCESS"))
        result = result_body.get("result") or {}
        notes["order_no"] = result.get("order_no")
        notes["storage_mode"] = (result.get("storage") or {}).get("mode")
        notes["pdf_count"] = len(result.get("pdf_paths") or {})
        checks.append(("async_has_order", bool(result.get("order_no"))))
        checks.append(
            (
                "async_storage_minio",
                "minio" in str((result.get("storage") or {}).get("mode") or ""),
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"async sample/poll failed: {exc}", notes)

    # Objects in MinIO after pipeline
    minio_ok2, _, after_objs = _check_minio()
    notes["objects_after"] = len(after_objs)
    notes["sample_objects"] = after_objs[:12]
    new_objs = [o for o in after_objs if o not in set(before_objs)]
    notes["new_objects"] = new_objs[:12]
    has_pdf_or_upload = any(
        o.endswith(".pdf") or o.startswith("uploads/") or o.startswith("outputs/") for o in after_objs
    )
    checks.append(("minio_has_objects", minio_ok2 and (len(after_objs) > 0) and has_pdf_or_upload))

    failed = [n for n, ok in checks if not ok]
    summary = {"checks": {n: ok for n, ok in checks}, "failed": failed, "notes": notes}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failed:
        print("INFRA_LIVE_FAILED")
        return 1
    print("INFRA_LIVE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
