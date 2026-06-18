"""Mark prepared TS-search nodes as actively running."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.base.rationale import lint_node_rationale
from transition_state_workflow.config.state_contract import TREE_SCHEMA
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import clean_string, portable_record_path, safe_identifier_token


@dataclass(frozen=True)
class NodeStartRequest:
    """Caller-supplied state for starting one prepared node."""

    root: Path
    node_id: str
    run_state: str
    decision: str
    summary: str
    primary_file: str
    badges: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    force: bool = False


def start_ts_workspace_node(request: NodeStartRequest) -> None:
    """Update node.json and tree.json for a node that has started running."""

    root = request.root.expanduser().resolve()
    ensure_workspace_root(root)
    node_path = root / "nodes" / request.node_id / "node.json"
    if not node_path.exists():
        raise SystemExit(f"node does not exist: {request.node_id}")

    node_payload = read_json_object_required(node_path)
    tree_payload = read_json_object_required(root / "tree.json")
    validate_start_request(node_payload, request)
    validate_pre_execution_rationale(root, request.node_id, node_payload)

    display = node_payload.get("display") if isinstance(node_payload.get("display"), dict) else {}
    primary_file = clean_string(request.primary_file) or clean_string(display.get("primary_file"))
    if primary_file:
        primary_file = portable_record_path(root, primary_file)["path"]

    node_payload["lifecycle_state"] = "active"
    node_payload["run_state"] = request.run_state
    node_payload["decision"] = request.decision
    node_payload["display"] = {
        **display,
        "badges": list(request.badges) or ["running"],
        "metrics": display.get("metrics") if isinstance(display.get("metrics"), dict) else {},
        "primary_file": primary_file,
        "summary": request.summary,
        "title": display.get("title") or request.node_id,
        "subtitle": display.get("subtitle") or node_payload.get("stage", ""),
    }

    tree_payload["active_frontier"] = append_unique(tree_payload.get("active_frontier", []), request.node_id)
    tree_payload["closed_nodes"] = [item for item in tree_payload.get("closed_nodes", []) if item != request.node_id]
    tree_payload["events"] = add_start_event(tree_payload, request, utc_timestamp())

    write_json_object(node_path, node_payload, overwrite_existing=True)
    write_json_object(root / "tree.json", tree_payload, overwrite_existing=True)


def ensure_workspace_root(root: Path) -> None:
    """Ensure the workspace root has the files required for start-node."""

    missing = [name for name in ("manifest.json", "tree.json", "nodes") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")
    tree = read_json_object_required(root / "tree.json")
    if clean_string(tree.get("schema")) != TREE_SCHEMA:
        raise SystemExit("tree.json must declare schema=tssearch-branching-tree-v2")


def validate_start_request(node_payload: dict[str, Any], request: NodeStartRequest) -> None:
    """Reject starts that would overwrite a scientific conclusion by accident."""

    if request.run_state not in {"pending", "running", "parsing"}:
        raise SystemExit(f"invalid active run_state: {request.run_state}")
    claim_status = clean_string(node_payload.get("claim_status"))
    outcome = clean_string(node_payload.get("outcome"))
    lifecycle_state = clean_string(node_payload.get("lifecycle_state"))
    if lifecycle_state in {"superseded", "archived"}:
        raise SystemExit(f"node is {lifecycle_state}; create a new branch instead of restarting it")
    if not request.force and lifecycle_state == "closed":
        raise SystemExit(f"node is already {lifecycle_state}; use --force to restart intentionally")
    if claim_status != "not_evaluated" or outcome != "none":
        raise SystemExit("start_node refuses to restart an evaluated node; create a new branch instead")


def validate_pre_execution_rationale(root: Path, node_id: str, node_payload: dict[str, Any]) -> None:
    """Reject runnable work when the pre-execution rationale is still a draft."""

    rationale = lint_node_rationale(root, node_id, node_payload)
    if not rationale.ok_to_start:
        raise SystemExit(f"start_node refused: incomplete pre-execution rationale; {rationale.summary()}")


def add_start_event(tree_payload: dict[str, Any], request: NodeStartRequest, timestamp: str) -> list[dict[str, Any]]:
    """Return timeline events with one new start_node event appended in time order."""

    events = [item for item in tree_payload.get("events", []) if isinstance(item, dict)]
    taken_ids = {clean_string(item.get("event_id")) for item in events}
    event_id = next_event_id(request.node_id, request.decision, taken_ids)
    events.append(
        {
            "event_id": event_id,
            "time": timestamp,
            "node_id": request.node_id,
            "event_type": "start_node",
            "decision": request.decision,
            "reason": request.summary,
            "evidence_refs": [clean_string(item) for item in request.evidence_refs if clean_string(item)],
        },
    )
    return events


def next_event_id(node_id: str, decision: str, taken_ids: set[str]) -> str:
    """Return an unused start_node event id."""

    base = f"evt_{safe_identifier_token(node_id)}_{safe_identifier_token(decision)}"
    if base not in taken_ids:
        return base
    index = 2
    while f"{base}_{index:02d}" in taken_ids:
        index += 1
    return f"{base}_{index:02d}"


def append_unique(raw_items: Any, item: str) -> list[str]:
    """Append item to a list unless already present, preserving order."""

    items = list(raw_items or [])
    if item not in items:
        items.append(item)
    return items


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()
