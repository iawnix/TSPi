"""Workspace-aware validation for mutation decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import read_json
from .decision import HYPOTHESIS_REF_PHASES, INITIAL_HYPOTHESIS_PHASES, ContractError, validate_decision
from .workspace import REQUIRED_FILES, UNRESOLVED_TERMINAL_VERDICTS


def validate_decision_for_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    """Validate a decision against both JSON shape and current workspace state."""

    validate_decision(decision)
    if decision.get("action") == "start_node":
        _validate_start_node_context(Path(root), decision)
    elif decision.get("action") == "end_node":
        _validate_end_node_context(Path(root), decision)
    return decision


def _validate_start_node_context(root: Path, decision: dict[str, Any]) -> None:
    _require_initialized(root)
    tree = read_json(root / "tree.json")
    payload = decision["payload"]
    node_id = payload.get("node_id") or _next_node_id(tree)
    if (root / "nodes" / node_id / "node.json").exists():
        raise ContractError(f"node already exists: {node_id}")

    ordered_node_ids = _ordered_node_ids(tree)
    node_ids = set(ordered_node_ids)
    _validate_backtrack_refs(payload.get("backtrack"), node_ids)
    if not ordered_node_ids:
        if node_id != "n000":
            raise ContractError("first node must be explicit n000 endpoint/preflight hypothesis node")
        if payload.get("phase") not in INITIAL_HYPOTHESIS_PHASES:
            raise ContractError("first node phase must be endpoint or preflight")
        return

    if payload.get("phase") in HYPOTHESIS_REF_PHASES:
        _validate_hypothesis_ref_exists(root, payload["hypothesis_ref"])

    previous_id = ordered_node_ids[-1]
    previous = _read_node(root, previous_id)
    if not _is_unresolved_closed(previous):
        return

    parent_by_id = _parent_map(root, ordered_node_ids)
    parent_by_id[node_id] = payload.get("parent_node")
    if _is_descendant(node_id, previous_id, parent_by_id):
        return

    backtrack = payload.get("backtrack")
    if backtrack is None:
        verdict = _claim_verdict(previous)
        raise ContractError(
            "payload.backtrack is required when start_node opens a replacement "
            f"branch after terminal {verdict} node {previous_id}"
        )
    if backtrack.get("from_node") != previous_id:
        raise ContractError(
            "payload.backtrack.from_node must match the terminal unresolved "
            f"node being replaced: {previous_id}"
        )


def _validate_end_node_context(root: Path, decision: dict[str, Any]) -> None:
    _require_initialized(root)
    payload = decision["payload"]
    node = _read_node(root, payload["node_id"])
    phase = node.get("phase")
    closure = payload["closure"]
    mechanism = closure.get("mechanism", {}) if isinstance(closure.get("mechanism"), dict) else {}

    if phase in INITIAL_HYPOTHESIS_PHASES:
        if closure.get("program_status") == "completed":
            if not isinstance(node.get("initial_mechanism_hypothesis"), dict):
                raise ContractError("completed endpoint/preflight node requires initial_mechanism_hypothesis")
        return

    if phase in HYPOTHESIS_REF_PHASES:
        node_ref = node.get("hypothesis_ref")
        mechanism_ref = mechanism.get("hypothesis_ref")
        if not isinstance(node_ref, dict):
            raise ContractError("node.hypothesis_ref is required for mechanism phase closure")
        if not isinstance(mechanism_ref, dict):
            raise ContractError("closure.mechanism.hypothesis_ref is required for mechanism phase closure")
        if mechanism_ref.get("hypothesis_id") != node_ref.get("hypothesis_id"):
            raise ContractError("closure.mechanism.hypothesis_ref must match node.hypothesis_ref")
        _validate_hypothesis_ref_exists(root, mechanism_ref)


def _require_initialized(root: Path) -> None:
    missing = [filename for filename in REQUIRED_FILES if not (root / filename).exists()]
    if missing:
        raise ContractError(f"workspace is not initialized; missing {', '.join(sorted(missing))}")


def _ordered_node_ids(tree: dict[str, Any]) -> list[str]:
    nodes = tree.get("nodes", [])
    if not isinstance(nodes, list):
        raise ContractError("tree.nodes must be a list")
    ordered: list[str] = []
    for entry in nodes:
        if not isinstance(entry, dict):
            raise ContractError("tree node entry must be an object")
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise ContractError("tree node missing node_id")
        ordered.append(node_id)
    return ordered


def _validate_backtrack_refs(backtrack: Any, node_ids: set[str]) -> None:
    if backtrack is None:
        return
    for field in ("from_node", "to_node"):
        node_id = backtrack.get(field)
        if node_id not in node_ids:
            raise ContractError(f"payload.backtrack.{field} does not exist: {node_id}")


def _validate_hypothesis_ref_exists(root: Path, hypothesis_ref: dict[str, Any]) -> None:
    model = read_json(root / "mechanism_model.json")
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    ids = {
        item.get("hypothesis_id")
        for item in model.get("hypotheses", [])
        if isinstance(item, dict)
    }
    if hypothesis_id not in ids:
        raise ContractError(f"unknown hypothesis_ref.hypothesis_id: {hypothesis_id}")


def _parent_map(root: Path, ordered_node_ids: list[str]) -> dict[str, Any]:
    parents: dict[str, Any] = {}
    for node_id in ordered_node_ids:
        parents[node_id] = _read_node(root, node_id).get("parent_node")
    return parents


def _read_node(root: Path, node_id: str) -> dict[str, Any]:
    node_path = root / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise ContractError(f"missing node.json for {node_id}")
    node = read_json(node_path)
    if not isinstance(node, dict):
        raise ContractError(f"node.json for {node_id} must be an object")
    return node


def _is_unresolved_closed(node: dict[str, Any]) -> bool:
    return node.get("lifecycle") in {"closed", "stopped"} and _claim_verdict(node) in UNRESOLVED_TERMINAL_VERDICTS


def _claim_verdict(node: dict[str, Any]) -> str | None:
    closure = node.get("closure")
    if isinstance(closure, dict):
        return closure.get("claim_verdict")
    return node.get("claim_verdict")


def _is_descendant(node_id: str, ancestor_id: str, parent_by_id: dict[str, Any]) -> bool:
    current = parent_by_id.get(node_id)
    seen: set[str] = set()
    while isinstance(current, str) and current and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = parent_by_id.get(current)
    return False


def _next_node_id(tree: dict[str, Any]) -> str:
    numbers = []
    for entry in tree.get("nodes", []):
        if not isinstance(entry, dict):
            continue
        node_id = entry.get("node_id", "")
        if node_id.startswith("n") and node_id[1:].isdigit():
            numbers.append(int(node_id[1:]))
    return f"n{(max(numbers) + 1) if numbers else 1:03d}"
