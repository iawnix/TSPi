"""Branch node-reference validation for TS-search workspaces."""

from __future__ import annotations

from typing import Any


class BranchReferenceError(ValueError):
    """Raised when a branch parent or input reference would break the tree."""


def clean_optional_node_ref(value: object) -> str:
    """Normalize optional node references from CLI or tree JSON."""

    return str(value or "").strip()


def normalize_branch_input_refs(raw_refs: tuple[str, ...] | list[str]) -> list[str]:
    """Return stable, de-duplicated dependency node ids from input refs."""

    refs: list[str] = []
    for raw in raw_refs:
        ref = clean_optional_node_ref(raw)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def parent_graph_would_cycle(*, node_id: str, parent_id: str | None, existing_nodes: dict[str, Any]) -> bool:
    """Return true if setting node_id -> parent_id would create a parent cycle."""

    seen = {node_id}
    current = clean_optional_node_ref(parent_id)
    while current:
        if current in seen:
            return True
        seen.add(current)
        payload = existing_nodes.get(current)
        if not isinstance(payload, dict):
            return False
        current = clean_optional_node_ref(payload.get("parent_id"))
    return False


def validate_branch_references(
    *,
    node_id: str,
    parent_id: str | None,
    input_refs: list[str],
    existing_nodes: dict[str, Any],
) -> None:
    """Reject branch references that would break the hypothesis tree."""

    clean_parent_id = clean_optional_node_ref(parent_id)
    if clean_parent_id == node_id:
        raise BranchReferenceError(f"node cannot be its own parent: {node_id}")
    if clean_parent_id and clean_parent_id not in existing_nodes:
        raise BranchReferenceError(f"parent node does not exist in tree.json: {clean_parent_id}")
    for input_ref in input_refs:
        if input_ref == node_id:
            raise BranchReferenceError(f"node cannot depend on itself through --input-ref: {node_id}")
        if input_ref not in existing_nodes:
            raise BranchReferenceError(f"input reference node does not exist in tree.json: {input_ref}")
    if parent_graph_would_cycle(node_id=node_id, parent_id=clean_parent_id, existing_nodes=existing_nodes):
        raise BranchReferenceError(f"parent link would create a cycle for node: {node_id}")


__all__ = [
    "BranchReferenceError",
    "clean_optional_node_ref",
    "normalize_branch_input_refs",
    "parent_graph_would_cycle",
    "validate_branch_references",
]
