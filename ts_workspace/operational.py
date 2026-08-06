"""Read-only indexing for noncanonical calculation and agent-run state."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .io import read_json, sha256_json


def operational_snapshot(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    files = _operational_files(root_path)
    agent_runs = agent_run_index(root_path)
    pending_controls = _pending_controls(root_path, files)
    unresolved_controls = _unresolved_controls(root_path, files)
    ambiguous_submissions = [
        row for row in unresolved_controls if row.get("error_class") == "submission_ambiguous"
    ]
    ambiguous_cancellations = [
        row for row in unresolved_controls if row.get("error_class") == "cancellation_ambiguous"
    ]
    retryable_controls = [
        row for row in unresolved_controls if row.get("retry_disposition") == "retry_same_submission"
    ]
    return {
        "operational_revision": sha256_json(
            {
                "files": [
                    {"path": path.relative_to(root_path).as_posix(), "sha256": _sha256_file(path)}
                    for path in files
                ]
            }
        ),
        "agent_runs": agent_runs,
        "pending_controls": pending_controls,
        "unresolved_controls": unresolved_controls,
        "ambiguous_submissions": ambiguous_submissions,
        "ambiguous_cancellations": ambiguous_cancellations,
        "retryable_controls": retryable_controls,
        "operational_summary": {
            "tracked_file_count": len(files),
            "calculation_file_count": sum(1 for path in files if "agent-runs" not in path.parts),
            "agent_run_count": len(agent_runs),
            "agent_run_failed_count": sum(1 for row in agent_runs if row.get("status") == "failed"),
            "agent_run_pending_count": sum(1 for row in agent_runs if row.get("status") == "pending"),
            "control_pending_count": len(pending_controls),
            "control_unresolved_count": len(unresolved_controls),
            "ambiguous_submission_count": len(ambiguous_submissions),
            "ambiguous_cancellation_count": len(ambiguous_cancellations),
            "control_retryable_count": len(retryable_controls),
        },
    }


def agent_run_index(root: str | Path) -> list[dict[str, Any]]:
    root_path = Path(root)
    run_dirs = [
        *root_path.glob("nodes/*/agent-runs/*"),
        *root_path.glob("operations/agent-runs/*"),
    ]
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs, key=lambda path: path.relative_to(root_path).as_posix()):
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        task = _read_or_empty(run_dir / "task.json")
        run = _read_or_empty(run_dir / "run.json")
        result = _read_or_empty(run_dir / "result.json")
        error = run.get("error") if isinstance(run.get("error"), dict) else {}
        scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        rows.append(
            {
                "task_id": task.get("task_id") or run_dir.name,
                "role": task.get("role"),
                "authority": task.get("authority"),
                "operation": task.get("operation"),
                "status": run.get("status") or "pending",
                "node_ids": scope.get("node_ids", []),
                "run_ref": run_dir.relative_to(root_path).as_posix(),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "summary": result.get("summary"),
                "error_code": error.get("code"),
                "error_message": error.get("message"),
            }
        )
    return rows


def _operational_files(root: Path) -> list[Path]:
    patterns = (
        "nodes/*/attempts/*/status.json",
        "nodes/*/attempts/*/*_guard.json",
        "nodes/*/attempts/*/*_result.json",
        "nodes/*/attempts/*/*_reconciliation.json",
        "nodes/*/attempts/*/*_receipt.json",
        "nodes/*/attempts/*/outputs/calculation_result.json",
        "nodes/*/remote/calculations/*/status.json",
        "nodes/*/remote/calculations/*/*_guard.json",
        "nodes/*/remote/calculations/*/*_result.json",
        "nodes/*/remote/calculations/*/*_reconciliation.json",
        "nodes/*/remote/calculations/*/*_receipt.json",
        "nodes/*/outputs/calculations/*/calculation_result.json",
        "nodes/*/agent-runs/*/*.json",
        "operations/agent-runs/*/*.json",
    )
    files = {
        path
        for pattern in patterns
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _pending_controls(root: Path, files: list[Path]) -> list[dict[str, str]]:
    pending: list[dict[str, str]] = []
    for guard in files:
        if not guard.name.endswith("_guard.json"):
            continue
        parsed = _control_record_name(guard.name, "guard")
        if parsed is None:
            continue
        operation, attempt, stem = parsed
        reconciliation = guard.parent / f"{operation}_reconciliation.json"
        if reconciliation.is_file() and not reconciliation.is_symlink():
            continue
        result = guard.parent / f"{stem}_result.json"
        if result.is_file() and not result.is_symlink():
            continue
        row = {
            "operation": operation,
            "intent_id": guard.parent.name,
            "guard_ref": guard.relative_to(root).as_posix(),
        }
        if attempt > 1:
            row["attempt"] = str(attempt)
        pending.append(row)
    return pending


def _unresolved_controls(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    latest_attempts: dict[tuple[Path, str], int] = {}
    for path in files:
        kind = "guard" if path.name.endswith("_guard.json") else "result"
        parsed = _control_record_name(path.name, kind)
        if parsed is None:
            continue
        operation, attempt, _stem = parsed
        key = (path.parent, operation)
        latest_attempts[key] = max(attempt, latest_attempts.get(key, 0))

    unresolved: list[dict[str, Any]] = []
    for result_path in files:
        if not result_path.name.endswith("_result.json"):
            continue
        parsed = _control_record_name(result_path.name, "result")
        if parsed is None:
            continue
        operation, attempt, _stem = parsed
        reconciliation = result_path.parent / f"{operation}_reconciliation.json"
        if reconciliation.is_file() and not reconciliation.is_symlink():
            continue
        if latest_attempts.get((result_path.parent, operation)) != attempt:
            continue
        result = _read_or_empty(result_path)
        control = result.get("control") if isinstance(result.get("control"), dict) else {}
        state = result.get("state")
        error_class = result.get("error_class")
        effect_outcome = control.get("effect_outcome")
        retry_disposition = control.get("retry_disposition")
        unresolved_state = effect_outcome == "unknown" or state == "unknown"
        retryable_failure = retry_disposition == "retry_same_submission"
        ambiguous_error = error_class in {"submission_ambiguous", "cancellation_ambiguous"}
        if not (unresolved_state or retryable_failure or ambiguous_error):
            continue
        row: dict[str, Any] = {
            "operation": operation,
            "intent_id": result_path.parent.name,
            "attempt": attempt,
            "result_ref": result_path.relative_to(root).as_posix(),
            "state": state,
            "error_class": error_class,
            "effect_outcome": effect_outcome or ("unknown" if unresolved_state else "failed"),
            "retry_disposition": retry_disposition or (
                "reconcile_only" if unresolved_state or ambiguous_error else None
            ),
            "job_id": result.get("job_id"),
        }
        unresolved.append(row)
    return unresolved


def _control_record_name(name: str, kind: str) -> tuple[str, int, str] | None:
    suffix = f"_{kind}.json"
    if not name.endswith(suffix):
        return None
    stem = name.removesuffix(suffix)
    if "_attempt_" not in stem:
        return (stem, 1, stem) if stem in {"submit", "cancel"} else None
    operation, token = stem.rsplit("_attempt_", 1)
    if operation not in {"submit", "cancel"} or len(token) != 4 or not token.isdigit():
        return None
    attempt = int(token)
    if attempt < 2:
        return None
    return operation, attempt, stem


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_or_empty(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
