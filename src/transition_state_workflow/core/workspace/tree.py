"""Generic TS-search workspace tree helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import TREE_SCHEMA

from .nodes import VALID_NODE_STATUSES


def read_tree(root: Path) -> dict[str, Any]:
    """Read a workspace tree, normalizing old transitional fields away."""

    path = root / "tree.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["schema"] = TREE_SCHEMA
            data.setdefault("active_frontier", [])
            data.setdefault("closed_nodes", [])
            data.setdefault("accepted_nodes", [])
            data.setdefault("events", [])
            data.setdefault("backtrack_events", [])
            data.setdefault("nodes", {})
            data.pop("schema_version", None)
            data.pop("root", None)
            data.pop("root_node", None)
            data.pop("current_best", None)
            data.pop("accepted_ts", None)
            data.pop("backtrack_edges", None)
            data.pop("branch_decisions", None)
            return data
    return {
        "schema": TREE_SCHEMA,
        "active_frontier": [],
        "closed_nodes": [],
        "accepted_nodes": [],
        "events": [],
        "backtrack_events": [],
        "nodes": {},
    }


def write_tree(root: Path, tree: dict[str, Any]) -> None:
    """Write a workspace tree with stable formatting."""

    (root / "tree.json").write_text(
        json.dumps(tree, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def upsert_tree_node(
    root: Path,
    node_id: str,
    *,
    parent: str | None,
    stage: str,
    status: str,
    current_best: str | None = None,
    accepted_ts: str | None = None,
) -> None:
    """Insert or update a node entry plus active/closed indexes."""

    # Kept for callers that still pass the old argument; tree state never stores current_best.
    _ = current_best
    if status not in VALID_NODE_STATUSES:
        raise ValueError(f"invalid tree node status '{status}' for {node_id}")
    tree = read_tree(root)
    nodes = tree.setdefault("nodes", {})
    entry = nodes.setdefault(node_id, {})
    entry["parent_id"] = parent
    entry["stage"] = stage
    if accepted_ts is not None:
        if accepted_ts not in tree.setdefault("accepted_nodes", []):
            tree["accepted_nodes"].append(accepted_ts)
    frontier = tree.setdefault("active_frontier", [])
    closed = tree.setdefault("closed_nodes", [])
    if status in {"pending", "running"}:
        if node_id not in frontier:
            frontier.append(node_id)
    elif node_id in frontier:
        frontier.remove(node_id)
    if status in {"succeeded", "failed", "ambiguous", "accepted", "closed"}:
        if node_id not in closed:
            closed.append(node_id)
    elif node_id in closed:
        closed.remove(node_id)
    write_tree(root, tree)


def update_tree_node_metadata(root: Path, node_id: str, metadata: dict[str, Any]) -> None:
    """Apply a subset of node metadata to the tree."""

    tree = read_tree(root)
    nodes = tree.setdefault("nodes", {})
    entry = nodes.setdefault(node_id, {})
    for key in ("parent_id", "stage", "operation", "input_refs", "hypothesis"):
        if key in metadata:
            entry[key] = metadata[key]
    write_tree(root, tree)


__all__ = ["read_tree", "write_tree", "upsert_tree_node", "update_tree_node_metadata"]
