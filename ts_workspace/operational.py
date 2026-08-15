"""Read-only projection of noncanonical v4 runtime state.

Canonical scientific state lives in the v4 registries.  Calculation attempts,
deterministic tool activities, advisory Review runs, and control receipts are
durable operational records, but they never become scientific support merely
because they appear in this projection.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .io import read_json, sha256_json


def operational_snapshot(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    files = _operational_files(root_path)
    activities = deterministic_activity_index(root_path)
    review_runs = review_run_index(root_path)
    pending_review_dispositions = review_disposition_obligations(review_runs)
    review_disposition_count = sum(1 for row in review_runs if row.get("root_disposition"))
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
        "deterministic_activities": activities,
        "review_runs": review_runs,
        "pending_review_dispositions": pending_review_dispositions,
        "review_disposition_count": review_disposition_count,
        "pending_controls": pending_controls,
        "unresolved_controls": unresolved_controls,
        "ambiguous_submissions": ambiguous_submissions,
        "ambiguous_cancellations": ambiguous_cancellations,
        "retryable_controls": retryable_controls,
        "operational_summary": {
            "tracked_file_count": len(files),
            "calculation_file_count": sum(1 for path in files if "attempts" in path.parts),
            "activity_count": len(activities),
            "activity_failed_count": sum(1 for row in activities if row.get("status") == "failed"),
            "activity_running_count": sum(1 for row in activities if row.get("status") == "running"),
            "review_run_count": len(review_runs),
            "review_run_failed_count": sum(1 for row in review_runs if row.get("status") == "failed"),
            "review_run_pending_count": sum(1 for row in review_runs if row.get("status") == "pending"),
            "review_disposition_count": review_disposition_count,
            "review_disposition_pending_count": len(pending_review_dispositions),
            "control_pending_count": len(pending_controls),
            "control_unresolved_count": len(unresolved_controls),
            "ambiguous_submission_count": len(ambiguous_submissions),
            "ambiguous_cancellation_count": len(ambiguous_cancellations),
            "control_retryable_count": len(retryable_controls),
        },
    }


def deterministic_activity_index(root: str | Path) -> list[dict[str, Any]]:
    """Index host-owned Compute, Render, and Report activity journals."""

    root_path = Path(root).expanduser().resolve()
    activity_dirs = [
        *root_path.glob("acts/*/activities/*"),
        *root_path.glob("operations/activities/*"),
    ]
    rows: list[dict[str, Any]] = []
    for activity_dir in sorted(activity_dirs, key=lambda path: path.relative_to(root_path).as_posix()):
        if not activity_dir.is_dir() or activity_dir.is_symlink():
            continue
        request = _read_or_empty(activity_dir / "request.json")
        status = _read_or_empty(activity_dir / "status.json")
        result = _read_or_empty(activity_dir / "result.json")
        error = status.get("error") if isinstance(status.get("error"), dict) else {}
        activity_ref = activity_dir.relative_to(root_path).as_posix()
        rows.append(
            {
                "activity_id": status.get("activity_id") or request.get("activity_id") or activity_dir.name,
                "kind": status.get("kind") or request.get("kind"),
                "operation": status.get("operation") or request.get("operation"),
                "status": status.get("status") or "pending",
                "act_refs": _string_list(status.get("act_refs") or request.get("act_refs")),
                "activity_ref": activity_ref,
                "started_at": status.get("started_at") or request.get("started_at"),
                "completed_at": status.get("completed_at"),
                "summary": result.get("summary"),
                "outcome": result.get("outcome"),
                "error_name": error.get("name"),
                "error_message": error.get("message"),
            }
        )
    return rows


def review_run_index(root: str | Path) -> list[dict[str, Any]]:
    """Index isolated advisory Review sessions.

    v4 has no model-based Compute, Render, or Report child sessions.  Any
    journal that is not explicitly an advisory Review is retained on disk for
    diagnosis but excluded from the public Review index.
    """

    root_path = Path(root).expanduser().resolve()
    run_dirs = [
        *root_path.glob("acts/*/agent-runs/*"),
        *root_path.glob("operations/agent-runs/*"),
    ]
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs, key=lambda path: path.relative_to(root_path).as_posix()):
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        task = _read_or_empty(run_dir / "task.json")
        if task.get("role") != "review" or task.get("authority") != "advisory":
            continue
        run = _read_or_empty(run_dir / "run.json")
        result = _read_or_empty(run_dir / "result.json")
        disposition = _read_or_empty(run_dir / "root-disposition.json")
        error = run.get("error") if isinstance(run.get("error"), dict) else {}
        scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        run_ref = run_dir.relative_to(root_path).as_posix()
        row = {
            "task_id": task.get("task_id") or run_dir.name,
            "role": "review",
            "authority": "advisory",
            "operation": task.get("operation"),
            "status": run.get("status") or "pending",
            "act_refs": _string_list(scope.get("act_refs")),
            "claim_refs": _string_list(scope.get("claim_refs")),
            "run_ref": run_ref,
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "summary": result.get("summary"),
            "result_outcome": result.get("outcome"),
            "error_code": error.get("code"),
            "error_message": error.get("message"),
        }
        disposition_valid = _valid_review_disposition(disposition, row)
        row.update(
            {
                "root_disposition": disposition.get("disposition") if disposition_valid else None,
                "root_response": disposition.get("response") if disposition_valid else None,
                "root_next_steps": disposition.get("next_steps", []) if disposition_valid else [],
                "root_disposition_ref": f"{run_ref}/root-disposition.json" if disposition_valid else None,
                "root_disposition_invalid": bool(disposition) and not disposition_valid,
            }
        )
        rows.append(row)
    return rows


def review_disposition_obligations(review_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return completed advisory Reviews that still require a Root response."""

    return [
        {
            "task_id": row.get("task_id"),
            "operation": row.get("operation"),
            "act_refs": row.get("act_refs", []),
            "claim_refs": row.get("claim_refs", []),
            "run_ref": row.get("run_ref"),
            "invalid_disposition": bool(row.get("root_disposition_invalid")),
        }
        for row in review_runs
        if row.get("status") == "completed" and not row.get("root_disposition")
    ]


def _valid_review_disposition(disposition: dict[str, Any], run: dict[str, Any]) -> bool:
    return (
        run.get("role") == "review"
        and run.get("authority") == "advisory"
        and run.get("status") == "completed"
        and disposition.get("schema_version") == "ts-review-root-disposition/1"
        and disposition.get("task_id") == run.get("task_id")
        and disposition.get("review_run_ref") == run.get("run_ref")
        and disposition.get("disposition") in {"accepted", "partially_accepted", "rejected", "deferred"}
        and isinstance(disposition.get("response"), str)
        and bool(disposition["response"].strip())
        and len(disposition["response"]) <= 4000
        and isinstance(disposition.get("next_steps"), list)
        and len(disposition["next_steps"]) <= 8
        and all(
            isinstance(item, str) and bool(item.strip()) and len(item) <= 1000
            for item in disposition["next_steps"]
        )
        and isinstance(disposition.get("created_at"), str)
        and bool(disposition["created_at"].strip())
    )


def _operational_files(root: Path) -> list[Path]:
    patterns = (
        "acts/*/attempts/*/status.json",
        "acts/*/attempts/*/*_guard.json",
        "acts/*/attempts/*/*_result.json",
        "acts/*/attempts/*/*_reconciliation.json",
        "acts/*/attempts/*/*_receipt.json",
        "acts/*/attempts/*/outputs/calculation_result.json",
        "acts/*/activities/*/*.json",
        "operations/activities/*/*.json",
        "acts/*/agent-runs/*/*.json",
        "operations/agent-runs/*/*.json",
    )
    files = {
        path
        for pattern in patterns
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _pending_controls(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
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
        row: dict[str, Any] = {
            "operation": operation,
            "act_id": _act_id_for_attempt(root, guard.parent),
            "intent_id": guard.parent.name,
            "guard_ref": guard.relative_to(root).as_posix(),
        }
        if attempt > 1:
            row["attempt"] = attempt
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
        unresolved.append(
            {
                "operation": operation,
                "act_id": _act_id_for_attempt(root, result_path.parent),
                "intent_id": result_path.parent.name,
                "attempt": attempt,
                "result_ref": result_path.relative_to(root).as_posix(),
                "state": state,
                "error_class": error_class,
                "effect_outcome": effect_outcome or ("unknown" if unresolved_state else "failed"),
                "retry_disposition": retry_disposition
                or ("reconcile_only" if unresolved_state or ambiguous_error else None),
                "job_id": result.get("job_id"),
            }
        )
    return unresolved


def _act_id_for_attempt(root: Path, attempt_dir: Path) -> str:
    relative = attempt_dir.relative_to(root)
    if len(relative.parts) != 4 or relative.parts[0] != "acts" or relative.parts[2] != "attempts":
        raise ValueError(f"invalid v4 calculation attempt path: {relative.as_posix()}")
    return relative.parts[1]


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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
