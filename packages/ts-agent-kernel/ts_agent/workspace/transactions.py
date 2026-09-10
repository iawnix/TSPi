"""Crash-recoverable workspace transactions shared by control-plane engines."""

from __future__ import annotations

import hashlib
import errno
import json
import os
import shutil
import stat
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Iterator

from .errors import ContractError
from ts_agent.io import append_jsonl, now_iso, read_json, sha256_json, write_json, write_text_atomic
from .path_safety import has_symlink_component, lexical_path, path_has_symlink
from .refs import DECISION_ID


TRANSACTION_DIR = ".ts-transactions"
WORKSPACE_LOCK = ".ts-workspace.lock"


@contextmanager
def workspace_lock(root: Path) -> Iterator[None]:
    root = lexical_path(root)
    if path_has_symlink(root):
        raise ContractError(f"workspace root contains a symbolic link: {root}")
    lock_path = root / WORKSPACE_LOCK
    if has_symlink_component(root, lock_path) or lock_path.is_symlink():
        raise ContractError(f"workspace lock contains a symbolic link: {lock_path}")
    # ``Path.touch`` follows a link if one is installed between the check
    # above and the open.  The workspace lock is a mutation boundary, so use
    # O_NOFOLLOW when available and verify the descriptor itself as well.
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ContractError(f"cannot open workspace lock safely: {lock_path}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ContractError(f"workspace lock must be a regular file: {lock_path}")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
            descriptor = -1
            flock(handle.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(handle.fileno(), LOCK_UN)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def committed_decision_result(root: Path, decision: dict[str, Any]) -> dict[str, Any] | None:
    root = lexical_path(root)
    if path_has_symlink(root):
        raise ContractError(f"workspace root contains a symbolic link: {root}")
    decision_id = _decision_id(decision)
    snapshot_path = root / "decisions" / f"{decision_id}.json"
    _assert_physical_target(root, snapshot_path, "decision snapshot")
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
    root = lexical_path(root)
    if path_has_symlink(root):
        raise ContractError(f"workspace root contains a symbolic link: {root}")
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
    _assert_physical_target(root, decision_log, "decision log")
    transaction_log = root / "transaction_log.jsonl"
    _assert_physical_target(root, transaction_log, "transaction log")
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
    for target in complete_changes:
        _assert_physical_target(root, target, "transaction target")
    for directory in directories:
        _assert_physical_target(root, directory, "transaction directory")
    relative_paths = sorted(path.relative_to(root).as_posix() for path in complete_changes)
    relative_directories = sorted(path.relative_to(root).as_posix() for path in directories)
    transaction_root = root / TRANSACTION_DIR / decision_id
    staged_root = transaction_root / "staged"
    backup_root = transaction_root / "backup"
    if has_symlink_component(root, transaction_root) or transaction_root.is_symlink():
        raise ContractError(f"transaction staging path contains a symbolic link: {transaction_root}")
    if transaction_root.exists():
        raise ContractError(f"transaction staging already exists: {decision_id}")

    staged_hashes: dict[str, str] = {}
    original_hashes: dict[str, str | None] = {}
    for target, value in complete_changes.items():
        relative = target.relative_to(root)
        staged = staged_root / relative
        _assert_physical_target(root, staged, "transaction staging target")
        _write_change(staged, value)
        key = relative.as_posix()
        staged_hashes[key] = _sha256_file(staged)
        if has_symlink_component(root, target) or target.is_symlink():
            raise ContractError(f"transaction target contains a symbolic link: {relative.as_posix()}")
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
    prepare_path = transaction_root / "prepare.json"
    _assert_physical_target(root, prepare_path, "transaction prepare record")
    write_json(prepare_path, prepare)
    _assert_physical_target(root, transaction_log, "transaction log")
    append_jsonl(transaction_log, prepare)
    resolved = False
    try:
        for directory in directories:
            _assert_physical_target(root, directory, "transaction directory")
            directory.mkdir(parents=True, exist_ok=False)
        for target in complete_changes:
            relative = target.relative_to(root)
            staged = staged_root / relative
            backup = backup_root / relative
            _assert_physical_target(root, target, "transaction target")
            _assert_physical_target(root, backup, "transaction backup")
            if target.exists():
                if target.is_symlink():
                    raise ContractError(f"transaction target contains a symbolic link: {relative.as_posix()}")
                if not target.is_file():
                    raise ContractError(f"transaction target must be a regular file: {relative.as_posix()}")
                _assert_physical_target(root, backup.parent, "transaction backup parent")
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            _assert_physical_target(root, target.parent, "transaction target parent")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
        _assert_physical_target(root, transaction_log, "transaction log")
        append_jsonl(
            transaction_log,
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
            _assert_physical_target(root, transaction_log, "transaction log")
            append_jsonl(
                transaction_log,
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
            _cleanup_resolved_transaction(root, transaction_root)


def recover_incomplete_transactions(root: Path) -> None:
    root = lexical_path(root)
    if path_has_symlink(root):
        raise ContractError(f"workspace root contains a symbolic link: {root}")
    transaction_root = root / TRANSACTION_DIR
    if has_symlink_component(root, transaction_root) or transaction_root.is_symlink():
        raise ContractError(f"transaction directory contains a symbolic link: {transaction_root}")
    if not transaction_root.exists():
        return
    if transaction_root.is_symlink() or not transaction_root.is_dir():
        raise ContractError(f"transaction directory is not a physical directory: {transaction_root}")
    try:
        children = sorted(transaction_root.iterdir())
    except OSError as exc:
        raise ContractError(f"cannot inspect transaction directory: {transaction_root}: {exc}") from exc
    for directory in children:
        # Unknown children are not harmless cache files: silently skipping one
        # could leave an unfinished mutation outside the recovery scan.
        if directory.is_symlink():
            raise ContractError(f"transaction child contains a symbolic link: {directory}")
        if not directory.is_dir():
            raise ContractError(f"transaction child is not a directory: {directory}")
        if has_symlink_component(root, directory):
            raise ContractError(f"transaction path contains a symbolic link: {directory}")
        decision_id = directory.name
        status = transaction_status(root, decision_id)
        if status == "committed":
            _assert_physical_tree(directory, root)
            shutil.rmtree(directory)
            continue
        prepare_path = directory / "prepare.json"
        if has_symlink_component(root, prepare_path) or prepare_path.is_symlink() or not prepare_path.is_file():
            raise ContractError(f"transaction {decision_id} has no recoverable prepare record")
        try:
            prepare = read_json(prepare_path)
        except (OSError, ValueError) as exc:
            raise ContractError(f"transaction {decision_id} has an invalid prepare record: {exc}") from exc
        if not isinstance(prepare, dict):
            raise ContractError(f"transaction {decision_id} prepare record must be an object")
        if prepare.get("decision_id") != decision_id:
            raise ContractError(
                f"transaction {decision_id} prepare record has a mismatched decision_id"
            )
        _rollback(root, prepare)
        transaction_log = root / "transaction_log.jsonl"
        _assert_physical_target(root, transaction_log, "transaction log")
        append_jsonl(
            transaction_log,
            {
                "decision_id": decision_id,
                "stage": "aborted",
                "created_at": now_iso(),
                "operation_kinds": prepare.get("operation_kinds", []),
                "paths": prepare.get("paths", []),
                "recovered": True,
            },
        )
        _assert_physical_tree(directory, root)
        shutil.rmtree(directory)
    _remove_empty_transaction_container(root)


def transaction_status(root: Path, decision_id: str) -> str:
    status = ""
    path = root / "transaction_log.jsonl"
    if path_has_symlink(root) or has_symlink_component(root, path) or path.is_symlink():
        raise ContractError(f"transaction log contains a symbolic link: {path}")
    if not path.exists():
        return status
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"transaction log must be a regular file: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read transaction log: {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # A process can die after writing a partial final line.  Preserve
            # the historical tolerance for that recoverable tail, while
            # rejecting a valid JSON value with the wrong structural type.
            continue
        if not isinstance(row, dict):
            raise ContractError(
                f"transaction log row {line_number} must be a JSON object"
            )
        if row.get("decision_id") == decision_id and row.get("stage") in {"prepare", "committed", "aborted"}:
            status = str(row["stage"])
    return status


def recorded_decision_ids(root: Path) -> set[str]:
    """Return Decision IDs already present in durable or recoverable history."""

    root = lexical_path(root)
    if path_has_symlink(root):
        raise ContractError(f"workspace root contains a symbolic link: {root}")
    decisions_root = root / "decisions"
    if has_symlink_component(root, decisions_root) or decisions_root.is_symlink():
        raise ContractError(f"decision directory contains a symbolic link: {decisions_root}")
    if decisions_root.exists() and not decisions_root.is_dir():
        raise ContractError(f"decision directory is not a physical directory: {decisions_root}")
    identifiers = {
        path.stem
        for path in decisions_root.glob("*.json")
        if not has_symlink_component(root, path) and path.is_file() and not path.is_symlink()
    }
    for name in ("decision_log.jsonl", "transaction_log.jsonl"):
        path = root / name
        if has_symlink_component(root, path) or path.is_symlink():
            raise ContractError(f"{name} contains a symbolic link: {path}")
        if path.exists() and not path.is_file():
            raise ContractError(f"{name} must be a regular file: {path}")
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines() if path.is_file() else [],
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                raise ContractError(f"{name} row {line_number} must be a JSON object")
            decision_id = row.get("decision_id") if isinstance(row, dict) else None
            if isinstance(decision_id, str) and decision_id:
                identifiers.add(decision_id)
    transaction_root = root / TRANSACTION_DIR
    if has_symlink_component(root, transaction_root) or transaction_root.is_symlink():
        raise ContractError(f"transaction directory contains a symbolic link: {transaction_root}")
    if transaction_root.exists() and not transaction_root.is_dir():
        raise ContractError(f"transaction directory is not a physical directory: {transaction_root}")
    if transaction_root.is_dir():
        identifiers.update(
            path.name
            for path in transaction_root.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
    return identifiers


def _remove_empty_transaction_container(root: Path) -> None:
    container = root / TRANSACTION_DIR
    if has_symlink_component(root, container) or container.is_symlink():
        raise ContractError(f"transaction directory contains a symbolic link: {container}")
    try:
        container.rmdir()
    except FileNotFoundError:
        return
    except OSError as exc:
        # ENOTEMPTY is the normal result when another transaction is present;
        # all other failures must remain visible instead of being mistaken for
        # successful cleanup.
        if getattr(exc, "errno", None) == errno.ENOTEMPTY:
            return
        raise ContractError(f"cannot remove empty transaction directory: {container}: {exc}") from exc


def _cleanup_resolved_transaction(root: Path, transaction_root: Path) -> None:
    """Remove a committed/aborted transaction only after a physical recheck."""

    try:
        mode = transaction_root.lstat().st_mode
    except FileNotFoundError:
        _remove_empty_transaction_container(root)
        return
    except OSError as exc:
        raise ContractError(
            f"cannot inspect resolved transaction cleanup path: {transaction_root}: {exc}"
        ) from exc
    if stat.S_ISLNK(mode):
        raise ContractError(
            f"resolved transaction cleanup refused because path is a symbolic link: {transaction_root}"
        )
    if not stat.S_ISDIR(mode):
        raise ContractError(
            f"resolved transaction cleanup path is not a directory: {transaction_root}"
        )
    _assert_physical_tree(transaction_root, root)
    try:
        shutil.rmtree(transaction_root)
    except OSError as exc:
        raise ContractError(f"cannot remove resolved transaction: {transaction_root}: {exc}") from exc
    _remove_empty_transaction_container(root)


def decision_log_result(root: Path, decision_id: str) -> dict[str, Any] | None:
    path = root / "decision_log.jsonl"
    if path_has_symlink(root) or has_symlink_component(root, path) or path.is_symlink():
        raise ContractError(f"decision log contains a symbolic link: {path}")
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"decision log must be a regular file: {path}")
    result = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read decision log: {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            raise ContractError(f"decision log row {line_number} must be a JSON object")
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
    if path_has_symlink(root) or has_symlink_component(root, transaction_root):
        raise ContractError(f"transaction recovery path contains a symbolic link: {transaction_root}")
    paths, staged_hashes, original_hashes = _recovery_metadata(root, prepare)
    for relative in paths:
        target = root / relative
        backup = backup_root / relative
        staged = staged_root / relative
        _assert_physical_target(root, target, "transaction recovery target")
        _assert_physical_target(root, backup, "transaction recovery backup")
        _assert_physical_target(root, staged, "transaction recovery staging")
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
        staged = staged_root / relative
        original_hash = original_hashes[relative.as_posix()]
        if backup.exists():
            if backup.is_symlink():
                raise ContractError(f"transaction recovery backup is a symbolic link: {relative}")
            target.unlink(missing_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        elif original_hash is None:
            if target.is_symlink():
                raise ContractError(f"transaction recovery target is a symbolic link: {relative}")
            target.unlink(missing_ok=True)
        if staged.is_symlink():
            raise ContractError(f"transaction recovery staging is a symbolic link: {relative}")
        staged.unlink(missing_ok=True)
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
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or "\\" in value:
        raise ContractError(f"unsafe transaction path: {value}")
    target = root / relative
    if has_symlink_component(root, target) or target == root:
        raise ContractError(f"transaction path escapes workspace: {value}")
    return relative


def _assert_physical_target(root: Path, target: Path, label: str) -> None:
    """Ensure a transaction operation cannot follow a link under ``root``."""

    target = lexical_path(target)
    if has_symlink_component(root, target) or target.is_symlink():
        raise ContractError(f"{label} contains a symbolic link: {target}")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"{label} escapes workspace: {target}") from exc


def _assert_physical_tree(path: Path, root: Path) -> None:
    """Reject links anywhere in a transaction tree before deleting it."""

    if has_symlink_component(root, path) or path.is_symlink():
        raise ContractError(f"transaction tree contains a symbolic link: {path}")
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except FileNotFoundError as exc:
            raise ContractError(f"transaction tree changed while being inspected: {current}") from exc
        except OSError as exc:
            raise ContractError(f"cannot inspect transaction tree: {current}: {exc}") from exc
        for entry in entries:
            entry_path = Path(entry.path)
            if has_symlink_component(root, entry_path) or entry.is_symlink():
                raise ContractError(f"transaction tree contains a symbolic link: {entry_path}")
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                raise ContractError(f"cannot inspect transaction tree entry: {entry_path}: {exc}") from exc
            if is_directory:
                pending.append(entry_path)


def _decision_id(decision: dict[str, Any]) -> str:
    value = decision.get("decision_id")
    if not isinstance(value, str) or DECISION_ID.fullmatch(value) is None:
        raise ContractError("decision_id must match dec_<positive integer>")
    return value


def _write_change(path: Path, value: Any) -> None:
    if isinstance(value, str):
        write_text_atomic(path, value)
    else:
        write_json(path, value)


def _jsonl_with_row(path: Path, row: dict[str, Any]) -> str:
    if path.is_symlink():
        raise ContractError(f"JSONL path contains a symbolic link: {path}")
    if path.exists() and not path.is_file():
        raise ContractError(f"JSONL path must be a regular file: {path}")
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        raise ContractError(f"cannot read JSONL path: {path}: {exc}") from exc
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
