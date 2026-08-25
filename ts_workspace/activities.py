"""Validated read model for deterministic activity journals.

The activity journal is the authoritative record of structure seed and
comparison, input import, Render, and Report execution. ResearchNode documents
do not duplicate these relationships.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .io import read_json
from .refs import NODE_ID, ACTIVITY_ID


UNSUPPORTED_UUID_ACTIVITY_ID = re.compile(
    r"^op_[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ACTIVITY_KINDS = frozenset({"structure_seed", "structure_compare", "artifact_import", "render", "report"})
ACTIVITY_STATES = frozenset({"running", "completed", "failed"})
MAX_DOCUMENT_BYTES = 1024 * 1024
REQUEST_FIELDS = frozenset({
    "schema_version",
    "activity_id",
    "kind",
    "operation",
    "node_refs",
    "request",
    "started_at",
})
STATUS_FIELDS = frozenset({
    "schema_version",
    "activity_id",
    "kind",
    "operation",
    "node_refs",
    "status",
    "started_at",
    "completed_at",
    "error",
})


def build_activity_index(
    root: str | Path,
    *,
    known_node_ids: Iterable[str] | None = None,
    exclude_activity_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Return validated activities, integrity findings, and per-Node summaries."""

    root_path = Path(root).expanduser().resolve()
    findings: list[dict[str, Any]] = []
    excluded = _normalize_exclusions(exclude_activity_refs)
    activity_dirs = _activity_directories(root_path, findings, excluded)
    known = set(known_node_ids) if known_node_ids is not None else _load_known_nodes(root_path, findings, bool(activity_dirs))
    rows = [
        _read_activity(root_path, activity_dir, owner_node, known, findings)
        for activity_dir, owner_node in activity_dirs
    ]
    seen: dict[str, str] = {}
    for row in rows:
        activity_id = str(row["activity_id"])
        prior = seen.get(activity_id)
        if prior is not None:
            _finding(
                findings,
                "duplicate_activity_id",
                f"deterministic activity ID {activity_id} is used by both {prior} and {row['activity_ref']}",
                str(row["activity_ref"]),
                row["node_refs"],
            )
        else:
            seen[activity_id] = str(row["activity_ref"])

    rows.sort(key=_activity_row_sort_key)
    summaries = _activity_summaries(rows, findings, known)
    return {
        "schema_version": "ts-activity-index/1",
        "activities": rows,
        "activity_summaries": summaries,
        "integrity_findings": findings,
        "excluded_activity_refs": sorted(excluded),
    }


def activity_completion_blockers(
    index: dict[str, Any],
    *,
    node_id: str,
    outcome: str,
) -> list[dict[str, str]]:
    """Return activity-related reasons that prevent terminal Node completion."""

    blockers: list[dict[str, str]] = []
    for finding in index.get("integrity_findings", []):
        if isinstance(finding, dict) and node_id in _string_list(finding.get("node_refs")):
            blockers.append({
                "code": "activity_integrity_error",
                "ref": str(finding.get("path") or node_id),
                "message": str(finding.get("message") or "activity journal integrity failed"),
            })
    for row in index.get("activities", []):
        if not isinstance(row, dict) or node_id not in _string_list(row.get("node_refs")):
            continue
        state = row.get("status")
        ref = str(row.get("activity_ref") or row.get("activity_id") or node_id)
        if state in {"running", "pending"}:
            blockers.append({
                "code": "activity_not_terminal",
                "ref": ref,
                "message": f"deterministic activity is still {state}: {ref}",
            })
        elif state == "failed" and outcome == "completed" and row.get("kind") != "render":
            blockers.append({
                "code": "failed_activity_requires_non_success_outcome",
                "ref": ref,
                "message": f"failed deterministic activity cannot be closed as completed: {ref}",
            })
    return _unique_blockers(blockers)


def _activity_row_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    activity_id = str(row.get("activity_id") or "")
    match = ACTIVITY_ID.fullmatch(activity_id)
    ordinal = int(activity_id.removeprefix("op_")) if match else 2**63 - 1
    return ordinal, str(row.get("activity_ref") or "")


def _activity_directories(
    root: Path,
    findings: list[dict[str, Any]],
    excluded: set[str],
) -> list[tuple[Path, str | None]]:
    rows: list[tuple[Path, str | None]] = []
    nodes_root = root / "nodes"
    if nodes_root.is_symlink():
        _finding(findings, "activity_path_symlink", "nodes/ is a symbolic link", "nodes", [])
    elif nodes_root.is_dir():
        for node_dir in sorted(nodes_root.iterdir(), key=lambda path: path.name):
            if node_dir.name.startswith("."):
                continue
            if node_dir.is_symlink():
                refs = [node_dir.name] if NODE_ID.fullmatch(node_dir.name) else []
                _finding(
                    findings,
                    "activity_path_symlink",
                    f"ResearchNode artifact root is a symbolic link: nodes/{node_dir.name}",
                    f"nodes/{node_dir.name}",
                    refs,
                )
                continue
            if not node_dir.is_dir():
                continue
            rows.extend(_scope_activity_dirs(root, node_dir / "activities", node_dir.name, findings, excluded))

    operations_root = root / "operations"
    if operations_root.is_symlink():
        _finding(findings, "activity_path_symlink", "operations/ is a symbolic link", "operations", [])
    elif operations_root.is_dir():
        rows.extend(_scope_activity_dirs(root, operations_root / "activities", None, findings, excluded))
    return sorted(rows, key=lambda item: item[0].relative_to(root).as_posix())


def _scope_activity_dirs(
    root: Path,
    scope: Path,
    owner_node: str | None,
    findings: list[dict[str, Any]],
    excluded: set[str],
) -> list[tuple[Path, str | None]]:
    scope_ref = scope.relative_to(root).as_posix()
    owner_refs = [owner_node] if owner_node else []
    if not scope.exists() and not scope.is_symlink():
        return []
    if scope.is_symlink():
        _finding(findings, "activity_path_symlink", f"activity scope is a symbolic link: {scope_ref}", scope_ref, owner_refs)
        return []
    if not scope.is_dir():
        _finding(findings, "activity_scope_not_directory", f"activity scope is not a directory: {scope_ref}", scope_ref, owner_refs)
        return []
    rows: list[tuple[Path, str | None]] = []
    for entry in sorted(scope.iterdir(), key=lambda path: path.name):
        if entry.name.startswith("."):
            continue
        ref = entry.relative_to(root).as_posix()
        if ref in excluded:
            continue
        if entry.is_symlink():
            _finding(findings, "activity_path_symlink", f"activity entry is a symbolic link: {ref}", ref, owner_refs)
        elif not entry.is_dir():
            _finding(findings, "activity_entry_not_directory", f"activity entry is not a directory: {ref}", ref, owner_refs)
        elif UNSUPPORTED_UUID_ACTIVITY_ID.fullmatch(entry.name):
            continue
        else:
            rows.append((entry, owner_node))
    return rows


def _read_activity(
    root: Path,
    activity_dir: Path,
    owner_node: str | None,
    known_nodes: set[str],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    ref = activity_dir.relative_to(root).as_posix()
    owner_refs = [owner_node] if owner_node else []
    request = _read_required_document(activity_dir / "request.json", root, findings, owner_refs)
    status = _read_required_document(activity_dir / "status.json", root, findings, owner_refs)
    result, result_exists = _read_optional_document(activity_dir / "result.json", root, findings, owner_refs)

    request_refs = _validate_request(request, ref, findings, owner_refs)
    status_refs = _validate_status(status, ref, findings, owner_refs)
    node_refs = _ordered_union(request_refs, status_refs, owner_refs)
    _validate_binding_consistency(request, status, ref, findings, node_refs)
    _validate_path_owner(owner_node, request_refs, status_refs, ref, findings, node_refs)
    _validate_known_nodes(node_refs, known_nodes, ref, findings)

    directory_id = activity_dir.name
    document_ids = [
        value
        for value in (request.get("activity_id"), status.get("activity_id"))
        if isinstance(value, str) and value
    ]
    if not ACTIVITY_ID.fullmatch(directory_id):
        _finding(findings, "invalid_activity_directory_id", f"invalid activity directory ID: {directory_id}", ref, node_refs)
    if any(value != directory_id for value in document_ids):
        _finding(findings, "activity_id_path_mismatch", f"activity documents do not match directory ID {directory_id}", ref, node_refs)

    state = status.get("status") if status.get("status") in ACTIVITY_STATES else "pending"
    _validate_terminal_state(state, status, result, result_exists, ref, findings, node_refs)
    error = status.get("error") if isinstance(status.get("error"), dict) else {}
    return {
        "activity_id": status.get("activity_id") or request.get("activity_id") or directory_id,
        "kind": status.get("kind") or request.get("kind"),
        "operation": status.get("operation") or request.get("operation"),
        "status": state,
        "node_refs": node_refs,
        "activity_ref": ref,
        "started_at": status.get("started_at") or request.get("started_at"),
        "completed_at": status.get("completed_at"),
        "summary": result.get("summary") if isinstance(result, dict) else None,
        "outcome": result.get("outcome") if isinstance(result, dict) else None,
        "error_name": error.get("name"),
        "error_message": error.get("message"),
    }


def _validate_request(
    value: dict[str, Any],
    ref: str,
    findings: list[dict[str, Any]],
    fallback_refs: list[str],
) -> list[str]:
    refs = _valid_node_refs(value.get("node_refs"))
    associated = _ordered_union(refs, fallback_refs)
    if value.get("schema_version") != "ts-deterministic-activity-request/1":
        _finding(findings, "invalid_activity_request_schema", "activity request schema_version is invalid", f"{ref}/request.json", associated)
    if set(value) != REQUEST_FIELDS:
        _finding(findings, "invalid_activity_request_fields", "activity request fields do not match the journal contract", f"{ref}/request.json", associated)
    _validate_common_binding(value, f"{ref}/request.json", findings, associated)
    if not isinstance(value.get("request"), dict):
        _finding(findings, "invalid_activity_request_payload", "activity request payload must be an object", f"{ref}/request.json", associated)
    return refs


def _validate_status(
    value: dict[str, Any],
    ref: str,
    findings: list[dict[str, Any]],
    fallback_refs: list[str],
) -> list[str]:
    refs = _valid_node_refs(value.get("node_refs"))
    associated = _ordered_union(refs, fallback_refs)
    if value.get("schema_version") != "ts-deterministic-activity-status/1":
        _finding(findings, "invalid_activity_status_schema", "activity status schema_version is invalid", f"{ref}/status.json", associated)
    if set(value) != STATUS_FIELDS:
        _finding(findings, "invalid_activity_status_fields", "activity status fields do not match the journal contract", f"{ref}/status.json", associated)
    _validate_common_binding(value, f"{ref}/status.json", findings, associated)
    if value.get("status") not in ACTIVITY_STATES:
        _finding(findings, "invalid_activity_status", "activity status must be running, completed, or failed", f"{ref}/status.json", associated)
    return refs


def _validate_common_binding(
    value: dict[str, Any],
    path: str,
    findings: list[dict[str, Any]],
    node_refs: list[str],
) -> None:
    if not isinstance(value.get("activity_id"), str) or not ACTIVITY_ID.fullmatch(str(value.get("activity_id"))):
        _finding(findings, "invalid_activity_id", "activity_id is invalid", path, node_refs)
    if value.get("kind") not in ACTIVITY_KINDS:
        _finding(findings, "invalid_activity_kind", "activity kind is invalid", path, node_refs)
    operation = value.get("operation")
    if not isinstance(operation, str) or not operation or len(operation) > 128:
        _finding(findings, "invalid_activity_operation", "activity operation is invalid", path, node_refs)
    if not _valid_node_ref_collection(value.get("node_refs")):
        _finding(findings, "invalid_activity_node_refs", "activity node_refs are invalid", path, node_refs)
    started_at = value.get("started_at")
    if not isinstance(started_at, str) or not started_at or len(started_at) > 64:
        _finding(findings, "invalid_activity_timestamp", "activity started_at is invalid", path, node_refs)


def _validate_binding_consistency(
    request: dict[str, Any],
    status: dict[str, Any],
    ref: str,
    findings: list[dict[str, Any]],
    node_refs: list[str],
) -> None:
    fields = ("activity_id", "kind", "operation", "node_refs", "started_at")
    mismatched = [field for field in fields if request.get(field) != status.get(field)]
    if mismatched:
        _finding(
            findings,
            "activity_request_status_mismatch",
            "activity request/status bindings differ: " + ", ".join(mismatched),
            ref,
            node_refs,
        )


def _validate_path_owner(
    owner_node: str | None,
    request_refs: list[str],
    status_refs: list[str],
    ref: str,
    findings: list[dict[str, Any]],
    node_refs: list[str],
) -> None:
    collections = [request_refs, status_refs]
    if owner_node is not None:
        valid = all(refs == [owner_node] for refs in collections)
        message = f"Node-scoped activity must be owned only by {owner_node}"
    else:
        valid = all(len(refs) != 1 for refs in collections)
        message = "workspace-scoped activity must have zero or multiple node_refs"
    if not valid:
        _finding(findings, "activity_path_owner_mismatch", message, ref, _ordered_union(node_refs, [owner_node] if owner_node else []))


def _validate_known_nodes(
    node_refs: list[str],
    known_nodes: set[str],
    ref: str,
    findings: list[dict[str, Any]],
) -> None:
    unknown = sorted(set(node_refs) - known_nodes, key=_node_sort_key)
    if unknown:
        _finding(
            findings,
            "activity_unknown_node_ref",
            "activity references unknown ResearchNodes: " + ", ".join(unknown),
            ref,
            node_refs,
        )


def _validate_terminal_state(
    state: str,
    status: dict[str, Any],
    result: dict[str, Any],
    result_exists: bool,
    ref: str,
    findings: list[dict[str, Any]],
    node_refs: list[str],
) -> None:
    completed_at = status.get("completed_at")
    error = status.get("error")
    if state == "running":
        valid = completed_at is None and error is None and not result_exists
    elif state == "completed":
        valid = isinstance(completed_at, str) and bool(completed_at) and error is None and result_exists
    elif state == "failed":
        valid = (
            isinstance(completed_at, str)
            and bool(completed_at)
            and isinstance(error, dict)
            and isinstance(error.get("name"), str)
            and bool(error.get("name"))
            and isinstance(error.get("message"), str)
            and bool(error.get("message"))
        )
    else:
        return
    if not valid:
        _finding(
            findings,
            "activity_terminal_state_mismatch",
            f"activity {state} status, result, completion time, and error are inconsistent",
            ref,
            node_refs,
        )


def _read_required_document(
    path: Path,
    root: Path,
    findings: list[dict[str, Any]],
    node_refs: list[str],
) -> dict[str, Any]:
    value, exists = _read_optional_document(path, root, findings, node_refs)
    if not exists:
        ref = path.relative_to(root).as_posix()
        _finding(findings, "missing_activity_document", f"required activity document is missing: {path.name}", ref, node_refs)
    return value


def _read_optional_document(
    path: Path,
    root: Path,
    findings: list[dict[str, Any]],
    node_refs: list[str],
) -> tuple[dict[str, Any], bool]:
    ref = path.relative_to(root).as_posix()
    if not path.exists() and not path.is_symlink():
        return {}, False
    if path.is_symlink():
        _finding(findings, "activity_document_symlink", f"activity document is a symbolic link: {path.name}", ref, node_refs)
        return {}, True
    if not path.is_file():
        _finding(findings, "activity_document_not_file", f"activity document is not a regular file: {path.name}", ref, node_refs)
        return {}, True
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError(f"activity document exceeds {MAX_DOCUMENT_BYTES} bytes")
        value = read_json(path)
    except (OSError, ValueError) as exc:
        _finding(findings, "malformed_activity_document", f"cannot read activity document: {exc}", ref, node_refs)
        return {}, True
    if not isinstance(value, dict):
        _finding(findings, "malformed_activity_document", "activity document must contain a JSON object", ref, node_refs)
        return {}, True
    return value, True


def _load_known_nodes(root: Path, findings: list[dict[str, Any]], required: bool) -> set[str]:
    registry_path = root / "research_nodes.json"
    if not registry_path.is_file() or registry_path.is_symlink():
        if required:
            _finding(findings, "activity_registry_unavailable", "ResearchNode registry is unavailable for activity validation", "research_nodes.json", [])
        return set()
    try:
        registry = read_json(registry_path)
    except (OSError, ValueError):
        if required:
            _finding(findings, "activity_registry_unavailable", "ResearchNode registry is not valid JSON", "research_nodes.json", [])
        return set()
    if not isinstance(registry, dict) or registry.get("schema_version") != "ts-research-node-registry/1":
        if required:
            _finding(findings, "activity_registry_unavailable", "ResearchNode registry does not use ts-research-node-registry/1", "research_nodes.json", [])
        return set()
    return {
        str(row["node_id"])
        for row in registry.get("nodes", [])
        if isinstance(row, dict) and isinstance(row.get("node_id"), str)
    }


def _activity_summaries(
    rows: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    known_nodes: set[str],
) -> list[dict[str, Any]]:
    node_ids = set(known_nodes)
    node_ids.update(ref for row in rows for ref in _string_list(row.get("node_refs")) if NODE_ID.fullmatch(ref))
    summaries: list[dict[str, Any]] = []
    for node_id in sorted(node_ids, key=_node_sort_key):
        selected = [row for row in rows if node_id in _string_list(row.get("node_refs"))]
        statuses = {state: sum(1 for row in selected if row.get("status") == state) for state in ("running", "completed", "failed", "pending")}
        summaries.append({
            "node_id": node_id,
            "activity_count": len(selected),
            "running_count": statuses["running"],
            "completed_count": statuses["completed"],
            "failed_count": statuses["failed"],
            "pending_count": statuses["pending"],
            "integrity_error_count": sum(
                1
                for finding in findings
                if node_id in _string_list(finding.get("node_refs")) and finding.get("severity") == "error"
            ),
        })
    return summaries


def _normalize_exclusions(values: Iterable[str]) -> set[str]:
    refs: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("excluded activity refs must be strings")
        parts = value.split("/")
        node_scoped = len(parts) == 4 and parts[0] == "nodes" and NODE_ID.fullmatch(parts[1] or "") and parts[2] == "activities"
        workspace_scoped = len(parts) == 3 and parts[:2] == ["operations", "activities"]
        if (not node_scoped and not workspace_scoped) or not ACTIVITY_ID.fullmatch(parts[-1] or ""):
            raise ValueError(f"invalid excluded activity ref: {value}")
        refs.add(value)
    return refs


def _valid_node_ref_collection(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 32
        and len(value) == len(set(item for item in value if isinstance(item, str)))
        and all(isinstance(item, str) and NODE_ID.fullmatch(item) for item in value)
    )


def _valid_node_refs(value: Any) -> list[str]:
    return list(value) if _valid_node_ref_collection(value) else []


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _ordered_union(*values: Iterable[str]) -> list[str]:
    rows: list[str] = []
    for collection in values:
        for value in collection:
            if isinstance(value, str) and value not in rows:
                rows.append(value)
    return rows


def _unique_blockers(values: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (value["code"], value["ref"])
        if key not in seen:
            rows.append(value)
            seen.add(key)
    return rows


def _node_sort_key(value: str) -> tuple[int, int | str]:
    if NODE_ID.fullmatch(value):
        return (0, int(value.split("_", 1)[1]))
    return (1, value)


def _finding(
    findings: list[dict[str, Any]],
    code: str,
    message: str,
    path: str,
    node_refs: Iterable[str],
) -> None:
    findings.append({
        "severity": "error",
        "code": code,
        "message": message,
        "path": path,
        "node_refs": list(dict.fromkeys(ref for ref in node_refs if isinstance(ref, str))),
    })
