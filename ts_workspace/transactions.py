"""Crash-recoverable workspace transactions shared by control-plane engines."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Iterator

from .errors import ContractError
from .io import append_jsonl, now_iso, read_json, sha256_json, write_json, write_text_atomic


TRANSACTION_DIR = ".ts-transactions"
WORKSPACE_LOCK = ".ts-workspace.lock"


@contextmanager
def workspace_lock(root: Path) -> Iterator[None]:
    lock_path = root / WORKSPACE_LOCK
    lock_path.touch(mode=0o600, exist_ok=True)
    with lock_path.open("r+", encoding="utf-8") as handle:
        flock(handle.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(handle.fileno(), LOCK_UN)


def committed_decision_result(root: Path, decision: dict[str, Any]) -> dict[str, Any] | None:
    decision_id = _decision_id(decision)
    snapshot_path = root / "decisions" / f"{decision_id}.json"
    status = transaction_status(root, decision_id)
    if not snapshot_path.exists() and not status:
        return None
    if not snapshot_path.exists():
        raise ContractError(f"decision_id already has {status} transaction without decision snapshot: {decision_id}")
    existing = read_json(snapshot_path)
    if sha256_json(existing) != sha256_json(decision):
        raise ContractError(f"decision_id already exists with different content: {decision_id}")
    if status != "committed":
        raise ContractError(f"decision_id already exists without committed transaction: {decision_id}")
    result = decision_log_result(root, decision_id)
    if result is None:
        raise ContractError(f"committed decision is missing its decision_log result: {decision_id}")
    return result


def commit_transaction(
    root: Path,
    decision: dict[str, Any],
    changes: dict[Path, Any],
    result: dict[str, Any],
    *,
    directories: list[Path] | None = None,
) -> None:
    decision_id = _decision_id(decision)
    snapshot_ref = f"decisions/{decision_id}.json"
    snapshot_path = root / snapshot_ref
    status = transaction_status(root, decision_id)
    if snapshot_path.exists() or status:
        replay = committed_decision_result(root, decision)
        if replay is not None:
            return
        raise ContractError(f"decision_id is already in use: {decision_id}")

    complete_changes = dict(changes)
    complete_changes[snapshot_path] = decision
    decision_log = root / "decision_log.jsonl"
    complete_changes[decision_log] = _jsonl_with_row(
        decision_log,
        {
            "decision_id": decision_id,
            "created_at": now_iso(),
            "report_ref": decision.get("report_ref"),
            "operation_kinds": [
                operation.get("op")
                for operation in decision.get("operations", [])
                if isinstance(operation, dict)
            ],
            "operations_hash": sha256_json(decision.get("operations", [])),
            "basis_refs": decision.get("basis_refs", []),
            "snapshot_ref": snapshot_ref,
            "result": result,
        },
    )
    directories = directories or []
    relative_paths = sorted(path.relative_to(root).as_posix() for path in complete_changes)
    relative_directories = sorted(path.relative_to(root).as_posix() for path in directories)
    transaction_root = root / TRANSACTION_DIR / decision_id
    staged_root = transaction_root / "staged"
    backup_root = transaction_root / "backup"
    if transaction_root.exists():
        raise ContractError(f"transaction staging already exists: {decision_id}")

    staged_hashes: dict[str, str] = {}
    original_hashes: dict[str, str | None] = {}
    for target, value in complete_changes.items():
        relative = target.relative_to(root)
        staged = staged_root / relative
        _write_change(staged, value)
        key = relative.as_posix()
        staged_hashes[key] = _sha256_file(staged)
        original_hashes[key] = _sha256_file(target) if target.exists() else None

    prepare = {
        "decision_id": decision_id,
        "stage": "prepare",
        "created_at": now_iso(),
        "operation_kinds": [
            operation.get("op")
            for operation in decision.get("operations", [])
            if isinstance(operation, dict)
        ],
        "paths": relative_paths,
        "directories": relative_directories,
        "staged_sha256": staged_hashes,
        "original_sha256": original_hashes,
    }
    write_json(transaction_root / "prepare.json", prepare)
    append_jsonl(root / "transaction_log.jsonl", prepare)
    resolved = False
    try:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=False)
        for target in complete_changes:
            relative = target.relative_to(root)
            staged = staged_root / relative
            backup = backup_root / relative
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
        append_jsonl(
            root / "transaction_log.jsonl",
            {
                "decision_id": decision_id,
                "stage": "committed",
                "created_at": now_iso(),
                "operation_kinds": prepare.get("operation_kinds", []),
                "paths": relative_paths,
            },
        )
        resolved = True
    except Exception as mutation_error:
        try:
            _rollback(root, prepare)
            append_jsonl(
                root / "transaction_log.jsonl",
                {
                    "decision_id": decision_id,
                    "stage": "aborted",
                    "created_at": now_iso(),
                    "operation_kinds": prepare.get("operation_kinds", []),
                    "paths": relative_paths,
                },
            )
            resolved = True
        except Exception as rollback_error:
            raise ContractError(
                f"transaction {decision_id} failed and automatic rollback was incomplete; "
                f"recovery data remains under {TRANSACTION_DIR}/{decision_id}: {rollback_error}"
            ) from mutation_error
        raise
    finally:
        if resolved:
            shutil.rmtree(transaction_root, ignore_errors=True)
            _remove_empty_transaction_container(root)


def recover_incomplete_transactions(root: Path) -> None:
    transaction_root = root / TRANSACTION_DIR
    if not transaction_root.is_dir():
        return
    for directory in sorted(transaction_root.iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        decision_id = directory.name
        status = transaction_status(root, decision_id)
        if status == "committed":
            shutil.rmtree(directory)
            continue
        prepare_path = directory / "prepare.json"
        if not prepare_path.is_file():
            raise ContractError(f"transaction {decision_id} has no recoverable prepare record")
        prepare = read_json(prepare_path)
        _rollback(root, prepare)
        append_jsonl(
            root / "transaction_log.jsonl",
            {
                "decision_id": decision_id,
                "stage": "aborted",
                "created_at": now_iso(),
                "operation_kinds": prepare.get("operation_kinds", []),
                "paths": prepare.get("paths", []),
                "recovered": True,
            },
        )
        shutil.rmtree(directory)
    _remove_empty_transaction_container(root)


def transaction_status(root: Path, decision_id: str) -> str:
    status = ""
    path = root / "transaction_log.jsonl"
    if not path.is_file():
        return status
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("decision_id") == decision_id and row.get("stage") in {"prepare", "committed", "aborted"}:
            status = str(row["stage"])
    return status


def recorded_decision_ids(root: Path) -> set[str]:
    """Return Decision IDs already present in durable or recoverable history."""

    identifiers = {
        path.stem
        for path in (root / "decisions").glob("*.json")
        if path.is_file() and not path.is_symlink()
    }
    for name in ("decision_log.jsonl", "transaction_log.jsonl"):
        path = root / name
        for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            decision_id = row.get("decision_id") if isinstance(row, dict) else None
            if isinstance(decision_id, str) and decision_id:
                identifiers.add(decision_id)
    transaction_root = root / TRANSACTION_DIR
    if transaction_root.is_dir():
        identifiers.update(
            path.name
            for path in transaction_root.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
    return identifiers


def _remove_empty_transaction_container(root: Path) -> None:
    try:
        (root / TRANSACTION_DIR).rmdir()
    except OSError:
        pass


def decision_log_result(root: Path, decision_id: str) -> dict[str, Any] | None:
    path = root / "decision_log.jsonl"
    if not path.is_file():
        return None
    result = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("decision_id") == decision_id and isinstance(row.get("result"), dict):
            result = row["result"]
    return result


def _rollback(root: Path, prepare: dict[str, Any]) -> None:
    decision_id = str(prepare.get("decision_id") or "")
    if not decision_id or "/" in decision_id or "\\" in decision_id or ".." in decision_id:
        raise ContractError(f"transaction has an unsafe decision_id: {decision_id!r}")
    transaction_root = root / TRANSACTION_DIR / decision_id
    backup_root = transaction_root / "backup"
    staged_root = transaction_root / "staged"
    paths, staged_hashes, original_hashes = _recovery_metadata(root, prepare)
    for relative in paths:
        target = root / relative
        backup = backup_root / relative
        staged_hash = staged_hashes[relative.as_posix()]
        original_hash = original_hashes[relative.as_posix()]
        if backup.exists():
            if original_hash is None or _sha256_file(backup) != original_hash:
                raise ContractError(f"transaction {decision_id} backup is invalid: {relative}")
            if target.exists() and _sha256_file(target) != staged_hash:
                raise ContractError(f"transaction {decision_id} target changed after prepare: {relative}")
        elif original_hash is not None:
            if not target.exists() or _sha256_file(target) != original_hash:
                raise ContractError(f"transaction {decision_id} is missing its backup: {relative}")
        elif target.exists() and _sha256_file(target) != staged_hash:
            raise ContractError(f"transaction {decision_id} created target changed after prepare: {relative}")

    for relative in reversed(paths):
        target = root / relative
        backup = backup_root / relative
        original_hash = original_hashes[relative.as_posix()]
        if backup.exists():
            target.unlink(missing_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        elif original_hash is None:
            target.unlink(missing_ok=True)
        (staged_root / relative).unlink(missing_ok=True)
    for value in reversed(prepare.get("directories", [])):
        try:
            (root / str(value)).rmdir()
        except OSError:
            pass


def _recovery_metadata(
    root: Path,
    prepare: dict[str, Any],
) -> tuple[list[Path], dict[str, str], dict[str, str | None]]:
    raw_paths = prepare.get("paths")
    staged = prepare.get("staged_sha256")
    originals = prepare.get("original_sha256")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ContractError("transaction has no recovery paths")
    if not isinstance(staged, dict) or not isinstance(originals, dict):
        raise ContractError("transaction recovery hashes are missing")
    paths = [_safe_relative(root, str(value)) for value in raw_paths]
    keys = {path.as_posix() for path in paths}
    if set(staged) != keys or set(originals) != keys:
        raise ContractError("transaction recovery hashes do not cover every path")
    for key in keys:
        if not _is_sha256(staged[key]):
            raise ContractError(f"transaction staged hash is invalid: {key}")
        if originals[key] is not None and not _is_sha256(originals[key]):
            raise ContractError(f"transaction original hash is invalid: {key}")
    for value in prepare.get("directories", []):
        _safe_relative(root, str(value))
    return paths, staged, originals


def _safe_relative(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ContractError(f"unsafe transaction path: {value}")
    target = (root / relative).resolve()
    if target == root or root not in target.parents:
        raise ContractError(f"transaction path escapes workspace: {value}")
    return relative


def _decision_id(decision: dict[str, Any]) -> str:
    value = decision.get("decision_id")
    if not isinstance(value, str) or not value:
        raise ContractError("decision_id is required")
    return value


def _write_change(path: Path, value: Any) -> None:
    if isinstance(value, str):
        write_text_atomic(path, value)
    else:
        write_json(path, value)


def _jsonl_with_row(path: Path, row: dict[str, Any]) -> str:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    return existing + json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.split(":", 1)[1]
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
