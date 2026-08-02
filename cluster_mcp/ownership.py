"""Persistent MCP-principal ownership for submitted scheduler jobs."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


class JobOwnershipStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_ownership (
                  job_id TEXT PRIMARY KEY,
                  principal TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  submitted_at TEXT NOT NULL,
                  metadata_json TEXT NOT NULL
                )
                """
            )
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection
        except sqlite3.Error as exc:
            raise ConfigurationError("Job ownership database is unavailable") from exc

    def record(
        self,
        job_id: str,
        *,
        principal: str,
        actor: str,
        metadata: dict[str, Any],
    ) -> None:
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        submitted_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO job_ownership
                          (job_id, principal, actor, submitted_at, metadata_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (job_id, principal, actor, submitted_at, encoded),
                    )
            except sqlite3.Error as exc:
                raise ConfigurationError(
                    f"Job {job_id} was submitted but its MCP ownership could not be recorded"
                ) from exc

    def principal_for(self, job_id: str) -> str | None:
        with self._lock:
            try:
                with self._connect() as connection:
                    row = connection.execute(
                        "SELECT principal FROM job_ownership WHERE job_id = ?", (job_id,)
                    ).fetchone()
            except sqlite3.Error as exc:
                raise ConfigurationError("Job ownership database could not be queried") from exc
        return str(row[0]) if row is not None else None

    def filter_owned(self, job_ids: list[str], *, principal: str) -> set[str]:
        if not job_ids:
            return set()
        with self._lock:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT job_id FROM job_ownership WHERE principal = ?", (principal,)
                    ).fetchall()
            except sqlite3.Error as exc:
                raise ConfigurationError("Job ownership database could not be queried") from exc
        selected = set(job_ids)
        return {str(row[0]) for row in rows if str(row[0]) in selected}
