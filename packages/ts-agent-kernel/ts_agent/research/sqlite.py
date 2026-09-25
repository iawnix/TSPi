"""Workspace-local SQLite persistence for Research Kernel metadata.

Raw Attempts and Artifacts stay on the filesystem.  This repository stores the
ResearchMap snapshot and Claim-scoped decision records in one short-transaction
database so map updates and lifecycle records can be committed atomically.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .decisions import AttemptInterpretation, StrategyPlan, StrategyReview, TurnCheckpoint
from .model import ResearchMap, ResearchModelError


SQLITE_FILE = "research.db"
SQLITE_SCHEMA = "research-sqlite/1"


class ResearchSqliteError(RuntimeError):
    """Raised when the SQLite Research Kernel store cannot commit a change."""


class ResearchSqliteRepository:
    """Persist Kernel metadata without storing raw scientific files in SQLite."""

    def __init__(self, root: str | Path, *, database: str | Path | None = None):
        self.root = Path(root).expanduser().absolute()
        self.path = Path(database).expanduser().absolute() if database is not None else self.root / SQLITE_FILE

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO kernel_meta(key, value) VALUES (?, ?)",
                ("schema_version", SQLITE_SCHEMA),
            )

    def bootstrap_from_json(self, research_map: ResearchMap) -> dict[str, Any]:
        """Create the SQLite snapshot from an existing JSON ResearchMap."""

        research_map.validate()
        self.initialize()
        with self._transaction() as connection:
            existing = connection.execute("SELECT map_id, revision FROM research_map WHERE singleton = 1").fetchone()
            if existing is not None:
                if existing["map_id"] != research_map.map_id or existing["revision"] != research_map.revision:
                    raise ResearchSqliteError("SQLite store already contains a different ResearchMap snapshot")
                return {"schema_version": "research-sqlite-bootstrap/1", "created": False, "revision": research_map.revision}
            self._write_map(connection, research_map)
            self._write_event(connection, "bootstrap", research_map.revision, {"map_id": research_map.map_id})
        return {"schema_version": "research-sqlite-bootstrap/1", "created": True, "revision": research_map.revision}

    def save_snapshot(self, research_map: ResearchMap) -> dict[str, Any]:
        """Replace the current SQLite map snapshot at an already assigned revision."""

        research_map.validate()
        self.initialize()
        with self._transaction() as connection:
            current = connection.execute("SELECT map_id, revision FROM research_map WHERE singleton = 1").fetchone()
            if current is not None:
                if current["map_id"] != research_map.map_id:
                    raise ResearchSqliteError("ResearchMap map_id does not match SQLite store")
                if research_map.revision < int(current["revision"]):
                    raise ResearchSqliteError("SQLite ResearchMap revision cannot move backwards")
            self._write_map(connection, research_map)
        return {
            "schema_version": "research-sqlite-snapshot-result/1",
            "map_id": research_map.map_id,
            "revision": research_map.revision,
        }

    def load_map(self) -> ResearchMap:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM research_map WHERE singleton = 1").fetchone()
        if row is None:
            raise ResearchSqliteError(f"SQLite ResearchMap has not been bootstrapped: {self.path}")
        try:
            return ResearchMap.from_dict(json.loads(row["payload"]))
        except (json.JSONDecodeError, ResearchModelError) as exc:
            raise ResearchSqliteError(f"SQLite ResearchMap is invalid: {exc}") from exc

    def commit(
        self,
        research_map: ResearchMap,
        *,
        expected_revision: int | None = None,
        event_id: str | None = None,
        request_digest: str | None = None,
        rationale: str | None = None,
        basis_refs: Iterable[str] = (),
        strategy_plans: Iterable[StrategyPlan] = (),
        strategy_reviews: Iterable[StrategyReview] = (),
        interpretations: Iterable[AttemptInterpretation] = (),
        checkpoint: TurnCheckpoint | None = None,
    ) -> dict[str, Any]:
        """Atomically commit map state and Claim/lifecycle records."""

        research_map.validate()
        plans = list(strategy_plans)
        reviews = list(strategy_reviews)
        interpretation_rows = list(interpretations)
        for record in (*plans, *reviews, *interpretation_rows):
            record.validate(research_map)
        if checkpoint is not None:
            checkpoint.validate(research_map)
        basis = list(basis_refs)
        if any(not isinstance(item, str) or not item.strip() for item in basis):
            raise ResearchSqliteError("basis_refs must contain non-empty strings")
        if event_id is not None and (not isinstance(event_id, str) or not event_id.strip()):
            raise ResearchSqliteError("event_id must be a non-empty string")

        self.initialize()
        with self._transaction() as connection:
            current = connection.execute("SELECT map_id, revision FROM research_map WHERE singleton = 1").fetchone()
            if current is None:
                if research_map.revision != 0:
                    raise ResearchSqliteError("first SQLite ResearchMap revision must be zero")
                current_revision = -1
            else:
                current_revision = int(current["revision"])
                if current["map_id"] != research_map.map_id:
                    raise ResearchSqliteError("ResearchMap map_id does not match SQLite store")
            if event_id is not None:
                replay = connection.execute("SELECT map_revision, payload FROM kernel_events WHERE event_id = ?", (event_id,)).fetchone()
                if replay is not None:
                    replay_payload = json.loads(replay["payload"])
                    previous_digest = replay_payload.get("request_digest")
                    if request_digest is not None and previous_digest is not None and previous_digest != request_digest:
                        raise ResearchSqliteError(f"event_id {event_id} is already bound to another decision request")
                    return replay_payload.get("result", replay_payload)
            if expected_revision is not None and expected_revision != current_revision:
                raise ResearchSqliteError(
                    f"ResearchMap revision mismatch: expected {expected_revision}, current {current_revision}"
                )
            next_revision = research_map.revision if current_revision < 0 else current_revision + 1
            if current_revision >= 0 and research_map.revision not in {current_revision, next_revision}:
                raise ResearchSqliteError(
                    f"ResearchMap revision must be current ({current_revision}) or next ({next_revision})"
                )
            saved = ResearchMap.from_dict(research_map.to_dict())
            saved.revision = next_revision
            if checkpoint is not None and checkpoint.map_revision != next_revision:
                checkpoint = TurnCheckpoint.from_dict({
                    **checkpoint.to_dict(),
                    "map_revision": next_revision,
                })
            self._write_map(connection, saved)
            created_ids: list[str] = []
            for plan in plans:
                self._insert_record(connection, "strategy_plans", plan.id, plan.claim_id, plan.created_at, plan.to_dict())
                created_ids.append(plan.id)
            for review in reviews:
                self._insert_record(connection, "strategy_reviews", review.id, review.claim_id, review.created_at, review.to_dict())
                created_ids.append(review.id)
            for interpretation in interpretation_rows:
                self._insert_record(connection, "attempt_interpretations", interpretation.id, interpretation.claim_id, interpretation.created_at, interpretation.to_dict())
                created_ids.append(interpretation.id)
            if checkpoint is not None:
                self._insert_record(connection, "turn_checkpoints", checkpoint.id, checkpoint.claim_ids[0] if checkpoint.claim_ids else None, checkpoint.created_at, checkpoint.to_dict())
                connection.executemany(
                    "INSERT INTO turn_checkpoint_claims(checkpoint_id, claim_id) VALUES (?, ?)",
                    [(checkpoint.id, claim_id) for claim_id in checkpoint.claim_ids],
                )
                created_ids.append(checkpoint.id)
            result = {
                "schema_version": "research-sqlite-commit-result/1",
                "map_id": saved.map_id,
                "revision": saved.revision,
                "created_ids": created_ids,
                "operation_count": len(created_ids) + 1,
            }
            self._write_event(
                connection,
                event_id or f"revision:{saved.revision}",
                saved.revision,
                {
                    "result": result,
                    "rationale": rationale,
                    "basis_refs": basis,
                    "request_digest": request_digest,
                },
            )
        return result

    def has_event(self, event_id: str) -> bool:
        """Return whether an event id has already been committed."""

        if not isinstance(event_id, str) or not event_id:
            return False
        self.initialize()
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM kernel_events WHERE event_id = ? LIMIT 1", (event_id,)
            ).fetchone() is not None

    def list_records(self, record_type: str, *, claim_id: str | None = None) -> list[dict[str, Any]]:
        table = _record_table(record_type)
        self.initialize()
        with self._connection() as connection:
            if claim_id is None:
                rows = connection.execute(f"SELECT payload FROM {table} ORDER BY created_at, id").fetchall()
            elif record_type == "turn_checkpoint":
                rows = connection.execute(
                    """SELECT checkpoints.payload
                       FROM turn_checkpoints AS checkpoints
                       JOIN turn_checkpoint_claims AS refs ON refs.checkpoint_id = checkpoints.id
                       WHERE refs.claim_id = ? ORDER BY checkpoints.created_at, checkpoints.id""",
                    (claim_id,),
                ).fetchall()
            else:
                rows = connection.execute(f"SELECT payload FROM {table} WHERE claim_id = ? ORDER BY created_at, id", (claim_id,)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def export_snapshot(self) -> dict[str, Any]:
        research_map = self.load_map()
        return {
            "schema_version": "research-sqlite-snapshot/1",
            "research_map": research_map.to_dict(),
            "claim_decisions": {
                "strategy_plans": self.list_records("strategy_plan"),
                "strategy_reviews": self.list_records("strategy_review"),
                "attempt_interpretations": self.list_records("attempt_interpretation"),
                "turn_checkpoints": self.list_records("turn_checkpoint"),
            },
        }

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _write_map(connection: sqlite3.Connection, research_map: ResearchMap) -> None:
        payload = json.dumps(research_map.to_dict(), ensure_ascii=False, sort_keys=True)
        connection.execute(
            """INSERT INTO research_map(singleton, map_id, revision, payload, updated_at)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(singleton) DO UPDATE SET map_id=excluded.map_id,
                 revision=excluded.revision, payload=excluded.payload, updated_at=excluded.updated_at""",
            (research_map.map_id, research_map.revision, payload, _now()),
        )

    @staticmethod
    def _insert_record(connection: sqlite3.Connection, table: str, record_id: str, claim_id: str | None, created_at: str, value: dict[str, Any]) -> None:
        try:
            connection.execute(
                f"INSERT INTO {table}(id, claim_id, created_at, payload) VALUES (?, ?, ?, ?)",
                (record_id, claim_id, created_at, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )
        except sqlite3.IntegrityError as exc:
            raise ResearchSqliteError(f"{table} record already exists: {record_id}") from exc

    @staticmethod
    def _write_event(connection: sqlite3.Connection, event_id: str, revision: int, value: dict[str, Any]) -> None:
        try:
            connection.execute(
                "INSERT INTO kernel_events(event_id, map_revision, payload, created_at) VALUES (?, ?, ?, ?)",
                (event_id, revision, json.dumps(value, ensure_ascii=False, sort_keys=True), _now()),
            )
        except sqlite3.IntegrityError as exc:
            raise ResearchSqliteError(f"event already exists: {event_id}") from exc


def _record_table(record_type: str) -> str:
    tables = {
        "strategy_plan": "strategy_plans",
        "strategy_review": "strategy_reviews",
        "attempt_interpretation": "attempt_interpretations",
        "turn_checkpoint": "turn_checkpoints",
    }
    try:
        return tables[record_type]
    except KeyError as exc:
        raise ResearchSqliteError(f"unsupported decision record type: {record_type}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS kernel_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_map (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    map_id TEXT NOT NULL UNIQUE,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_plans (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_reviews (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempt_interpretations (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turn_checkpoints (
    id TEXT PRIMARY KEY,
    claim_id TEXT,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turn_checkpoint_claims (
    checkpoint_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    PRIMARY KEY (checkpoint_id, claim_id)
);
CREATE TABLE IF NOT EXISTS kernel_events (
    event_id TEXT PRIMARY KEY,
    map_revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_plans_claim_created ON strategy_plans(claim_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_strategy_reviews_claim_created ON strategy_reviews(claim_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_interpretations_claim_created ON attempt_interpretations(claim_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_claim_created ON turn_checkpoints(claim_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_claim_refs ON turn_checkpoint_claims(claim_id, checkpoint_id);
"""


__all__ = ["ResearchSqliteError", "ResearchSqliteRepository", "SQLITE_FILE", "SQLITE_SCHEMA"]
