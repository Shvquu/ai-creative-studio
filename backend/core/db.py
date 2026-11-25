"""SQLite persistence (jobs, assets, cost ledger).

Local-first: a single file in ``data/studio.db`` with WAL journaling. Access is
serialised with a re-entrant lock; queries are tiny so they run inline.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  resource TEXT NOT NULL,
  params TEXT NOT NULL,
  result TEXT,
  error TEXT,
  progress REAL NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 1,
  provider TEXT,
  parent_id TEXT,
  retry_of TEXT,
  project TEXT,
  label TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  mime TEXT,
  size_bytes INTEGER,
  sha256 TEXT,
  width INTEGER,
  height INTEGER,
  duration_s REAL,
  fps REAL,
  created_at TEXT NOT NULL,
  job_id TEXT,
  provider TEXT,
  model TEXT,
  prompt TEXT,
  negative_prompt TEXT,
  seed INTEGER,
  params TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  favorite INTEGER NOT NULL DEFAULT 0,
  rating INTEGER,
  project TEXT,
  quality TEXT,
  source TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
CREATE INDEX IF NOT EXISTS idx_assets_created ON assets(created_at);
CREATE INDEX IF NOT EXISTS idx_assets_job ON assets(job_id);
CREATE TABLE IF NOT EXISTS cost_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT,
  operation TEXT NOT NULL,
  count INTEGER NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  job_id TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def from_json(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.rowcount

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.executemany(sql, rows)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def fetchone(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def fetchall(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
