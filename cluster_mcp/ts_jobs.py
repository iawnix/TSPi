"""TS-specific submission validation and idempotency records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ConfigurationError, SecurityError


_SUBMISSION_ID = re.compile(r"^tsjob_[A-Za-z0-9][A-Za-z0-9_.-]{5,121}$")
_INTENT_ID = re.compile(r"^calc_[A-Za-z0-9_.-]{1,123}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BACKENDS = frozenset({"gaussian", "xtb", "crest", "ase_neb", "qbics_dmecp"})
_REPLAYABLE_STATES = frozenset({"submitted"})
_SENSITIVE_ENV_KEY = re.compile(
    r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTHORIZATION|API_KEY|PRIVATE_KEY)(?:$|_)"
)


def validate_ts_submission_id(value: Any) -> str:
    return _required_match(value, _SUBMISSION_ID, "submission_id")


def validate_ts_submission_request(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SecurityError("TS submission request must be an object")
    allowed = {
        "schema_version",
        "submission_id",
        "intent_id",
        "intent_digest",
        "node_id",
        "backend",
        "script_path",
        "workdir",
        "input_manifest",
        "expected_artifacts",
        "execution",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SecurityError(f"TS submission request contains unknown fields: {', '.join(unknown)}")
    if value.get("schema_version") != "ts-cluster-job/1":
        raise SecurityError("TS submission schema_version must be ts-cluster-job/1")

    submission_id = validate_ts_submission_id(value.get("submission_id"))
    intent_id = _required_match(value.get("intent_id"), _INTENT_ID, "intent_id")
    intent_digest = _required_match(value.get("intent_digest"), _DIGEST, "intent_digest")
    node_id = _required_match(value.get("node_id"), _NODE_ID, "node_id")
    backend = value.get("backend")
    if backend not in _BACKENDS:
        raise SecurityError(f"Unsupported TS backend: {backend}")
    workdir = _relative_path(value.get("workdir"), "workdir", allow_dot=True)
    script_path = _relative_path(value.get("script_path"), "script_path")
    _require_descendant(script_path, workdir, "script_path")

    raw_manifest = value.get("input_manifest")
    if not isinstance(raw_manifest, list) or not 1 <= len(raw_manifest) <= 64:
        raise SecurityError("input_manifest must contain between 1 and 64 files")
    manifest: list[dict[str, Any]] = []
    seen_inputs: set[str] = set()
    for index, item in enumerate(raw_manifest):
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise SecurityError(f"input_manifest[{index}] must contain path, size, and sha256")
        path = _relative_path(item.get("path"), f"input_manifest[{index}].path")
        _require_descendant(path, workdir, f"input_manifest[{index}].path")
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 1 << 30:
            raise SecurityError(f"input_manifest[{index}].size is invalid")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise SecurityError(f"input_manifest[{index}].sha256 is invalid")
        if path in seen_inputs:
            raise SecurityError(f"input_manifest contains duplicate path: {path}")
        seen_inputs.add(path)
        manifest.append({"path": path, "size": size, "sha256": digest})
    if script_path not in seen_inputs:
        raise SecurityError("script_path must be present in input_manifest")

    raw_expected = value.get("expected_artifacts")
    if not isinstance(raw_expected, list) or not 1 <= len(raw_expected) <= 32:
        raise SecurityError("expected_artifacts must contain between 1 and 32 paths")
    expected: list[str] = []
    for index, item in enumerate(raw_expected):
        path = _relative_path(item, f"expected_artifacts[{index}]")
        _require_descendant(path, workdir, f"expected_artifacts[{index}]")
        if path in seen_inputs:
            raise SecurityError(f"expected artifact overlaps an input: {path}")
        if path in expected:
            raise SecurityError(f"expected_artifacts contains duplicate path: {path}")
        expected.append(path)

    execution = validate_ts_execution(value.get("execution"))

    return {
        "schema_version": "ts-cluster-job/1",
        "submission_id": submission_id,
        "intent_id": intent_id,
        "intent_digest": intent_digest,
        "node_id": node_id,
        "backend": backend,
        "script_path": script_path,
        "workdir": workdir,
        "input_manifest": manifest,
        "expected_artifacts": expected,
        "execution": execution,
    }


def request_digest(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class TSSubmissionStore:
    """Persist one irreversible scheduler submission decision per submission_id."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ts_submissions (
                  submission_id TEXT PRIMARY KEY,
                  principal TEXT NOT NULL,
                  request_digest TEXT NOT NULL,
                  request_json TEXT NOT NULL,
                  state TEXT NOT NULL,
                  job_id TEXT,
                  result_json TEXT,
                  error_text TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
        os.chmod(self.path, 0o600)

    def reserve(self, request: dict[str, Any], *, principal: str) -> dict[str, Any] | None:
        submission_id = str(request["submission_id"])
        digest = request_digest(request)
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"))
        timestamp = _now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT principal, request_digest, state, result_json FROM ts_submissions "
                "WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO ts_submissions "
                    "(submission_id, principal, request_digest, request_json, state, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'reserved', ?, ?)",
                    (submission_id, principal, digest, encoded, timestamp, timestamp),
                )
                return None
            existing_principal, existing_digest, state, result_json = row
            if existing_principal != principal or existing_digest != digest:
                raise SecurityError("submission_id is already bound to a different request")
            if state in _REPLAYABLE_STATES and result_json:
                return _stored_object(result_json, "TS submission result")
            if state == "rejected":
                cursor = connection.execute(
                    "UPDATE ts_submissions SET state = 'reserved', result_json = NULL, "
                    "error_text = NULL, updated_at = ? WHERE submission_id = ? AND state = 'rejected'",
                    (timestamp, submission_id),
                )
                if cursor.rowcount != 1:
                    raise ConfigurationError(
                        f"TS submission retry reservation failed: {submission_id} rejected->reserved"
                    )
                return None
            raise SecurityError(
                f"submission_id is in state {state}; automatic resubmission is forbidden"
            )

    def replay(self, request: dict[str, Any], *, principal: str) -> dict[str, Any] | None:
        submission_id = str(request["submission_id"])
        digest = request_digest(request)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT principal, request_digest, state, result_json FROM ts_submissions "
                "WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        if row is None:
            return None
        existing_principal, existing_digest, state, result_json = row
        if existing_principal != principal or existing_digest != digest:
            raise SecurityError("submission_id is already bound to a different request")
        if state in _REPLAYABLE_STATES and result_json:
            return _stored_object(result_json, "TS submission result")
        if state == "rejected":
            return None
        raise SecurityError(
            f"submission_id is in state {state}; automatic resubmission is forbidden"
        )

    def mark_submitting(self, submission_id: str) -> None:
        self._transition(submission_id, from_state="reserved", to_state="submitting")

    def mark_rejected(
        self,
        submission_id: str,
        *,
        result: dict[str, Any],
        error: BaseException,
    ) -> None:
        self._transition(
            submission_id,
            from_state="reserved",
            to_state="rejected",
            result=result,
            error_text=f"{type(error).__name__}: {error}"[:2000],
        )

    def mark_scheduler_accepted(self, submission_id: str, *, job_id: str) -> None:
        self._transition(
            submission_id,
            from_state="submitting",
            to_state="scheduler_accepted",
            job_id=job_id,
        )

    def mark_submitted(self, submission_id: str, *, job_id: str, result: dict[str, Any]) -> None:
        self._transition(
            submission_id,
            from_state="scheduler_accepted",
            to_state="submitted",
            job_id=job_id,
            result=result,
        )

    def mark_ambiguous(self, submission_id: str, error: BaseException) -> None:
        current = self.get(submission_id)
        state = str(current["state"])
        if state not in {"submitting", "scheduler_accepted"}:
            raise ConfigurationError(
                f"TS submission cannot become ambiguous from state {state}"
            )
        self._transition(
            submission_id,
            from_state=state,
            to_state="ambiguous",
            error_text=f"{type(error).__name__}: {error}"[:2000],
        )

    def begin_cancel(
        self,
        submission_id: str,
        *,
        principal: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT principal, state, job_id, result_json FROM ts_submissions "
                "WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            if row is None:
                raise SecurityError(f"Unknown TS submission: {submission_id}")
            existing_principal, state, existing_job_id, result_json = row
            if existing_principal != principal or existing_job_id != job_id:
                raise SecurityError("TS cancellation binding changed before scheduler control")
            if state == "cancelled" and result_json:
                return _stored_object(result_json, "TS cancellation result")
            if state not in {"submitted", "ambiguous"}:
                raise SecurityError(
                    f"TS submission cannot be cancelled from state {state}; "
                    "automatic cancellation replay is forbidden"
                )
            cursor = connection.execute(
                "UPDATE ts_submissions SET state = 'cancelling', error_text = NULL, updated_at = ? "
                "WHERE submission_id = ? AND state = ?",
                (_now(), submission_id, state),
            )
            if cursor.rowcount != 1:
                raise ConfigurationError(
                    f"TS cancellation reservation failed: {submission_id} {state}->cancelling"
                )
        return None

    def mark_cancelled(self, submission_id: str, result: dict[str, Any]) -> None:
        self._transition(
            submission_id,
            from_state="cancelling",
            to_state="cancelled",
            result=result,
        )

    def mark_cancellation_ambiguous(self, submission_id: str, error: BaseException) -> None:
        self._transition(
            submission_id,
            from_state="cancelling",
            to_state="cancellation_ambiguous",
            error_text=f"{type(error).__name__}: {error}"[:2000],
        )

    def get(self, submission_id: str) -> dict[str, Any]:
        record = self.find(submission_id)
        if record is None:
            raise SecurityError(f"Unknown TS submission: {submission_id}")
        return record

    def find(self, submission_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT principal, request_digest, request_json, state, job_id, result_json, "
                "error_text, created_at, updated_at FROM ts_submissions WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        if row is None:
            return None
        request = _stored_object(row[2], "TS submission request")
        result = _stored_object(row[5], "TS submission result") if row[5] else None
        return {
            "schema_version": "ts-cluster-submission/1",
            "submission_id": submission_id,
            "principal": row[0],
            "request_digest": row[1],
            "request": request,
            "state": row[3],
            "job_id": row[4],
            "result": result,
            "error": row[6],
            "created_at": row[7],
            "updated_at": row[8],
        }

    def health(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM ts_submissions").fetchone()
        return {"available": True, "submission_count": int(row[0]) if row else 0}

    def _transition(
        self,
        submission_id: str,
        *,
        from_state: str,
        to_state: str,
        job_id: str | None = None,
        result: dict[str, Any] | None = None,
        error_text: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE ts_submissions SET state = ?, job_id = COALESCE(?, job_id), "
                "result_json = COALESCE(?, result_json), error_text = ?, updated_at = ? "
                "WHERE submission_id = ? AND state = ?",
                (
                    to_state,
                    job_id,
                    (
                        json.dumps(result, sort_keys=True, separators=(",", ":"))
                        if result is not None
                        else None
                    ),
                    error_text,
                    _now(),
                    submission_id,
                    from_state,
                ),
            )
            if cursor.rowcount != 1:
                raise ConfigurationError(
                    f"TS submission transition failed: {submission_id} {from_state}->{to_state}"
                )

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection
        except sqlite3.Error as exc:
            raise ConfigurationError("TS submission database is unavailable") from exc


def _required_match(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SecurityError(f"Invalid {label}")
    return value


def _stored_object(encoded: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Stored {label} is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Stored {label} is invalid")
    return value


def _relative_path(value: Any, label: str, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\n" in value or "\r" in value:
        raise SecurityError(f"Invalid {label}")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        if allow_dot and value == ".":
            return value
        raise SecurityError(f"{label} must be a normalized workspace-relative path")
    if candidate.parts[0] == ".cluster_mcp":
        raise SecurityError(f"{label} uses a reserved path")
    return candidate.as_posix()


def _require_descendant(path: str, directory: str, label: str) -> None:
    if directory == ".":
        return
    candidate = PurePosixPath(path)
    root = PurePosixPath(directory)
    if candidate == root or root not in candidate.parents:
        raise SecurityError(f"{label} must be inside workdir")


def validate_ts_execution(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SecurityError("execution must be an object")
    keys = {
        "queue",
        "nodes",
        "ncpus",
        "memory",
        "walltime",
        "ngpus",
        "mpiprocs",
        "ompthreads",
        "host",
        "place",
        "environment",
        "gpu_devices",
    }
    if set(value) != keys:
        raise SecurityError("execution must contain the complete ts-cluster-job/1 resource shape")
    queue = value.get("queue")
    if not isinstance(queue, str) or not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", queue):
        raise SecurityError("execution.queue is invalid")
    memory = value.get("memory")
    walltime = value.get("walltime")
    if not isinstance(memory, str) or not memory:
        raise SecurityError("execution.memory is invalid")
    if not isinstance(walltime, str) or not walltime:
        raise SecurityError("execution.walltime is invalid")
    for key in ("nodes", "ncpus", "ngpus"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int):
            raise SecurityError(f"execution.{key} must be an integer")
    for key in ("mpiprocs", "ompthreads"):
        item = value.get(key)
        if item is not None and (isinstance(item, bool) or not isinstance(item, int)):
            raise SecurityError(f"execution.{key} must be an integer or null")
    for key in ("host", "place"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise SecurityError(f"execution.{key} must be a string or null")
    environment = value.get("environment")
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in environment.items()
    ):
        raise SecurityError("execution.environment must contain string values")
    forbidden_environment = sorted(
        key
        for key in environment
        if key.startswith("TS_CLUSTER_MCP_") or _SENSITIVE_ENV_KEY.search(key)
    )
    if forbidden_environment:
        raise SecurityError(
            "execution.environment contains host connection or credential fields: "
            + ", ".join(forbidden_environment)
        )
    gpu_devices = value.get("gpu_devices")
    if not isinstance(gpu_devices, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in gpu_devices
    ):
        raise SecurityError("execution.gpu_devices must contain integers")
    return {
        "queue": queue,
        "nodes": value["nodes"],
        "ncpus": value["ncpus"],
        "memory": memory,
        "walltime": walltime,
        "ngpus": value["ngpus"],
        "mpiprocs": value["mpiprocs"],
        "ompthreads": value["ompthreads"],
        "host": value["host"],
        "place": value["place"],
        "environment": dict(environment),
        "gpu_devices": list(gpu_devices),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
