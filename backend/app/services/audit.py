"""INSERT-only audit log with SHA256 hash chain."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..db import execute, fetchone


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_audit(
    conn,
    *,
    tenant_id: int,
    actor: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> str:
    prev = fetchone(
        conn,
        "SELECT entry_hash FROM audit_logs WHERE tenant_id=? ORDER BY id DESC LIMIT 1",
        (tenant_id,),
    )
    prev_hash = prev["entry_hash"] if prev else "GENESIS"
    detail_json = json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)
    material = f"{prev_hash}|{tenant_id}|{actor}|{action}|{entity_type}|{entity_id}|{detail_json}"
    entry_hash = _hash(material)
    execute(
        conn,
        """
        INSERT INTO audit_logs
          (tenant_id, actor, action, entity_type, entity_id, detail_json, prev_hash, entry_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tenant_id, actor, action, entity_type, entity_id, detail_json, prev_hash, entry_hash),
    )
    return entry_hash
