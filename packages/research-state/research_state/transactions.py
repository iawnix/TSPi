"""Single workspace transaction writer with durable redo and replay receipts.

A committed decision is durable *before* any public file is replaced. Readers
hold the same flock and replay an interrupted decision before observing state.
External commands must record intent and reconcile; this writer never claims
that a process, scheduler submission, or remote effect can be rolled back.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from fcntl import LOCK_EX, LOCK_UN, flock
from functools import wraps
from pathlib import Path
from typing import Any, Iterator

_LOCAL = threading.local()
_STAGING: ContextVar[tuple[Path, dict[str, Any]] | None] = ContextVar("state_transaction_staging", default=None)


class TransactionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise TransactionError("transaction_path_invalid")
    path = root / relative
    for part in [root, *path.relative_to(root).parents]:
        # Relative parents are checked explicitly below.
        if part == root and part.is_symlink():
            raise TransactionError("transaction_path_symlink")
    current = root
    for component in Path(relative).parts:
        current /= component
        if current.is_symlink():
            raise TransactionError("transaction_path_symlink")
    return path


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise TransactionError("transaction_path_symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_json(path: Path, value: Any) -> None:
    """Stage a State/projection write when inside a coordinated mutation."""
    path = Path(path)
    staging = _STAGING.get()
    if staging is None:
        _atomic_json(path, value)
        return
    root, writes = staging
    relative = path.relative_to(root).as_posix()
    _safe_path(root, relative)
    writes[relative] = copy.deepcopy(value)


class TransactionCoordinator:
    def __init__(self, root: str | Path):
        requested = Path(root).expanduser().absolute()
        if requested.resolve() != requested:
            raise TransactionError("workspace_root_symlink")
        self.root = requested
        self.journal = self.root / "operations" / "transactions"

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Reentrant per thread; a crashed process cannot leave a stale lock."""
        held = getattr(_LOCAL, "locks", None)
        if held is None:
            held = _LOCAL.locks = {}
        key = str(self.root)
        if key in held:
            yield
            return
        self.root.mkdir(parents=True, exist_ok=True)
        path = _safe_path(self.root, ".ts-workspace.lock")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise TransactionError("workspace_lock_not_regular")
            os.fchmod(descriptor, 0o600)
            flock(descriptor, LOCK_EX)
            held[key] = descriptor
            self._recover_locked()
            yield
        finally:
            held.pop(key, None)
            flock(descriptor, LOCK_UN)
            os.close(descriptor)

    def _receipt_path(self, request_id: str) -> Path:
        if not isinstance(request_id, str) or not request_id or len(request_id) > 512:
            raise TransactionError("transaction_request_id_invalid")
        return _safe_path(self.root, f"operations/transactions/{_digest(request_id)}.json")

    def _read(self, path: Path) -> dict[str, Any] | None:
        if path.is_symlink():
            raise TransactionError("transaction_path_symlink")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict) or value.get("schema_version") != "agent_transaction/1":
            raise TransactionError("transaction_journal_invalid")
        return value

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self.locked():
            return self._read(self._receipt_path(request_id))

    def _replay(self, path: Path, record: dict[str, Any]) -> dict[str, Any]:
        writes = record.get("writes")
        if not isinstance(writes, dict) or _digest(writes) != record.get("writes_digest"):
            raise TransactionError("transaction_writes_corrupt")
        for relative, value in writes.items():
            _atomic_json(_safe_path(self.root, relative), value)
        committed = {**record, "state": "committed", "committed_at": _now()}
        _atomic_json(path, committed)
        return committed

    def _recover_locked(self) -> list[dict[str, Any]]:
        journal = _safe_path(self.root, "operations/transactions")
        recovered = []
        if not journal.exists():
            return recovered
        for path in sorted(journal.glob("*.json")):
            record = self._read(path)
            if record and record.get("state") == "committing":
                recovered.append(self._replay(path, record))
        return recovered

    def recover(self) -> dict[str, Any]:
        # locked() always recovers before it yields, including ordinary reads.
        with self.locked():
            return {"recovered": True, "workspace_root": str(self.root)}

    def prepare(self, request_id: str, operation: str, payload: Any, *, writes: dict[str, Any], result: Any) -> dict[str, Any]:
        with self.locked():
            path = self._receipt_path(request_id)
            request_digest = _digest({"operation": operation, "payload": payload})
            previous = self._read(path)
            if previous:
                if previous["request_digest"] != request_digest:
                    raise TransactionError("transaction_id_reused")
                if previous["state"] != "pending":
                    return previous
            if not isinstance(writes, dict):
                raise TransactionError("transaction_writes_invalid")
            for relative in writes:
                _safe_path(self.root, relative)
                if relative.startswith("operations/transactions/") or relative == ".ts-workspace.lock":
                    raise TransactionError("transaction_reserved_path")
            record = {
                "schema_version": "agent_transaction/1", "transaction_id": f"txn_{_digest(request_id)}",
                "request_id": request_id, "operation": operation, "request_digest": request_digest,
                "state": "prepared", "prepared_at": _now(), "writes": writes,
                "writes_digest": _digest(writes), "result": result,
            }
            _atomic_json(path, record)
            return record

    def begin(self, request_id: str, operation: str, payload: Any) -> dict[str, Any]:
        with self.locked():
            path = self._receipt_path(request_id)
            request_digest = _digest({"operation": operation, "payload": payload})
            previous = self._read(path)
            if previous:
                if previous["request_digest"] != request_digest:
                    raise TransactionError("transaction_id_reused")
                return previous
            record = {
                "schema_version": "agent_transaction/1", "transaction_id": f"txn_{_digest(request_id)}",
                "request_id": request_id, "operation": operation, "request_digest": request_digest,
                "state": "pending", "created_at": _now(), "payload": payload,
            }
            _atomic_json(path, record)
            return record

    def commit(self, request_id: str) -> dict[str, Any]:
        with self.locked():
            path = self._receipt_path(request_id)
            record = self._read(path)
            if not record:
                raise TransactionError("transaction_not_found")
            if record["state"] == "committed":
                return record
            if record["state"] != "prepared":
                raise TransactionError("transaction_not_prepared")
            # Durable redo decision: after this fsync, recovery must roll forward.
            record = {**record, "state": "committing", "decision_at": _now()}
            _atomic_json(path, record)
            return self._replay(path, record)

    def abort(self, request_id: str) -> dict[str, Any]:
        with self.locked():
            path = self._receipt_path(request_id)
            record = self._read(path)
            if not record:
                raise TransactionError("transaction_not_found")
            if record["state"] == "committed":
                raise TransactionError("transaction_already_committed")
            record = {**record, "state": "aborted", "aborted_at": _now()}
            _atomic_json(path, record)
            return record

    def commit_files(self, request_id: str, operation: str, payload: Any, *, writes: dict[str, Any], result: Any) -> dict[str, Any]:
        with self.locked():
            self.prepare(request_id, operation, payload, writes=writes, result=result)
            return self.commit(request_id)


def state_transaction(operation: str):
    """Wrap a canonical mutation, stage its JSON writes, persist one receipt."""
    def decorate(fn):
        @wraps(fn)
        def invoke(root, request=None):
            request = request or {}
            coordinator = TransactionCoordinator(root)
            request_id = request.get("request_id") or request.get("transaction_id") or f"{operation}_{uuid.uuid4().hex}"
            payload = {key: value for key, value in request.items() if key not in {"root", "workspace_root"}}
            with coordinator.locked():
                previous = coordinator.get(request_id)
                if previous:
                    if previous["request_digest"] != _digest({"operation": operation, "payload": payload}):
                        raise TransactionError("transaction_id_reused")
                    if previous["state"] == "aborted":
                        raise TransactionError("transaction_aborted")
                    return coordinator.commit(request_id)["result"]
                writes: dict[str, Any] = {}
                token = _STAGING.set((coordinator.root, writes))
                try:
                    result = fn(root, request)
                finally:
                    _STAGING.reset(token)
                return coordinator.commit_files(request_id, operation, payload, writes=writes, result=result)["result"]
        return invoke
    return decorate
