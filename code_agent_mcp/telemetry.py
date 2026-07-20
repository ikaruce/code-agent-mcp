from __future__ import annotations

import csv
import getpass
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .jobs import DB_PATH, _ensure_dirs


TELEMETRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    job_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    model TEXT,
    prompt_len INTEGER NOT NULL,
    cwd TEXT NOT NULL,
    context_file_count INTEGER NOT NULL,
    dispatched_at TEXT NOT NULL,
    finished_at TEXT,
    elapsed_ms INTEGER,
    exit_code INTEGER,
    final_state TEXT,
    result_len INTEGER,
    user TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_dispatched_at ON telemetry(dispatched_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


class Telemetry:
    def __init__(self, db_path: Optional[Path] = None):
        _ensure_dirs()
        # Lazy default so monkeypatched telemetry.DB_PATH is honored by tests.
        resolved = db_path if db_path is not None else DB_PATH
        self._conn = sqlite3.connect(str(resolved), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(TELEMETRY_SCHEMA)

    def record_dispatch(
        self,
        job_id: str,
        agent: str,
        prompt_len: int,
        cwd: str,
        context_file_count: int,
        model: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO telemetry "
            "(job_id, agent, model, prompt_len, cwd, context_file_count, dispatched_at, user) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, agent, model, prompt_len, cwd, context_file_count, _now_iso(), _current_user()),
        )

    def record_finish(
        self,
        job_id: str,
        final_state: str,
        exit_code: Optional[int],
        result_len: int,
    ) -> None:
        row = self._conn.execute(
            "SELECT dispatched_at FROM telemetry WHERE job_id=?", (job_id,)
        ).fetchone()
        elapsed_ms: Optional[int] = None
        if row is not None:
            try:
                start = datetime.strptime(row["dispatched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
                elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            except ValueError:
                elapsed_ms = None
        self._conn.execute(
            "UPDATE telemetry SET finished_at=?, elapsed_ms=?, exit_code=?, "
            "final_state=?, result_len=? WHERE job_id=?",
            (_now_iso(), elapsed_ms, exit_code, final_state, result_len, job_id),
        )

    def export_csv(self, since_iso: Optional[str] = None) -> str:
        if since_iso is not None:
            rows = self._conn.execute(
                "SELECT * FROM telemetry WHERE dispatched_at >= ? ORDER BY dispatched_at ASC",
                (since_iso,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM telemetry ORDER BY dispatched_at ASC"
            ).fetchall()
        if not rows:
            return ""
        buf = io.StringIO()
        writer = csv.writer(buf)
        cols = list(rows[0].keys())
        writer.writerow(cols)
        for r in rows:
            writer.writerow([r[c] for c in cols])
        return buf.getvalue()

    def prune_older_than_days(self, days: int) -> int:
        cur = self._conn.execute(
            "DELETE FROM telemetry WHERE dispatched_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        return cur.rowcount
