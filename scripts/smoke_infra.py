#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2+ infra smoke: auth-disabled path + JWT unit + graceful Celery/MinIO skips."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Ensure local demo defaults before importing app settings
os.environ.setdefault("AUTH_DISABLED", "1")
os.environ.setdefault("CELERY_ENABLED", "0")
# Clear MinIO so local path is exercised
for k in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
    os.environ.pop(k, None)


def main() -> int:
    from app.auth import create_access_token, decode_token, login_and_issue_token
    from app.config import get_settings
    from app.services import storage as object_store
    from app.services.pipeline import load_sample_po, run_pipeline
    from app.tasks import celery_available, enqueue_pipeline

    checks: list[tuple[str, bool]] = []
    notes: dict = {}

    # 1) Auth disabled by default
    s = get_settings()
    checks.append(("auth_disabled_default", not s.auth_required))

    # 2) Sync pipeline still works (auth not involved in direct call)
    text, name = load_sample_po()
    result = run_pipeline(raw_text=text, original_filename=f"infra-{name}")
    checks.append(("pipeline_sync_ok", bool(result.get("ok"))))
    notes["order_no"] = result.get("order_no")
    notes["storage_mode"] = (result.get("storage") or {}).get("mode")

    # 3) Storage falls back to local when MinIO unset
    st = object_store.storage_status()
    checks.append(("minio_local_fallback", st.get("mode") == "local" and not st.get("enabled")))

    # 4) Celery disabled → enqueue returns None
    checks.append(("celery_off", not s.celery_on))
    queued = enqueue_pipeline(raw_text=text, original_filename="skip.txt")
    checks.append(("enqueue_skipped", queued is None))
    notes["celery_available"] = celery_available()

    # 5) JWT issue/verify with temporary secret (does not mutate process auth_required permanently)
    with mock.patch.dict(os.environ, {"JWT_SECRET": "smoke-infra-secret", "AUTH_DISABLED": "0"}, clear=False):
        # pydantic settings cached? get_settings() re-reads each call — good
        from importlib import reload
        import app.config as cfg

        reload(cfg)
        import app.auth as auth_mod

        reload(auth_mod)
        s2 = cfg.get_settings()
        checks.append(("auth_required_when_secret", s2.auth_required))
        token = auth_mod.create_access_token(sub="demo", extra={"uid": 1})
        payload = auth_mod.decode_token(token)
        checks.append(("jwt_roundtrip", payload.get("sub") == "demo"))
        login = auth_mod.login_and_issue_token("demo", "demo")
        checks.append(("login_demo", bool(login.get("access_token"))))

    # restore settings for any further use
    from importlib import reload
    import app.config as cfg2
    import app.auth as auth2

    reload(cfg2)
    reload(auth2)

    # 6) FastAPI TestClient: protected route open when auth disabled
    try:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        h = client.get("/api/health")
        checks.append(("health_ok", h.status_code == 200 and h.json().get("ok")))
        checks.append(("health_auth_flag", h.json().get("auth_required") is False))
        sample = client.post("/api/orders/sample")
        # may be slow with LLM; accept 200 with order or ok
        body = sample.json() if sample.headers.get("content-type", "").startswith("application/json") else {}
        checks.append(
            (
                "api_sample_no_auth",
                sample.status_code == 200 and (body.get("ok") is True or body.get("order_id")),
            )
        )
        notes["api_sample_status"] = sample.status_code
    except Exception as exc:  # noqa: BLE001
        checks.append(("api_sample_no_auth", False))
        notes["api_error"] = str(exc)[:200]

    failed = [n for n, ok in checks if not ok]
    summary = {"checks": {n: ok for n, ok in checks}, "failed": failed, "notes": notes}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failed:
        print("INFRA_SMOKE_FAILED")
        return 1
    print("INFRA_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
