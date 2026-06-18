"""Tree structure and index checks for ChemGate workspace validation."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.config.state_contract import TREE_LEGACY_TOP_LEVEL_FIELDS, derive_node_audit_view
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .common import clean_string_set
from .contracts import Finding


def validate_tree_top_level_contract(tree: dict[str, Any], findings: list[Finding]) -> None:
    """Reject top-level tree fields that duplicate canonical v2 state."""

    legacy = [field for field in TREE_LEGACY_TOP_LEVEL_FIELDS if field in tree]
    if legacy:
        findings.append(
            Finding(
                "error",
                "legacy_tree_top_level_fields",
                f"tree.json contains non-v2 top-level fields: {', '.join(legacy)}",
                path="tree.json",
            )
        )


def validate_parent_graph(parent_by_node: dict[str, str], findings: list[Finding]) -> None:
    """Validate that parent links form an acyclic branch tree."""

    for node_id, parent_id in parent_by_node.items():
        if parent_id == node_id:
            findings.append(
                Finding(
                    "error",
                    "self_parent",
                    "node parent_id points to itself",
                    path=f"nodes/{node_id}/node.json",
                    node_id=node_id,
                )
            )

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node_id: str, path: list[str]) -> None:
        if node_id in active:
            cycle = " -> ".join(path + [node_id])
            findings.append(
                Finding(
                    "error",
                    "parent_cycle",
                    f"parent links contain a cycle: {cycle}",
                    path="tree.json",
                    node_id=node_id,
                )
            )
            return
        if node_id in visited:
            return
        active.add(node_id)
        parent = parent_by_node.get(node_id)
        if parent:
            visit(parent, path + [node_id])
        active.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(parent_by_node):
        visit(node_id, [])


def validate_indexes(tree: dict[str, Any], graph: dict[str, Any], findings: list[Finding]) -> None:
    """Validate tree index arrays against normalized graph node state."""

    active = clean_string_set(list_or_empty(tree.get("active_frontier")))
    closed = clean_string_set(list_or_empty(tree.get("closed_nodes")))
    accepted = clean_string_set(list_or_empty(tree.get("accepted_nodes")))
    node_by_id = {clean_string(node.get("id")): node for node in list_or_empty(graph.get("nodes")) if isinstance(node, dict)}
    expected_active = {
        node_id
        for node_id, node in node_by_id.items()
        if node_id and clean_string(node.get("lifecycle_state")) == "active"
    }
    expected_closed = {
        node_id
        for node_id, node in node_by_id.items()
        if node_id and clean_string(node.get("lifecycle_state")) == "closed"
    }
    expected_accepted = {
        node_id
        for node_id, node in node_by_id.items()
        if node_id and clean_string(node.get("claim_status")) == "accepted_ts"
    }
    if active != expected_active:
        findings.append(Finding("warning", "active_index_drift", "tree active_frontier differs from normalized active_frontier", path="tree.json"))
    if closed != expected_closed:
        findings.append(Finding("warning", "closed_index_drift", "tree closed_nodes differs from normalized closed_nodes", path="tree.json"))
    if accepted != expected_accepted:
        findings.append(Finding("warning", "accepted_index_drift", "tree accepted_nodes differs from normalized accepted_nodes", path="tree.json"))
    for node_id in active:
        node = node_by_id.get(node_id)
        if not node:
            findings.append(Finding("error", "frontier_missing_node", "active_frontier references a missing node", path="tree.json", node_id=node_id))
            continue
        if clean_string(node.get("lifecycle_state")) != "active":
            findings.append(Finding("error", "frontier_lifecycle_conflict", "active_frontier node is not lifecycle_state=active", path="tree.json", node_id=node_id))
        if clean_string(node.get("run_state")) not in {"pending", "running", "parsing"}:
            findings.append(Finding("warning", "frontier_run_state_unexpected", "active_frontier node run_state is not pending/running/parsing", path="tree.json", node_id=node_id))
    for node_id in closed:
        node = node_by_id.get(node_id)
        if node and clean_string(node.get("lifecycle_state")) != "closed":
            findings.append(Finding("warning", "closed_index_conflict", "closed_nodes entry is not lifecycle_state=closed", path="tree.json", node_id=node_id))
    for node_id in accepted:
        node = node_by_id.get(node_id)
        if node and clean_string(node.get("claim_status")) != "accepted_ts":
            findings.append(Finding("error", "accepted_index_conflict", "accepted_nodes entry is not claim_status=accepted_ts", path="tree.json", node_id=node_id))


def validate_manifest_accepted_ts(
    manifest: dict[str, Any],
    tree: dict[str, Any],
    node_json_by_id: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    """Validate manifest.current_accepted_ts against node and tree state."""

    current = clean_string(manifest.get("current_accepted_ts"))
    if not current:
        return
    node = node_json_by_id.get(current)
    if not node:
        findings.append(
            Finding(
                "error",
                "manifest_accepted_missing_node",
                "manifest current_accepted_ts references a missing node",
                path="manifest.json",
                node_id=current,
            )
        )
        return
    audit = derive_node_audit_view(node)
    if clean_string(audit.get("claim_status")) != "accepted_ts":
        findings.append(
            Finding(
                "error",
                "manifest_accepted_claim_conflict",
                "manifest current_accepted_ts node is not claim_status=accepted_ts",
                path="manifest.json",
                node_id=current,
            )
        )
    accepted_nodes = clean_string_set(list_or_empty(tree.get("accepted_nodes")))
    if current not in accepted_nodes:
        findings.append(
            Finding(
                "error",
                "manifest_accepted_index_conflict",
                "manifest current_accepted_ts is missing from tree.accepted_nodes",
                path="manifest.json",
                node_id=current,
            )
        )


__all__ = [
    "validate_tree_top_level_contract",
    "validate_parent_graph",
    "validate_indexes",
    "validate_manifest_accepted_ts",
]
