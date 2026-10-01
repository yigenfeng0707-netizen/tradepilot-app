"""JWT auth helpers — skip when AUTH_DISABLED=1 or JWT_SECRET unset."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .db import fetchone, get_conn
from .services.pipeline import ensure_db

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain: str, stored_hash: str | None) -> bool:
    settings = get_settings()
    if not stored_hash:
        # seed demo user has null hash → accept DEMO_PASSWORD (default "demo")
        return plain == (settings.demo_password or "demo")
    return _hash_password(plain) == stored_hash or plain == stored_hash


def create_access_token(*, sub: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    secret = (settings.jwt_secret or "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET 未配置，无法签发令牌")
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(minutes=int(settings.jwt_expire_minutes or 1440)),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    secret = (settings.jwt_secret or "").strip()
    if not secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "JWT 未配置")
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效令牌") from exc


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    ensure_db()
    with get_conn() as conn:
        row = fetchone(
            conn,
            "SELECT id, tenant_id, username, display_name, role, password_hash, is_active "
            "FROM users WHERE username = ? LIMIT 1",
            (username.strip(),),
        )
    if not row or not row.get("is_active"):
        return None
    if not verify_password(password, row.get("password_hash")):
        return None
    return row


def login_and_issue_token(username: str, password: str) -> dict[str, Any]:
    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token = create_access_token(
        sub=str(user["username"]),
        extra={
            "uid": user["id"],
            "tenant_id": user["tenant_id"],
            "role": user.get("role") or "operator",
        },
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(get_settings().jwt_expire_minutes or 1440) * 60,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name"),
            "role": user.get("role"),
            "tenant_id": user["tenant_id"],
        },
    }


async def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Protect sensitive routes. No-op when auth is disabled."""
    settings = get_settings()
    if not settings.auth_required:
        return {"sub": "anonymous", "auth_skipped": True}
    if creds is None or not (creds.credentials or "").strip():
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "需要 Bearer JWT（先 POST /api/auth/login）",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    payload["auth_skipped"] = False
    return payload
