"""Record canonical backtrack events for TS-search hypothesis trees."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from transition_state_workflow.config.state_contract import TREE_SCHEMA, VALID_BACKTRACK_EVENT_STATES
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import clean_string, safe_identifier_token


@dataclass(frozen=True)
class BacktrackRequest:
    """Caller-supplied state for one backtrack edge/event."""

    root: Path
    from_node: str
    to_node: str
    reason_code: str
    reason: str
    new_branch_node: str = ""
    event_state: str = "active"
    evidence_refs: tuple[str, ...] = ()
    event_id: str = ""
    decision: str = ""
    supersede_active: bool = False


@dataclass(frozen=True)
class BacktrackStateUpdateRequest:
    """Caller-supplied state for updating one backtrack event."""

    root: Path
    backtrack_id: str
    event_state: str
    reason: str
    decision: str = ""
    evidence_refs: tuple[str, ...] = ()
    supersede_active: bool = False


def register_record_backtrack_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the record-backtrack subcommand to the workspace CLI."""

    parser = subparsers.add_parser(
        "record-backtrack",
        help="Append one canonical backtrack_events[] entry and matching timeline event.",
    )
    parser.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    parser.add_argument("--from-node", required=True, help="Failed, ambiguous, or superseded branch node.")
    parser.add_argument("--to-node", required=True, help="Closest chemically meaningful ancestor to revisit.")
    parser.add_argument(
        "--new-branch-node",
        default="",
        help="Optional new branch node created after backtracking; omit when only recording the failed branch badge.",
    )
    parser.add_argument("--reason-code", required=True, help="Short machine-readable reason code.")
    parser.add_argument("--reason", required=True, help="Human-readable backtrack reason.")
    parser.add_argument("--event-state", choices=sorted(VALID_BACKTRACK_EVENT_STATES), default="active")
    parser.add_argument("--evidence-ref", action="append", default=[], help="Existing evidence id; may be repeated.")
    parser.add_argument("--event-id", default="", help="Explicit backtrack event id.")
    parser.add_argument("--decision", default="", help="Timeline decision token. Defaults to backtrack_to_<to-node>.")
    parser.add_argument(
        "--supersede-active",
        action="store_true",
        help="Mark any existing active backtrack event as superseded before writing this active event.",
    )


def register_update_backtrack_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the update-backtrack subcommand to the workspace CLI."""

    parser = subparsers.add_parser(
        "update-backtrack",
        help="Update one canonical backtrack event state and append a timeline event.",
    )
    parser.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    parser.add_argument("--backtrack-id", required=True, help="Existing backtrack_events[] id.")
    parser.add_argument("--event-state", required=True, choices=sorted(VALID_BACKTRACK_EVENT_STATES))
    parser.add_argument("--reason", required=True, help="Human-readable reason for the state update.")
    parser.add_argument("--decision", default="", help="Timeline decision token. Defaults to update_backtrack_<state>.")
    parser.add_argument("--evidence-ref", action="append", default=[], help="Existing evidence id; may be repeated.")
    parser.add_argument(
        "--supersede-active",
        action="store_true",
        help="When setting this event active, supersede any other active backtrack first.",
    )
    parser.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")


def record_backtrack_from_cli_args(args: argparse.Namespace) -> None:
    """Build a backtrack request from argparse values and execute it."""

    request = BacktrackRequest(
        root=args.root,
        from_node=args.from_node,
        to_node=args.to_node,
        new_branch_node=args.new_branch_node,
        reason_code=args.reason_code,
        reason=args.reason,
        event_state=args.event_state,
        evidence_refs=tuple(args.evidence_ref or ()),
        event_id=args.event_id,
        decision=args.decision,
        supersede_active=args.supersede_active,
    )
    record_backtrack(request)


def update_backtrack_from_cli_args(args: argparse.Namespace) -> None:
    """Build a backtrack state update request from argparse values."""

    request = BacktrackStateUpdateRequest(
        root=args.root,
        backtrack_id=args.backtrack_id,
        event_state=args.event_state,
        reason=args.reason,
        decision=args.decision,
        evidence_refs=tuple(args.evidence_ref or ()),
        supersede_active=args.supersede_active,
    )
    update_backtrack_state(request)


def record_backtrack(request: BacktrackRequest) -> None:
    """Append one backtrack event to tree.json."""

    root = request.root.expanduser().resolve()
    ensure_workspace_root(root)
    tree_path = root / "tree.json"
    tree_payload = read_json_object_required(tree_path)
    validate_backtrack_request(tree_payload, request)

    now = utc_timestamp()
    backtrack_events = [item for item in tree_payload.get("backtrack_events", []) if isinstance(item, dict)]
    existing_backtrack_ids = {clean_string(item.get("id")) for item in backtrack_events}
    event_id = clean_string(request.event_id) or next_backtrack_event_id(request, existing_backtrack_ids)
    if event_id in existing_backtrack_ids:
        raise SystemExit(f"duplicate backtrack event id: {event_id}")
    evidence_refs = [clean_string(item) for item in request.evidence_refs if clean_string(item)]
    events = [item for item in tree_payload.get("events", []) if isinstance(item, dict)]
    if request.event_state == "active" and request.supersede_active:
        events.extend(
            supersede_active_backtracks(
                backtrack_events,
                now,
                {clean_string(item.get("event_id")) for item in events},
                exclude_event_id="",
            )
        )

    backtrack_events.append(
        {
            "id": event_id,
            "from_node": request.from_node,
            "to_node": request.to_node,
            "new_branch_node": clean_string(request.new_branch_node),
            "reason_code": request.reason_code,
            "reason": request.reason,
            "evidence_refs": evidence_refs,
            "event_state": request.event_state,
            "created_at": now,
        },
    )
    tree_payload["backtrack_events"] = backtrack_events

    decision = clean_string(request.decision) or f"backtrack_to_{safe_identifier_token(request.to_node)}"
    timeline_id = next_timeline_event_id(request.from_node, decision, {clean_string(item.get("event_id")) for item in events})
    events.append(
        {
            "event_id": timeline_id,
            "time": now,
            "node_id": request.from_node,
            "event_type": "record_backtrack",
            "decision": decision,
            "reason": request.reason,
            "evidence_refs": evidence_refs,
        },
    )
    tree_payload["events"] = events
    write_json_object(tree_path, tree_payload, overwrite_existing=True)


def update_backtrack_state(request: BacktrackStateUpdateRequest) -> None:
    """Update one backtrack event state and append one timeline event."""

    root = request.root.expanduser().resolve()
    ensure_workspace_root(root)
    tree_path = root / "tree.json"
    tree_payload = read_json_object_required(tree_path)
    validate_backtrack_state_update_request(tree_payload, request)

    now = utc_timestamp()
    backtrack_events = [item for item in tree_payload.get("backtrack_events", []) if isinstance(item, dict)]
    target = find_backtrack_event(backtrack_events, request.backtrack_id)
    if target is None:
        raise SystemExit(f"backtrack event id not found: {request.backtrack_id}")
    events = [item for item in tree_payload.get("events", []) if isinstance(item, dict)]
    if request.event_state == "active" and request.supersede_active:
        events.extend(
            supersede_active_backtracks(
                backtrack_events,
                now,
                {clean_string(item.get("event_id")) for item in events},
                exclude_event_id=request.backtrack_id,
            )
        )

    target["event_state"] = request.event_state
    target["updated_at"] = now
    if request.event_state in {"resolved", "superseded"}:
        target[f"{request.event_state}_at"] = now
    elif request.event_state == "active":
        target["activated_at"] = now

    evidence_refs = [clean_string(item) for item in request.evidence_refs if clean_string(item)]
    decision = clean_string(request.decision) or f"update_backtrack_{safe_identifier_token(request.event_state)}"
    timeline_id = next_timeline_event_id(
        clean_string(target.get("from_node")),
        decision,
        {clean_string(item.get("event_id")) for item in events},
    )
    events.append(
        {
            "event_id": timeline_id,
            "time": now,
            "node_id": clean_string(target.get("from_node")),
            "event_type": "update_backtrack",
            "decision": decision,
            "reason": request.reason,
            "evidence_refs": evidence_refs,
            "backtrack_event_id": request.backtrack_id,
            "backtrack_event_state": request.event_state,
        },
    )
    tree_payload["backtrack_events"] = backtrack_events
    tree_payload["events"] = events
    write_json_object(tree_path, tree_payload, overwrite_existing=True)


def ensure_workspace_root(root: Path) -> None:
    """Ensure root has the files required for record-backtrack."""

    missing = [name for name in ("manifest.json", "tree.json", "nodes") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")
    tree = read_json_object_required(root / "tree.json")
    if clean_string(tree.get("schema")) != TREE_SCHEMA:
        raise SystemExit("tree.json must declare schema=tssearch-branching-tree-v2")


def validate_backtrack_request(tree_payload: dict[str, object], request: BacktrackRequest) -> None:
    """Validate node references and event state before writing tree.json."""

    nodes = tree_payload.get("nodes") if isinstance(tree_payload.get("nodes"), dict) else {}
    for label, node_id in (("from_node", request.from_node), ("to_node", request.to_node)):
        if clean_string(node_id) not in nodes:
            raise SystemExit(f"{label} does not exist in tree.json nodes: {node_id}")
    new_branch_node = clean_string(request.new_branch_node)
    if new_branch_node and new_branch_node not in nodes:
        raise SystemExit(f"new_branch_node does not exist in tree.json nodes: {new_branch_node}")
    if request.event_state not in VALID_BACKTRACK_EVENT_STATES:
        raise SystemExit(f"invalid event_state: {request.event_state}")
    active_backtracks = active_backtrack_events(tree_payload)
    if request.event_state == "active" and active_backtracks and not request.supersede_active:
        active_ids = ", ".join(clean_string(item.get("id")) for item in active_backtracks if clean_string(item.get("id")))
        raise SystemExit(
            "active backtrack event already exists"
            + (f": {active_ids}" if active_ids else "")
            + "; mark it resolved/superseded or rerun with --supersede-active"
        )


def validate_backtrack_state_update_request(tree_payload: dict[str, object], request: BacktrackStateUpdateRequest) -> None:
    """Validate one backtrack state update before writing tree.json."""

    if request.event_state not in VALID_BACKTRACK_EVENT_STATES:
        raise SystemExit(f"invalid event_state: {request.event_state}")
    backtrack_events = [item for item in tree_payload.get("backtrack_events", []) if isinstance(item, dict)]
    target = find_backtrack_event(backtrack_events, request.backtrack_id)
    if target is None:
        raise SystemExit(f"backtrack event id not found: {request.backtrack_id}")
    nodes = tree_payload.get("nodes") if isinstance(tree_payload.get("nodes"), dict) else {}
    for label in ("from_node", "to_node"):
        node_id = clean_string(target.get(label))
        if node_id not in nodes:
            raise SystemExit(f"backtrack {label} does not exist in tree.json nodes: {node_id}")
    new_branch_node = clean_string(target.get("new_branch_node"))
    if new_branch_node and new_branch_node not in nodes:
        raise SystemExit(f"backtrack new_branch_node does not exist in tree.json nodes: {new_branch_node}")
    active_backtracks = [
        item
        for item in active_backtrack_events(tree_payload)
        if clean_string(item.get("id")) != request.backtrack_id
    ]
    if request.event_state == "active" and active_backtracks and not request.supersede_active:
        active_ids = ", ".join(clean_string(item.get("id")) for item in active_backtracks if clean_string(item.get("id")))
        raise SystemExit(
            "another active backtrack event already exists"
            + (f": {active_ids}" if active_ids else "")
            + "; mark it resolved/superseded or rerun with --supersede-active"
        )


def find_backtrack_event(backtrack_events: list[dict[str, object]], event_id: str) -> dict[str, object] | None:
    """Return one backtrack event by id."""

    wanted = clean_string(event_id)
    for event in backtrack_events:
        if clean_string(event.get("id")) == wanted:
            return event
    return None


def active_backtrack_events(tree_payload: dict[str, object]) -> list[dict[str, object]]:
    """Return currently active backtrack events from tree.json."""

    return [
        item
        for item in tree_payload.get("backtrack_events", [])
        if isinstance(item, dict) and (clean_string(item.get("event_state")) or "active") == "active"
    ]


def supersede_active_backtracks(
    backtrack_events: list[dict[str, object]],
    timestamp: str,
    taken_event_ids: set[str],
    *,
    exclude_event_id: str = "",
) -> list[dict[str, object]]:
    """Mark existing active backtracks as superseded and return timeline events."""

    timeline_events: list[dict[str, object]] = []
    for event in backtrack_events:
        if clean_string(event.get("id")) == clean_string(exclude_event_id):
            continue
        if (clean_string(event.get("event_state")) or "active") != "active":
            continue
        event["event_state"] = "superseded"
        event["superseded_at"] = timestamp
        event_id = clean_string(event.get("id")) or "unnamed_backtrack"
        from_node = clean_string(event.get("from_node"))
        timeline_id = next_timeline_event_id(from_node, f"supersede_{event_id}", taken_event_ids)
        taken_event_ids.add(timeline_id)
        timeline_events.append(
            {
                "event_id": timeline_id,
                "time": timestamp,
                "node_id": from_node,
                "event_type": "supersede_backtrack",
                "decision": "supersede_backtrack",
                "reason": f"Backtrack event {event_id} was superseded by a newer active backtrack event.",
                "evidence_refs": [],
            }
        )
    return timeline_events


def next_backtrack_event_id(request: BacktrackRequest, taken_ids: set[str]) -> str:
    """Return an unused backtrack event id."""

    parts = ["bt", request.from_node, "to", request.to_node, request.reason_code]
    if clean_string(request.new_branch_node):
        parts.extend(["new", request.new_branch_node])
    base = safe_identifier_token("_".join(parts))
    if base not in taken_ids:
        return base
    index = 2
    while f"{base}_{index:02d}" in taken_ids:
        index += 1
    return f"{base}_{index:02d}"


def next_timeline_event_id(node_id: str, decision: str, taken_ids: set[str]) -> str:
    """Return an unused timeline event id."""

    base = f"evt_{safe_identifier_token(node_id)}_{safe_identifier_token(decision)}"
    if base not in taken_ids:
        return base
    index = 2
    while f"{base}_{index:02d}" in taken_ids:
        index += 1
    return f"{base}_{index:02d}"


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()
