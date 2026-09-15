"""Read-only projection of noncanonical runtime state.

Canonical scientific state lives in the workspace registries. Calculation attempts,
deterministic tool activities, Compute/Review runs, and control receipts are
durable operational records, but they never become scientific support merely
because they appear in this projection.
"""

from __future__ import annotations

import hashlib
import errno
import os
import stat
from pathlib import Path
from typing import Any, Iterable

from .activities import activity_completion_blockers, build_activity_index
from ts_agent.io import read_json, sha256_json
from .path_safety import has_symlink_component, lexical_path, path_has_symlink
from .refs import NODE_ID, ACTIVITY_ID, CALCULATION_ID, CLAIM_ID, SUBAGENT_RUN_ID
from .schema_validation import SchemaValidationError, validate_contract


# A scheduler reaching ``completed`` is not the same as a Compute Attempt
# reaching a settled state: collection and parsing may still be pending.  An
# intent that never left ``prepared`` has no external effect and is safe to
# abandon by closing its Node; submitted/queued/running/unknown and
# completed-but-unparsed Attempts are not.  Keeping this rule here gives the
# Kernel, Context, and Web the same operational interpretation without making
# the browser infer it from raw files.
_TERMINAL_ATTEMPT_STATES = frozenset({"failed", "stopped", "parsed"})
_COMPLETION_SAFE_ATTEMPT_STATES = frozenset({"prepared", *_TERMINAL_ATTEMPT_STATES})


def operational_snapshot(
    root: str | Path,
    *,
    exclude_activity_refs: Iterable[str] = (),
) -> dict[str, Any]:
    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        return _empty_operational_snapshot({
            "code": "workspace_path_symlink",
            "scope": "workspace",
            "path": ".",
            "node_refs": [],
            "message": "workspace root contains a symbolic-link component",
        })
    activity_index = build_activity_index(
        root_path,
        exclude_activity_refs=exclude_activity_refs,
    )
    excluded = set(activity_index["excluded_activity_refs"])
    operational_integrity_findings: list[dict[str, Any]] = []
    files = _operational_files(
        root_path,
        excluded_activity_refs=excluded,
        integrity_findings=operational_integrity_findings,
    )
    activities = activity_index["activities"]
    agent_runs = agent_run_index(
        root_path,
        integrity_findings=operational_integrity_findings,
    )
    pending_review_dispositions = review_disposition_obligations(agent_runs)
    review_disposition_count = sum(1 for row in agent_runs if row.get("root_disposition"))
    pending_controls = _pending_controls(root_path, files)
    control_effects = _control_effects(
        root_path,
        files,
        integrity_findings=operational_integrity_findings,
    )
    calculation_attempts = calculation_attempt_index(root_path)
    calculation_attempt_integrity_findings = _calculation_attempt_integrity_findings(
        calculation_attempts
    )
    unresolved_controls = [row for row in control_effects if row["classification"] == "unresolved"]
    ambiguous_submissions = [
        row for row in unresolved_controls if row.get("error_class") == "submission_ambiguous"
    ]
    ambiguous_cancellations = [
        row for row in unresolved_controls if row.get("error_class") == "cancellation_ambiguous"
    ]
    retryable_controls = [row for row in control_effects if row["classification"] == "retryable"]
    concrete_attempts = [
        row
        for row in calculation_attempts
        if isinstance(row, dict)
        and isinstance(row.get("intent_id"), str)
        and CALCULATION_ID.fullmatch(row["intent_id"]) is not None
    ]
    file_digests = _safe_operational_file_digests(
        root_path,
        files,
        operational_integrity_findings,
    )
    from .dispatch import dispatch_projection
    dispatch = dispatch_projection(root_path, [p.name for p in (root_path / "nodes").iterdir() if NODE_ID.fullmatch(p.name)] if (root_path / "nodes").is_dir() else [])
    return {
        "node_dispatch": dispatch,
        "operational_revision": sha256_json(
            {
                "files": file_digests,
                "activity_integrity_findings": activity_index["integrity_findings"],
                "operational_integrity_findings": operational_integrity_findings,
                "excluded_activity_refs": activity_index["excluded_activity_refs"],
                "calculation_attempts": calculation_attempts,
                "calculation_attempt_integrity_findings": calculation_attempt_integrity_findings,
            }
        ),
        "deterministic_activities": activities,
        "activity_summaries": activity_index["activity_summaries"],
        "activity_integrity_findings": activity_index["integrity_findings"],
        "operational_integrity_findings": operational_integrity_findings,
        "excluded_activity_refs": activity_index["excluded_activity_refs"],
        "calculation_attempt_integrity_findings": calculation_attempt_integrity_findings,
        "agent_runs": agent_runs,
        "pending_review_dispositions": pending_review_dispositions,
        "review_disposition_count": review_disposition_count,
        "pending_controls": pending_controls,
        "unresolved_controls": unresolved_controls,
        "ambiguous_submissions": ambiguous_submissions,
        "ambiguous_cancellations": ambiguous_cancellations,
        "retryable_controls": retryable_controls,
        "calculation_attempts": calculation_attempts,
        "operational_summary": {
            "paused_node_count": sum(row.get("paused") is True for row in dispatch),
            "tracked_file_count": len(file_digests),
            "calculation_file_count": sum(
                1 for row in file_digests if "attempts" in Path(str(row["path"])).parts
            ),
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
            # Synthetic parent rows are diagnostics, not Attempts.  Keep them
            # out of the entity count so projections cannot imply a fake
            # ``calc_*`` record exists.
            "calculation_attempt_count": len(concrete_attempts),
            "calculation_attempt_blocking_count": sum(
                1 for row in calculation_attempts if row.get("blocks_completion")
            ),
            "calculation_attempt_integrity_error_count": len(
                calculation_attempt_integrity_findings
            ),
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
    control_blocked_intents = {
        str(row.get("intent_id"))
        for key in ("pending_controls", "unresolved_controls")
        for row in snapshot.get(key, [])
        if isinstance(row, dict) and row.get("node_id") == node_id and row.get("intent_id")
    }
    # A Compute run is only one part of an Attempt lifecycle.  The child run
    # can finish after submitting a remote job while the scheduler job remains
    # queued/running, so inspect the durable Attempt status as well.
    for row in snapshot.get("calculation_attempts", []):
        if not isinstance(row, dict) or row.get("node_id") != node_id:
            continue
        ref = str(row.get("path") or row.get("intent_id") or node_id)
        if row.get("integrity_error"):
            blockers.append({
                "code": "calculation_attempt_invalid",
                "ref": ref,
                "message": f"calculation Attempt status is invalid: {ref}",
            })
            continue
        if row.get("blocks_completion") and row.get("intent_id") not in control_blocked_intents:
            state = str(row.get("state") or "unknown")
            blockers.append({
                "code": "calculation_attempt_not_terminal",
                "ref": ref,
                "message": f"calculation Attempt is still {state}: {ref}",
            })

    # Operational records are separate from scientific state, but an unsafe
    # path must still prevent a Node from being declared complete.  The file
    # scanner records symlink/non-file matches instead of silently dropping
    # them from the control projection.
    for finding in snapshot.get("operational_integrity_findings", []):
        if not isinstance(finding, dict) or node_id not in _string_list(finding.get("node_refs")):
            continue
        ref = str(finding.get("path") or node_id)
        blockers.append({
            "code": "operational_integrity_error",
            "ref": ref,
            "message": str(finding.get("message") or f"unsafe operational path: {ref}"),
        })

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


def agent_run_index(
    root: str | Path,
    *,
    integrity_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Index isolated Review and Compute sessions without granting authority."""

    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        return []
    run_dirs = _discover_agent_run_paths(root_path, integrity_findings)
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs, key=lambda path: _agent_run_path_sort_key(root_path, path)):
        # ``Path.glob`` may walk through a symlinked attempts/reviews parent.
        # Do not inspect a task document reached through such a path, even if
        # the final run directory itself is a regular directory.
        if has_symlink_component(root_path, run_dir) or not run_dir.is_dir() or run_dir.is_symlink():
            continue
        ownership = _agent_run_ownership(root_path, run_dir)
        if ownership is None:
            continue
        task = _read_or_empty(
            run_dir / "task.json",
            root=root_path,
            integrity_findings=integrity_findings,
            label="agent-run task",
        )
        if task.get("task_id") != run_dir.name:
            continue
        role = task.get("role")
        authority = task.get("authority")
        if (role, authority) not in {("review", "advisory"), ("compute", "operational")}:
            continue
        if role != ownership["role"]:
            continue
        run = _read_or_empty(
            run_dir / "run.json",
            root=root_path,
            integrity_findings=integrity_findings,
            label="agent-run status",
        )
        result = _read_or_empty(
            run_dir / "result.json",
            root=root_path,
            integrity_findings=integrity_findings,
            label="agent-run result",
        )
        disposition = _read_or_empty(
            run_dir / "root-disposition.json",
            root=root_path,
            integrity_findings=integrity_findings,
            label="agent-run disposition",
        )
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
            "capability": inputs.get("capability"),
            "capability_version": inputs.get("capability_version"),
            "expected_output_roles": _string_list(inputs.get("expected_output_roles")),
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


def _discover_agent_run_paths(
    root: Path,
    integrity_findings: list[dict[str, Any]] | None,
) -> list[Path]:
    """Discover physical agent-run directories without traversing links.

    A recursive glob can silently walk through a linked ``runs`` parent, and
    it emits no row when a linked run directory is empty.  Explicitly inspect
    each managed level so the operational projection can report the unsafe
    path and never read a document outside the workspace.
    """

    seen: set[tuple[str, str]] = set()
    paths: list[Path] = []

    def children(parent: Path, *, scope: str, refs: list[str]) -> list[Path]:
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            return []
        except OSError as exc:
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    parent,
                    f"cannot inspect agent-run {scope}: {exc}",
                    integrity_findings,
                    seen,
                )
            return []
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    parent,
                    f"agent-run {scope} is not a physical directory",
                    integrity_findings,
                    seen,
                )
            return []
        try:
            return [Path(entry.path) for entry in os.scandir(parent)]
        except OSError as exc:
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    parent,
                    f"cannot enumerate agent-run {scope}: {exc}",
                    integrity_findings,
                    seen,
                )
            return []

    def physical_directory(path: Path, *, scope: str, refs: list[str]) -> bool:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return False
        except OSError as exc:
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    path,
                    f"cannot inspect agent-run {scope}: {exc}",
                    integrity_findings,
                    seen,
                )
            return False
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    path,
                    f"agent-run {scope} is not a physical directory",
                    integrity_findings,
                    seen,
                )
            return False
        if has_symlink_component(root, path):
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    path,
                    f"agent-run {scope} contains a symbolic-link component",
                    integrity_findings,
                    seen,
                )
            return False
        return True

    nodes_root = root / "nodes"
    if physical_directory(nodes_root, scope="nodes root", refs=[]):
        for node_dir in children(nodes_root, scope="ResearchNode root", refs=[]):
            if NODE_ID.fullmatch(node_dir.name) is None:
                continue
            if not physical_directory(node_dir, scope="ResearchNode root", refs=[node_dir.name]):
                continue
            attempts_root = node_dir / "attempts"
            if not physical_directory(attempts_root, scope="Attempt parent", refs=[node_dir.name]):
                continue
            for attempt_dir in children(attempts_root, scope="Attempt", refs=[node_dir.name]):
                if CALCULATION_ID.fullmatch(attempt_dir.name) is None:
                    continue
                if not physical_directory(attempt_dir, scope="Attempt", refs=[node_dir.name]):
                    continue
                runs_root = attempt_dir / "runs"
                if not physical_directory(runs_root, scope="runs parent", refs=[node_dir.name]):
                    continue
                for run_dir in children(runs_root, scope="run", refs=[node_dir.name]):
                    if SUBAGENT_RUN_ID.fullmatch(run_dir.name) is None:
                        continue
                    if physical_directory(run_dir, scope="run", refs=[node_dir.name]):
                        paths.append(run_dir)

    reviews_root = root / "reviews"
    if physical_directory(reviews_root, scope="reviews root", refs=[]):
        for claim_dir in children(reviews_root, scope="Claim review root", refs=[]):
            if CLAIM_ID.fullmatch(claim_dir.name) is None:
                continue
            if not physical_directory(claim_dir, scope="Claim review root", refs=[]):
                continue
            runs_root = claim_dir / "runs"
            if not physical_directory(runs_root, scope="review runs parent", refs=[]):
                continue
            for run_dir in children(runs_root, scope="review run", refs=[]):
                if SUBAGENT_RUN_ID.fullmatch(run_dir.name) is None:
                    continue
                if physical_directory(run_dir, scope="review run", refs=[]):
                    paths.append(run_dir)
    return paths


def _calculation_attempt_integrity_findings(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project Attempt integrity errors without inventing Attempt entities.

    ``calculation_attempt_index`` may contain a synthetic row for an unsafe
    ``attempts/`` parent.  Such a row has no ``intent_id`` and must remain a
    parent-scope diagnostic rather than being rendered as ``calc_*``.  Concrete
    Attempt errors are included in the same projection so every consumer can
    inspect one complete, consistently shaped diagnostic stream.
    """

    findings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        message = row.get("integrity_error")
        path = row.get("path")
        if not isinstance(message, str) or not message or not isinstance(path, str) or not path:
            continue
        node_id = row.get("node_id")
        intent_id = row.get("intent_id")
        concrete = isinstance(intent_id, str) and CALCULATION_ID.fullmatch(intent_id) is not None
        finding: dict[str, Any] = {
            "code": "calculation_attempt_integrity",
            "scope": "attempt" if concrete else "attempt_parent",
            "path": path,
            "node_refs": [node_id] if isinstance(node_id, str) and node_id else [],
            "message": message,
        }
        if concrete:
            finding["intent_id"] = intent_id
        findings.append(finding)
    findings.sort(
        key=lambda item: (
            str(item.get("path") or ""),
            str(item.get("message") or ""),
        )
    )
    return findings


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


def _operational_files(
    root: Path,
    *,
    excluded_activity_refs: set[str],
    integrity_findings: list[dict[str, Any]] | None = None,
) -> list[Path]:
    patterns = (
        ".ts-operational-ids.json",
        "nodes/*/attempts/*/intent.json",
        "nodes/*/attempts/*/prepared.json",
        "nodes/*/attempts/*/status.json",
        "nodes/*/attempts/*/*_guard.json",
        "nodes/*/attempts/*/*_result.json",
        "nodes/*/attempts/*/*_reconciliation.json",
        "nodes/*/attempts/*/*_receipt.json",
        "nodes/*/attempts/*/outputs/calculation_result.json",
        "nodes/*/activities/*/*.json",
        "nodes/*/dispatch/*.json",
        "operations/activities/*/*.json",
        "nodes/*/attempts/*/runs/*/*.json",
        "reviews/*/runs/*/*.json",
    )
    files = set()
    seen_findings: set[tuple[str, str]] = set()
    for pattern in patterns:
        try:
            paths = list(root.glob(pattern))
        except OSError as exc:
            if integrity_findings is not None:
                _append_operational_finding(
                    root,
                    root / pattern,
                    f"cannot enumerate operational path pattern {pattern}: {exc}",
                    integrity_findings,
                    seen_findings,
                )
            continue
        for path in paths:
            ref = path.relative_to(root).as_posix()
            if any(ref.startswith(f"{activity_ref}/") for activity_ref in excluded_activity_refs):
                continue
            # ``Path.glob`` can traverse a symlinked parent (for example an
            # ``attempts`` directory) even when the final file itself is a
            # regular file.  Never hash or interpret a document outside the
            # physical workspace tree.
            if has_symlink_component(root, path) or path.is_symlink():
                if integrity_findings is not None:
                    _append_operational_finding(
                        root,
                        path,
                        "operational path contains a symbolic-link component",
                        integrity_findings,
                        seen_findings,
                    )
                continue
            try:
                regular = path.is_file()
            except OSError as exc:
                regular = False
                if integrity_findings is not None:
                    _append_operational_finding(
                        root,
                        path,
                        f"cannot inspect operational path: {exc}",
                        integrity_findings,
                        seen_findings,
                    )
            if not regular:
                if integrity_findings is not None:
                    try:
                        exists = path.exists()
                    except OSError:
                        exists = True
                    if exists:
                        _append_operational_finding(
                            root,
                            path,
                            "operational path is not a regular file",
                            integrity_findings,
                            seen_findings,
                        )
                continue
            if not _is_current_operational_path(path.relative_to(root).parts):
                continue
            files.add(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _append_operational_finding(
    root: Path,
    path: Path,
    message: str,
    findings: list[dict[str, Any]],
    seen: set[tuple[str, str]],
) -> None:
    """Record one bounded operational path error without reading its target."""

    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = str(path)
    key = (relative, message)
    if key in seen:
        return
    seen.add(key)
    parts = Path(relative).parts
    node_refs = (
        [parts[1]]
        if len(parts) > 1 and parts[0] == "nodes" and NODE_ID.fullmatch(parts[1])
        else []
    )
    findings.append({
        "code": "operational_path_integrity",
        "path": relative,
        "node_refs": node_refs,
        "message": message,
    })


def _empty_operational_snapshot(finding: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, read-free projection for an unsafe workspace root."""

    findings = [finding]
    return {
        "node_dispatch": [],
        "operational_revision": sha256_json({"workspace_path_finding": finding}),
        "deterministic_activities": [],
        "activity_summaries": [],
        "activity_integrity_findings": findings,
        "operational_integrity_findings": [],
        "excluded_activity_refs": [],
        "calculation_attempt_integrity_findings": [],
        "agent_runs": [],
        "pending_review_dispositions": [],
        "review_disposition_count": 0,
        "pending_controls": [],
        "unresolved_controls": [],
        "ambiguous_submissions": [],
        "ambiguous_cancellations": [],
        "retryable_controls": [],
        "calculation_attempts": [],
        "operational_summary": {
            "paused_node_count": 0,
            "tracked_file_count": 0,
            "calculation_file_count": 0,
            "activity_count": 0,
            "activity_failed_count": 0,
            "activity_running_count": 0,
            "activity_pending_count": 0,
            "activity_integrity_error_count": 1,
            "agent_run_count": 0,
            "agent_run_failed_count": 0,
            "agent_run_pending_count": 0,
            "review_disposition_count": 0,
            "review_disposition_pending_count": 0,
            "control_pending_count": 0,
            "control_unresolved_count": 0,
            "ambiguous_submission_count": 0,
            "ambiguous_cancellation_count": 0,
            "control_retryable_count": 0,
            "calculation_attempt_count": 0,
            "calculation_attempt_blocking_count": 0,
            "calculation_attempt_integrity_error_count": 0,
        },
    }


def calculation_attempt_index(root: str | Path) -> list[dict[str, Any]]:
    """Build a fail-closed index of durable calculation Attempt state.

    Control receipts alone do not describe the whole lifecycle.  This index is
    deliberately derived from the Attempt directory and is read-only; it does
    not promote operational state to scientific evidence.
    """

    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        return []
    # Discover the parent and children explicitly instead of relying on one
    # recursive glob.  ``Path.glob`` follows a symlinked ``attempts`` parent
    # and silently returns no rows for an empty/inaccessible target; both cases
    # must remain visible to the completion guard and read-only projections.
    attempt_dirs = _discover_attempt_paths(root_path)

    rows: list[dict[str, Any]] = []
    for attempt_dir in sorted(attempt_dirs, key=lambda path: _attempt_path_sort_key(root_path, path)):
        relative = attempt_dir.relative_to(root_path)
        node_id = relative.parts[1] if len(relative.parts) > 1 else "unknown"
        # A synthetic parent row has no concrete calculation ID.  It is an
        # integrity blocker only; concrete child rows retain their normal
        # ``calc_n`` identity for existing consumers.
        intent_id = relative.parts[3] if len(relative.parts) > 3 else None
        if len(relative.parts) != 4 or relative.parts[2] != "attempts":
            parent_error = (
                "Attempt parent path contains a symbolic-link component"
                if has_symlink_component(root_path, attempt_dir)
                else "Attempt parent path cannot be inspected safely"
            )
            rows.append(_invalid_attempt_row(
                node_id,
                intent_id,
                relative.as_posix(),
                parent_error,
            ))
            continue
        if attempt_dir.is_symlink() or not attempt_dir.is_dir():
            rows.append(_invalid_attempt_row(
                node_id,
                intent_id,
                relative.as_posix(),
                "Attempt path must be a physical directory",
            ))
            continue
        if has_symlink_component(root_path, attempt_dir):
            rows.append(_invalid_attempt_row(
                node_id,
                intent_id,
                relative.as_posix(),
                "Attempt path contains a symbolic-link component",
            ))
            continue
        intent, intent_error, _intent_exists = _read_attempt_document(
            attempt_dir / "intent.json", root=root_path
        )
        prepared, prepared_error, prepared_exists = _read_attempt_document(
            attempt_dir / "prepared.json", root=root_path
        )
        status, status_error, status_exists = _read_attempt_document(
            attempt_dir / "status.json", root=root_path
        )
        result, result_error, result_exists = _read_attempt_document(
            attempt_dir / "outputs" / "calculation_result.json",
            root=root_path,
        )

        errors = [
            error
            for error in (intent_error, prepared_error, status_error, result_error)
            if error
        ]
        outputs_path = attempt_dir / "outputs"
        unsafe_runtime_path = False
        if outputs_path.is_symlink():
            unsafe_runtime_path = True
            if "symbolic link is not allowed" not in errors:
                errors.append("symbolic link is not allowed")
        elif outputs_path.exists() and not outputs_path.is_dir():
            unsafe_runtime_path = True
            if "not a regular directory" not in errors:
                errors.append("outputs path is not a regular directory")
        if not intent and intent_error is None:
            errors.append("intent.json is missing")
        if intent:
            errors.extend(_attempt_intent_errors(intent, node_id=node_id, intent_id=intent_id))
        if prepared_exists:
            if prepared:
                errors.extend(
                    _attempt_prepared_errors(
                        prepared,
                        intent=intent,
                        node_id=node_id,
                        intent_id=intent_id,
                    )
                )
            elif prepared_error is None:
                errors.append("prepared.json must contain an object")
        elif not unsafe_runtime_path and _attempt_has_runtime_records(
            attempt_dir,
            status_exists=status_exists,
            result_exists=result_exists,
        ):
            # Every operation that can write status, control, run, or output
            # records is entered through ``_load_prepared``.  Seeing one of
            # those records without the immutable preparation binding means
            # the lifecycle cannot be trusted, even if the result happens to
            # be schema-valid and claims ``parsed``.
            errors.append("prepared.json is missing for an executed Attempt")
        for label, document in (("status.json", status), ("calculation_result.json", result)):
            if document:
                errors.extend(
                    _attempt_result_errors(
                        document,
                        intent=intent,
                        label=label,
                    )
                )
        state = result.get("state") or status.get("state")
        program_status = result.get("program_status") or status.get("program_status")
        if not isinstance(state, str) or not state:
            # Creating or preparing an intent has no external effect. Any
            # malformed lifecycle document is explicitly unknown and blocks.
            state = "unknown" if errors or status or result else "prepared"
        if not isinstance(program_status, str) or not program_status:
            program_status = "not_run"

        rows.append(
            {
                "node_id": node_id,
                "intent_id": intent_id,
                "path": relative.as_posix(),
                "state": state,
                "program_status": program_status,
                "job_id": result.get("job_id") or status.get("job_id"),
                "terminal": not errors and state in _TERMINAL_ATTEMPT_STATES,
                "blocks_completion": bool(errors) or state not in _COMPLETION_SAFE_ATTEMPT_STATES,
                "integrity_error": "; ".join(errors) if errors else None,
            }
        )
    return rows


def _discover_attempt_paths(root: Path) -> set[Path]:
    """Discover every canonical Attempt path without traversing unsafe data."""

    discovered: set[Path] = set()
    nodes_root = root / "nodes"
    try:
        nodes_mode = nodes_root.lstat().st_mode
    except FileNotFoundError:
        return discovered
    except OSError:
        discovered.add(nodes_root)
        return discovered
    if stat.S_ISLNK(nodes_mode) or not stat.S_ISDIR(nodes_mode):
        # Keep a parent-scope diagnostic. Returning no rows here would let a
        # completion guard mistake an inaccessible/linked ``nodes/`` tree for
        # a workspace with no calculation Attempts.
        discovered.add(nodes_root)
        return discovered
    try:
        node_dirs = list(nodes_root.iterdir())
    except OSError:
        discovered.add(nodes_root)
        return discovered
    for node_dir in node_dirs:
        if NODE_ID.fullmatch(node_dir.name) is None:
            continue
        attempts_root = node_dir / "attempts"
        try:
            node_mode = node_dir.lstat().st_mode
            if stat.S_ISLNK(node_mode):
                # A linked ResearchNode can hide an external Attempt tree.
                # Keep one diagnostic without enumerating its target.
                discovered.add(node_dir)
                continue
            if not stat.S_ISDIR(node_mode):
                discovered.add(node_dir)
                continue
            attempts_mode = attempts_root.lstat().st_mode
            if stat.S_ISLNK(attempts_mode):
                # A symlinked parent can hide an entire external tree.  Keep
                # one parent-scope diagnostic, but never enumerate its target
                # (even names can disclose or race with data outside the
                # workspace).
                discovered.add(attempts_root)
                continue
            if not stat.S_ISDIR(attempts_mode):
                discovered.add(attempts_root)
                continue
            children = _safe_iterdir(attempts_root)
            if children is None:
                discovered.add(attempts_root)
                continue
            discovered.update(
                child
                for child in children
                if CALCULATION_ID.fullmatch(child.name) is not None
                and _is_attempt_candidate(child)
            )
        except FileNotFoundError:
            # The parent may disappear between the lstat and the directory
            # listing.  A missing parent is equivalent to no Attempt tree.
            continue
        except OSError:
            # ``exists/is_dir`` can still race with removal or permission
            # changes.  Keep the parent as a diagnostic blocker rather than
            # silently treating the Attempt tree as absent.
            discovered.add(attempts_root)
    return discovered


def _attempt_path_sort_key(root: Path, path: Path) -> tuple[str, int, str]:
    """Sort concrete Attempts and parent diagnostics without assuming depth."""

    relative = path.relative_to(root)
    node = relative.parts[1] if len(relative.parts) > 1 else ""
    return node, _calculation_ordinal(path.name), relative.as_posix()


def _safe_iterdir(path: Path) -> list[Path] | None:
    """Return directory children, or ``None`` when enumeration failed."""

    try:
        return list(path.iterdir())
    except OSError:
        return None


def _is_attempt_candidate(path: Path) -> bool:
    """Recognize a durable Attempt without mistaking control-only history for one."""

    if path.is_symlink() or not path.is_dir():
        return True
    try:
        children = list(path.iterdir())
    except OSError:
        return True
    if not children:
        return True
    markers = {
        "intent.json",
        "prepared.json",
        "status.json",
        "outputs",
    }
    return any(child.name in markers for child in children)


def _attempt_intent_errors(
    intent: dict[str, Any],
    *,
    node_id: str,
    intent_id: str,
) -> list[str]:
    errors: list[str] = []
    try:
        validate_contract("attempt_intent_projection.schema.json", intent)
    except SchemaValidationError as exc:
        errors.append(str(exc))
    # The workspace projection schema deliberately documents the fields that
    # the operational index reads.  The Compute contract remains authoritative
    # for the complete immutable intent (including closed fields and capability
    # bindings), so validate it here as well rather than allowing a permissive
    # projection schema to make malformed intents look executable.
    try:
        from ts_agent.calculation_contracts import (
            CalculationContractError,
            validate_calculation_contract,
        )

        validate_calculation_contract("calculation_intent.schema.json", intent)
    except CalculationContractError as exc:
        errors.append(str(exc))
    if intent.get("intent_id") != intent_id:
        errors.append("intent_id does not match Attempt directory")
    if intent.get("node_id") != node_id:
        errors.append("node_id does not match Attempt directory")
    return errors


def _attempt_prepared_errors(
    prepared: dict[str, Any],
    *,
    intent: dict[str, Any],
    node_id: str,
    intent_id: str,
) -> list[str]:
    expected_ref = f"nodes/{node_id}/attempts/{intent_id}/intent.json"
    errors: list[str] = []
    if prepared.get("schema_version") != "ts-compute-prepared/1":
        errors.append("prepared.json has an unsupported schema_version")
    if prepared.get("intent_id") != intent_id or prepared.get("node_id") != node_id:
        errors.append("prepared.json identity does not match Attempt directory")
    if prepared.get("intent_ref") != expected_ref:
        errors.append("prepared.json intent_ref does not match Attempt directory")
    if not intent or prepared.get("intent_digest") != sha256_json(intent):
        errors.append("prepared.json intent_digest does not match intent.json")
    if not isinstance(prepared.get("prepared_task"), dict):
        errors.append("prepared.json prepared_task must be an object")
    if not isinstance(prepared.get("execution_policy"), dict):
        errors.append("prepared.json execution_policy must be an object")
    return errors


def _attempt_result_errors(
    document: dict[str, Any],
    *,
    intent: dict[str, Any],
    label: str,
) -> list[str]:
    if not intent:
        return [f"{label} cannot be bound without intent.json"]
    try:
        validate_contract("attempt_result_projection.schema.json", document)
    except SchemaValidationError as exc:
        return [str(exc)]
    # Keep the binding rule in the Compute contract module so the writer,
    # control path, operational index, and Web projection cannot drift apart.
    try:
        from ts_agent.calculation_contracts import (
            CalculationContractError,
            validate_calculation_result_binding,
        )

        validate_calculation_result_binding(intent, document, label=label)
    except CalculationContractError as exc:
        return [str(exc)]
    return []


def _invalid_attempt_row(
    node_id: str,
    intent_id: str | None,
    path: str,
    error: str,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "intent_id": intent_id,
        "path": path,
        "state": "unknown",
        "program_status": "not_run",
        "job_id": None,
        "terminal": False,
        "blocks_completion": True,
        "integrity_error": error,
    }


def _read_attempt_document(
    path: Path,
    *,
    root: Path,
) -> tuple[dict[str, Any], str | None, bool]:
    if has_symlink_component(root, path):
        return {}, "symbolic link is not allowed", True
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return {}, None, False
    except OSError as exc:
        return {}, f"cannot inspect file: {exc}", True
    if stat.S_ISLNK(mode):
        return {}, "symbolic link is not allowed", True
    if not stat.S_ISREG(mode):
        return {}, "not a regular file", True
    try:
        value = read_json(path)
    except (OSError, ValueError) as exc:
        return {}, f"cannot parse JSON: {exc}", True
    if not isinstance(value, dict):
        return {}, "document must be an object", True
    return value, None, True


def _attempt_has_runtime_records(
    attempt_dir: Path,
    *,
    status_exists: bool,
    result_exists: bool,
) -> bool:
    """Return whether an Attempt contains records that require preparation.

    ``intent.json`` alone is the deliberately safe, pre-effect state created
    before the deterministic prepare step.  Every other durable lifecycle
    record is written only after preparation and therefore cannot be accepted
    without its ``prepared.json`` binding.
    """

    if status_exists or result_exists:
        return True
    try:
        children = list(attempt_dir.iterdir())
    except OSError:
        # The caller will report the unreadable directory separately.  Treat
        # it as runtime-bearing here so a race cannot turn an unsafe state into
        # an apparently abandonable intent.
        return True
    for child in children:
        if child.name in {"intent.json", "prepared.json"}:
            continue
        if child.name == "outputs" or child.name == "runs":
            return True
        if child.name.endswith(("_guard.json", "_result.json", "_reconciliation.json", "_receipt.json")):
            return True
    return False


def _calculation_ordinal(value: str) -> int:
    match = CALCULATION_ID.fullmatch(value)
    return int(value.removeprefix("calc_")) if match else 2**63 - 1


def _is_current_operational_path(parts: tuple[str, ...]) -> bool:
    if len(parts) == 4 and parts[0] == "nodes" and NODE_ID.fullmatch(parts[1]) and parts[2] == "dispatch":
        return parts[3].endswith(".json")
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


def _control_effects(
    root: Path,
    files: list[Path],
    *,
    integrity_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Project only controls that require reconciliation or permit a safe replay."""

    latest_attempts: dict[tuple[Path, str], int] = {}
    for path in files:
        kind = "guard" if path.name.endswith("_guard.json") else "result"
        parsed = _control_record_name(path.name, kind)
        if parsed is None:
            continue
        operation, attempt, _stem = parsed
        key = (path.parent, operation)
        latest_attempts[key] = max(attempt, latest_attempts.get(key, 0))

    effects: list[dict[str, Any]] = []
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
        result = _read_or_empty(
            result_path,
            root=root,
            integrity_findings=integrity_findings,
            label="compute control result",
        )
        control = result.get("control") if isinstance(result.get("control"), dict) else {}
        state = result.get("state")
        error_class = result.get("error_class")
        effect_outcome = control.get("effect_outcome")
        effect_attempted = control.get("effect_attempted")
        retry_disposition = control.get("retry_disposition")
        reconciliation_required = control.get("reconciliation_required")
        ambiguous_error = error_class in {"submission_ambiguous", "cancellation_ambiguous"}
        retry_requested = retry_disposition == "retry_same_submission"
        retryable_failure = (
            effect_outcome == "failed"
            and effect_attempted is False
            and retry_requested
            and reconciliation_required is False
        )
        unresolved_state = (
            reconciliation_required is True
            or effect_outcome == "unknown"
            or state == "unknown"
            or ambiguous_error
            or (retry_requested and not retryable_failure)
        )
        if not (unresolved_state or retryable_failure):
            continue
        effects.append(
            {
                "classification": "unresolved" if unresolved_state else "retryable",
                "operation": operation,
                "node_id": _node_id_for_attempt(root, result_path.parent),
                "intent_id": result_path.parent.name,
                "attempt": attempt,
                "result_ref": result_path.relative_to(root).as_posix(),
                "state": state,
                "error_class": error_class,
                "effect_outcome": effect_outcome or ("unknown" if unresolved_state else "failed"),
                "effect_attempted": effect_attempted,
                "retry_disposition": retry_disposition
                or ("reconcile_only" if unresolved_state or ambiguous_error else None),
                "reconciliation_required": reconciliation_required,
                "job_id": result.get("job_id"),
            }
        )
    return effects


def _node_id_for_attempt(root: Path, attempt_dir: Path) -> str:
    relative = attempt_dir.relative_to(root)
    if len(relative.parts) != 4 or relative.parts[0] != "nodes" or relative.parts[2] != "attempts":
        raise ValueError(f"invalid calculation attempt path: {relative.as_posix()}")
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
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise OSError(errno.EISDIR, "path must be a regular file", os.fspath(path))
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _safe_operational_file_digests(
    root: Path,
    files: Iterable[Path],
    integrity_findings: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Hash the operational file set without following a raced link.

    Enumeration and hashing are separate filesystem operations.  A file can
    disappear or be replaced by a link in between them; that condition must
    become a visible operational finding rather than an exception or an
    external file digest in ``operational_revision``.
    """

    findings_seen = _finding_key_set(integrity_findings)
    rows: list[dict[str, str]] = []
    for path in files:
        try:
            if has_symlink_component(root, path) or path.is_symlink():
                raise OSError(errno.ELOOP, "symbolic link is not allowed", os.fspath(path))
            digest = _sha256_file(path)
        except OSError as exc:
            _append_operational_finding(
                root,
                path,
                f"cannot hash operational path safely: {exc}",
                integrity_findings,
                findings_seen,
            )
            continue
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": digest,
        })
    return rows


def _read_or_empty(
    path: Path,
    *,
    root: Path | None = None,
    integrity_findings: list[dict[str, Any]] | None = None,
    label: str = "operational document",
) -> dict[str, Any]:
    """Read an optional operational object without hiding malformed files."""

    if root is not None and has_symlink_component(root, path):
        if integrity_findings is not None:
            _append_operational_finding(
                root,
                path,
                f"{label} contains a symbolic-link component",
                integrity_findings,
                _finding_key_set(integrity_findings),
            )
        return {}
    try:
        mode = path.lstat()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        if root is not None and integrity_findings is not None:
            _append_operational_finding(
                root,
                path,
                f"cannot inspect {label}: {exc}",
                integrity_findings,
                _finding_key_set(integrity_findings),
            )
        return {}
    if stat.S_ISLNK(mode.st_mode) or not stat.S_ISREG(mode.st_mode):
        if root is not None and integrity_findings is not None:
            _append_operational_finding(
                root,
                path,
                f"{label} is not a regular file",
                integrity_findings,
                _finding_key_set(integrity_findings),
            )
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError) as exc:
        if root is not None and integrity_findings is not None:
            _append_operational_finding(
                root,
                path,
                f"cannot parse {label}: {exc}",
                integrity_findings,
                _finding_key_set(integrity_findings),
            )
        return {}
    if not isinstance(value, dict):
        if root is not None and integrity_findings is not None:
            _append_operational_finding(
                root,
                path,
                f"{label} must contain a JSON object",
                integrity_findings,
                _finding_key_set(integrity_findings),
            )
        return {}
    return value


def _finding_key_set(findings: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Build a deduplication set for callers that read optional documents."""

    return {
        (str(item.get("path") or ""), str(item.get("message") or ""))
        for item in findings
        if isinstance(item, dict)
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
