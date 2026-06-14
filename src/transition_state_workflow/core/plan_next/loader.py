"""Workspace loading helpers for ChemKernel next-action planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from transition_state_workflow.util.json_io import read_json_object_required
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .context import summarize_node
from .ids import node_sort_key


def ensure_plan_workspace(root: Path) -> None:
    """Fail early when the root cannot be planned from."""

    missing = [name for name in ("manifest.json", "tree.json", "nodes") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")


def conservative_workspace_validation(root: Path) -> dict[str, Any]:
    """Return a minimal validation packet when no ChemGate validator is injected."""

    return {
        "summary": {
            "mode": "not_validated",
            "source": str(root),
            "warning": "No ChemGate workspace validator was supplied to core.plan_next.",
        },
        "findings": [],
    }


def no_tsfreq_evidence_support(_root: Path, _record: Mapping[str, object]) -> bool:
    """Return false when no ChemGate TS/Freq evidence predicate is injected."""

    return False


def load_node_payloads(root: Path, tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Load node.json payloads for all tree or directory nodes."""

    tree_nodes = tree.get("nodes") if isinstance(tree.get("nodes"), dict) else {}
    node_ids = {str(key) for key in tree_nodes}
    nodes_dir = root / "nodes"
    if nodes_dir.exists():
        node_ids.update(path.name for path in nodes_dir.iterdir() if path.is_dir())
    payloads: dict[str, dict[str, Any]] = {}
    for node_id in sorted(node_ids, key=node_sort_key):
        node_path = root / "nodes" / node_id / "node.json"
        if node_path.exists():
            try:
                payloads[node_id] = read_json_object_required(node_path)
            except ValueError:
                payloads[node_id] = {}
        else:
            payloads[node_id] = {}
    return payloads


def active_node_summaries(tree: dict[str, Any], node_payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return nodes that are currently active according to tree indexes or node state."""

    active_ids = {clean_string(item) for item in list_or_empty(tree.get("active_frontier")) if clean_string(item)}
    for node_id, node in node_payloads.items():
        if clean_string(node.get("lifecycle_state")) == "active" or clean_string(node.get("run_state")) in {
            "pending",
            "running",
            "parsing",
        }:
            active_ids.add(node_id)
    return [summarize_node(node_id, node_payloads.get(node_id, {})) for node_id in sorted(active_ids, key=node_sort_key)]


def nodes_with_claim(node_payloads: dict[str, dict[str, Any]], claim_status: str) -> list[tuple[str, dict[str, Any]]]:
    """Return nodes whose current claim matches claim_status."""

    return [
        (node_id, node)
        for node_id, node in node_payloads.items()
        if clean_string(node.get("claim_status")) == claim_status
    ]


__all__ = [
    "ensure_plan_workspace",
    "conservative_workspace_validation",
    "no_tsfreq_evidence_support",
    "load_node_payloads",
    "active_node_summaries",
    "nodes_with_claim",
]
