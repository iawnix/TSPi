"""Read-only projection of noncanonical v5 runtime state.

Canonical scientific state lives in the v5 registries.  Calculation attempts,
deterministic tool activities, Compute/Review runs, and control receipts are
durable operational records, but they never become scientific support merely
because they appear in this projection.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from .activities import activity_completion_blockers, build_activity_index
from .io import read_json, sha256_json
from .refs import NODE_ID, ACTIVITY_ID, CALCULATION_ID, CLAIM_ID, SUBAGENT_RUN_ID


def operational_snapshot(
    root: str | Path,
    *,
    exclude_activity_refs: Iterable[str] = (),
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    activity_index = build_activity_index(
        root_path,
        exclude_activity_refs=exclude_activity_refs,
    )
    excluded = set(activity_index["excluded_activity_refs"])
    files = _operational_files(root_path, excluded_activity_refs=excluded)
    activities = activity_index["activities"]
    agent_runs = agent_run_index(root_path)
    pending_review_dispositions = review_disposition_obligations(agent_runs)
    review_disposition_count = sum(1 for row in agent_runs if row.get("root_disposition"))
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
                ],
                "activity_integrity_findings": activity_index["integrity_findings"],
                "excluded_activity_refs": activity_index["excluded_activity_refs"],
            }
        ),
        "deterministic_activities": activities,
        "activity_summaries": activity_index["activity_summaries"],
        "activity_integrity_findings": activity_index["integrity_findings"],
        "excluded_activity_refs": activity_index["excluded_activity_refs"],
        "agent_runs": agent_runs,
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
            "activity_pending_count": sum(1 for row in activities if row.get("status") == "pending"),
            "activity_integrity_error_count": len(activity_index["integrity_findings"]),
            "agent_run_count": len(agent_runs),
            "agent_run_failed_count": sum(1 for row in agent_runs if row.get("status") == "failed"),
            "agent_run_pending_count": sum(1 for row in agent_runs if row.get("status") == "pending"),
            "review_disposition_count": review_disposition_count,
            "review_disposition_pending_count": len(pending_review_dispositions),
            "control_pending_count": len(pending_controls),
            "control_unresolved_count": len(unresolved_controls),
            "ambiguous_submission_count": len(ambiguous_submissions),
            "ambiguous_cancellation_count": len(ambiguous_cancellations),
            "control_retryable_count": len(retryable_controls),
        },
    }


def node_completion_blockers(
    snapshot: dict[str, Any],
    *,
    node_id: str,
    outcome: str,
) -> list[dict[str, str]]:
    """Combine activity and remote-control blockers for one Node completion."""

    blockers = activity_completion_blockers(
        {
            "activities": snapshot.get("deterministic_activities", []),
            "integrity_findings": snapshot.get("activity_integrity_findings", []),
        },
        node_id=node_id,
        outcome=outcome,
    )
    for row in snapshot.get("agent_runs", []):
        if (
            not isinstance(row, dict)
            or row.get("role") != "compute"
            or node_id not in _string_list(row.get("node_refs"))
        ):
            continue
        state = str(row.get("status") or "pending")
        if state not in {"completed", "failed"}:
            ref = str(row.get("run_ref") or row.get("task_id") or node_id)
            blockers.append({
                "code": "compute_run_not_terminal",
                "ref": ref,
                "message": f"Compute run is still {state}: {ref}",
            })
    for row in snapshot.get("pending_controls", []):
        if isinstance(row, dict) and row.get("node_id") == node_id:
            ref = str(row.get("guard_ref") or row.get("intent_id") or node_id)
            blockers.append({
                "code": "pending_compute_control",
                "ref": ref,
                "message": f"pending compute control must finish before Node completion: {ref}",
            })
    for row in snapshot.get("unresolved_controls", []):
        if isinstance(row, dict) and row.get("node_id") == node_id:
            ref = str(row.get("result_ref") or row.get("intent_id") or node_id)
            blockers.append({
                "code": "unresolved_compute_control",
                "ref": ref,
                "message": f"unresolved or ambiguous compute control must be reconciled before Node completion: {ref}",
            })
    return blockers


def agent_run_index(root: str | Path) -> list[dict[str, Any]]:
    """Index isolated Review and Compute sessions without granting authority."""

    root_path = Path(root).expanduser().resolve()
    run_dirs = [
        *root_path.glob("nodes/*/attempts/*/runs/*"),
        *root_path.glob("reviews/*/runs/*"),
    ]
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs, key=lambda path: _agent_run_path_sort_key(root_path, path)):
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        ownership = _agent_run_ownership(root_path, run_dir)
        if ownership is None:
            continue
        task = _read_or_empty(run_dir / "task.json")
        if task.get("task_id") != run_dir.name:
            continue
        role = task.get("role")
        authority = task.get("authority")
        if (role, authority) not in {("review", "advisory"), ("compute", "operational")}:
            continue
        if role != ownership["role"]:
            continue
        run = _read_or_empty(run_dir / "run.json")
        result = _read_or_empty(run_dir / "result.json")
        disposition = _read_or_empty(run_dir / "root-disposition.json")
        error = run.get("error") if isinstance(run.get("error"), dict) else {}
        scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        node_refs = _string_list(scope.get("node_refs"))
        claim_refs = _string_list(scope.get("claim_refs"))
        inputs = task.get("inputs") if isinstance(task.get("inputs"), dict) else {}
        if role == "compute" and (
            node_refs != [ownership["node_id"]]
            or inputs.get("intent_id") != ownership["intent_id"]
        ):
            continue
        if role == "review" and ownership["claim_id"] not in claim_refs:
            continue
        run_ref = run_dir.relative_to(root_path).as_posix()
        row = {
            "task_id": task.get("task_id") or run_dir.name,
            "role": role,
            "authority": authority,
            "operation": task.get("operation"),
            "status": run.get("status") or "pending",
            "node_refs": node_refs,
            "claim_refs": claim_refs,
            "run_ref": run_ref,
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "summary": result.get("summary"),
            "result_outcome": result.get("outcome"),
            "error_code": error.get("code"),
            "error_message": error.get("message"),
            "backend": inputs.get("backend"),
            "intent_id": inputs.get("intent_id"),
        }
        disposition_valid = role == "review" and _valid_review_disposition(disposition, row)
        row.update(
            {
                "root_disposition": disposition.get("disposition") if disposition_valid else None,
                "root_response": disposition.get("response") if disposition_valid else None,
                "root_next_steps": disposition.get("next_steps", []) if disposition_valid else [],
                "root_disposition_ref": f"{run_ref}/root-disposition.json" if disposition_valid else None,
                "root_disposition_invalid": role == "review" and bool(disposition) and not disposition_valid,
            }
        )
        rows.append(row)
    return rows


def _agent_run_path_sort_key(root: Path, path: Path) -> tuple[int, str]:
    match = SUBAGENT_RUN_ID.fullmatch(path.name)
    ordinal = int(path.name.removeprefix("sub_")) if match else 2**63 - 1
    return ordinal, path.relative_to(root).as_posix()


def _agent_run_ownership(root: Path, run_dir: Path) -> dict[str, str] | None:
    parts = run_dir.relative_to(root).parts
    if (
        len(parts) == 6
        and parts[0] == "nodes"
        and NODE_ID.fullmatch(parts[1])
        and parts[2] == "attempts"
        and CALCULATION_ID.fullmatch(parts[3])
        and parts[4] == "runs"
        and SUBAGENT_RUN_ID.fullmatch(parts[5])
    ):
        return {"role": "compute", "node_id": parts[1], "intent_id": parts[3]}
    if (
        len(parts) == 4
        and parts[0] == "reviews"
        and CLAIM_ID.fullmatch(parts[1])
        and parts[2] == "runs"
        and SUBAGENT_RUN_ID.fullmatch(parts[3])
    ):
        return {"role": "review", "claim_id": parts[1]}
    return None


def review_disposition_obligations(agent_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return completed advisory Reviews that still require a Root response."""

    return [
        {
            "task_id": row.get("task_id"),
            "operation": row.get("operation"),
            "node_refs": row.get("node_refs", []),
            "claim_refs": row.get("claim_refs", []),
            "run_ref": row.get("run_ref"),
            "invalid_disposition": bool(row.get("root_disposition_invalid")),
        }
        for row in agent_runs
        if row.get("role") == "review"
        and row.get("authority") == "advisory"
        and row.get("status") == "completed"
        and not row.get("root_disposition")
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


def _operational_files(root: Path, *, excluded_activity_refs: set[str]) -> list[Path]:
    patterns = (
        ".ts-operational-ids.json",
        "nodes/*/attempts/*/status.json",
        "nodes/*/attempts/*/*_guard.json",
        "nodes/*/attempts/*/*_result.json",
        "nodes/*/attempts/*/*_reconciliation.json",
        "nodes/*/attempts/*/*_receipt.json",
        "nodes/*/attempts/*/outputs/calculation_result.json",
        "nodes/*/activities/*/*.json",
        "operations/activities/*/*.json",
        "nodes/*/attempts/*/runs/*/*.json",
        "reviews/*/runs/*/*.json",
    )
    files = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file() or path.is_symlink():
                continue
            ref = path.relative_to(root).as_posix()
            if any(ref.startswith(f"{activity_ref}/") for activity_ref in excluded_activity_refs):
                continue
            if not _is_current_operational_path(path.relative_to(root).parts):
                continue
            files.add(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _is_current_operational_path(parts: tuple[str, ...]) -> bool:
    if parts == (".ts-operational-ids.json",):
        return True
    if len(parts) >= 5 and parts[0] == "nodes" and NODE_ID.fullmatch(parts[1]):
        if parts[2] == "attempts" and CALCULATION_ID.fullmatch(parts[3]):
            return len(parts) < 6 or parts[4] != "runs" or SUBAGENT_RUN_ID.fullmatch(parts[5]) is not None
        if parts[2] == "activities" and ACTIVITY_ID.fullmatch(parts[3]):
            return True
    if (
        len(parts) >= 5
        and parts[0] == "reviews"
        and CLAIM_ID.fullmatch(parts[1])
        and parts[2] == "runs"
        and SUBAGENT_RUN_ID.fullmatch(parts[3])
    ):
        return True
    return bool(
        len(parts) >= 4
        and parts[0] == "operations"
        and parts[1] == "activities"
        and ACTIVITY_ID.fullmatch(parts[2])
    )


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
            "node_id": _node_id_for_attempt(root, guard.parent),
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
                "node_id": _node_id_for_attempt(root, result_path.parent),
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


def _node_id_for_attempt(root: Path, attempt_dir: Path) -> str:
    relative = attempt_dir.relative_to(root)
    if len(relative.parts) != 4 or relative.parts[0] != "nodes" or relative.parts[2] != "attempts":
        raise ValueError(f"invalid v5 calculation attempt path: {relative.as_posix()}")
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
