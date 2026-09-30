"""SQLite helpers + schema bootstrap."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings


def _db_path() -> Path:
    settings = get_settings()
    # sqlite:///D:/... or sqlite:///./...
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    return get_settings().upload_dir.parent / "tradepilot.db"


def connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings = get_settings()
    sql = settings.schema_sql.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.executescript(sql)


def fetchone(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def execute(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    cur = conn.execute(sql, params)
    return int(cur.lastrowid or 0)
