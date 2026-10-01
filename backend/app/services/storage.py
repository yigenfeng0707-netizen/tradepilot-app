"""Optional MinIO object storage — falls back to local data/ when unset or down."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger("tradepilot.storage")

_client: Any | None = None
_client_failed = False


def minio_enabled() -> bool:
    return get_settings().minio_configured and not _client_failed


def _get_client():
    global _client, _client_failed
    if _client_failed:
        return None
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.minio_configured:
        return None
    try:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint.strip(),
            access_key=settings.minio_access_key.strip(),
            secret_key=settings.minio_secret_key.strip(),
            secure=settings.minio_use_tls,
        )
        bucket = settings.minio_bucket or "tradepilot"
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        _client = client
        logger.info("MinIO ready bucket=%s endpoint=%s", bucket, settings.minio_endpoint)
        return _client
    except Exception as exc:  # noqa: BLE001
        _client_failed = True
        logger.warning("MinIO unavailable, using local files: %s", exc)
        return None


def reset_minio_state() -> None:
    """Test helper — clear cached failure so next call re-probes."""
    global _client, _client_failed
    _client = None
    _client_failed = False


def object_key_for_path(local_path: Path | str) -> str:
    """Map local path under data/ to object key."""
    settings = get_settings()
    path = Path(local_path).resolve()
    data_root = (settings.upload_dir.parent).resolve()  # data/
    try:
        rel = path.relative_to(data_root)
        return rel.as_posix()
    except ValueError:
        return Path(local_path).name


def put_file(local_path: Path | str, *, object_name: str | None = None) -> dict[str, Any]:
    """Upload local file to MinIO when enabled. Always keeps local file."""
    path = Path(local_path)
    meta: dict[str, Any] = {
        "local_path": str(path),
        "minio": False,
        "object": None,
    }
    client = _get_client()
    if client is None or not path.is_file():
        return meta
    settings = get_settings()
    key = object_name or object_key_for_path(path)
    try:
        client.fput_object(settings.minio_bucket or "tradepilot", key, str(path))
        meta["minio"] = True
        meta["object"] = key
        meta["bucket"] = settings.minio_bucket
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO put failed for %s: %s", path, exc)
    return meta


def put_bytes(data: bytes, object_name: str, *, content_type: str = "application/octet-stream") -> dict[str, Any]:
    meta: dict[str, Any] = {"minio": False, "object": object_name}
    client = _get_client()
    if client is None:
        return meta
    settings = get_settings()
    try:
        client.put_object(
            settings.minio_bucket or "tradepilot",
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        meta["minio"] = True
        meta["bucket"] = settings.minio_bucket
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO put_bytes failed: %s", exc)
    return meta


def get_object_bytes(object_name: str) -> bytes | None:
    client = _get_client()
    if client is None:
        return None
    settings = get_settings()
    try:
        resp = client.get_object(settings.minio_bucket or "tradepilot", object_name)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO get failed for %s: %s", object_name, exc)
        return None


def download_to_path(object_name: str, dest: Path) -> bool:
    client = _get_client()
    if client is None:
        return False
    settings = get_settings()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        client.fget_object(settings.minio_bucket or "tradepilot", object_name, str(dest))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO download failed: %s", exc)
        return False


def storage_status() -> dict[str, Any]:
    settings = get_settings()
    if not settings.minio_configured:
        return {"enabled": False, "mode": "local", "reason": "MINIO_ENDPOINT unset"}
    client = _get_client()
    if client is None:
        return {"enabled": False, "mode": "local", "reason": "connection_failed"}
    return {
        "enabled": True,
        "mode": "minio+local",
        "endpoint": settings.minio_endpoint,
        "bucket": settings.minio_bucket,
    }
