"""Workspace-aware validation for mutation decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_policy import node_owner_from_artifact_path, role_matches_phase
from ..evidence_gates import gate_artifact_metadata_diagnostic
from ..io import read_json
from .decision import (
    ANCHORED_BRANCH_RELATIONS,
    HYPOTHESIS_REF_PHASES,
    INITIAL_HYPOTHESIS_PHASES,
    ContractError,
    validate_decision,
)
from .workspace import REQUIRED_FILES


def validate_decision_for_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    """Validate a decision against both JSON shape and current workspace state."""

    validate_decision(decision)
    if decision.get("action") == "start_node":
        _validate_start_node_context(Path(root), decision)
    elif decision.get("action") == "end_node":
        _validate_end_node_context(Path(root), decision)
    elif decision.get("action") == "update_workspace":
        _validate_update_workspace_context(Path(root), decision)
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
    if not ordered_node_ids:
        if node_id != "n000":
            raise ContractError("first node must be explicit n000 endpoint/preflight hypothesis node")
        if payload.get("phase") not in INITIAL_HYPOTHESIS_PHASES:
            raise ContractError("first node phase must be endpoint or preflight")
        return

    _validate_parent_ref(payload.get("parent_node"), node_ids)
    _validate_branch_context(root, payload, node_ids)

    if payload.get("phase") in HYPOTHESIS_REF_PHASES:
        _validate_hypothesis_ref_exists(root, payload["hypothesis_ref"])


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


def _validate_update_workspace_context(root: Path, decision: dict[str, Any]) -> None:
    _require_initialized(root)
    evidence = decision["payload"].get("append_evidence")
    if evidence is None:
        return
    entries = evidence if isinstance(evidence, list) else [evidence]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        node = _read_node(root, node_id)
        path = entry.get("path")
        if isinstance(path, str) and path.strip() and not role_matches_phase(entry.get("role"), node.get("phase")):
            raise ContractError(
                "append_evidence.role does not match the node phase for a path-bearing artifact: "
                f"role={entry.get('role')!r}, node={node_id}, phase={node.get('phase')!r}"
            )
        owner = node_owner_from_artifact_path(path)
        if owner is not None and owner != node_id:
            raise ContractError(
                "append_evidence.path points to a different node artifact directory: "
                f"path owner={owner}, evidence.node_id={node_id}. "
                "Write the validation artifact under the current node and record upstream files "
                "in nodes/<node>/outputs/artifact_manifest.json consumed_artifacts."
            )
        gate_diagnostic = gate_artifact_metadata_diagnostic(entry)
        if gate_diagnostic:
            raise ContractError(gate_diagnostic)


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


def _validate_parent_ref(parent_node: Any, node_ids: set[str]) -> None:
    if parent_node is None:
        return
    if parent_node not in node_ids:
        raise ContractError(f"payload.parent_node does not exist: {parent_node}")


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


def _validate_branch_context(root: Path, payload: dict[str, Any], node_ids: set[str]) -> None:
    context = payload.get("branch_context")
    if not isinstance(context, dict):
        raise ContractError("payload.branch_context is required after n000")

    relation = context.get("relation")
    from_node_id = context.get("from_node")
    anchor_node_id = context.get("anchor_node")
    if from_node_id not in node_ids:
        raise ContractError(f"payload.branch_context.from_node does not exist: {from_node_id}")
    if anchor_node_id not in node_ids:
        raise ContractError(f"payload.branch_context.anchor_node does not exist: {anchor_node_id}")

    from_node = _read_node(root, str(from_node_id))
    if relation == "continue_parent":
        _require_parent_matches(payload, from_node_id, "from_node", relation)
    elif relation in ANCHORED_BRANCH_RELATIONS:
        _require_parent_matches(payload, anchor_node_id, "anchor_node", relation)
    if relation == "new_solution_branch":
        _validate_new_solution_branch(from_node, payload)
    elif relation == "new_hypothesis_branch":
        _validate_new_hypothesis_branch(from_node, payload)
    elif relation == "new_pathway_branch":
        if not isinstance(payload.get("pathway_ref"), dict):
            raise ContractError("new_pathway_branch requires payload.pathway_ref")
    elif relation == "administrative_followup":
        if not isinstance(context.get("reason_code"), str) or not context["reason_code"].strip():
            raise ContractError("administrative_followup requires payload.branch_context.reason_code")


def _require_parent_matches(payload: dict[str, Any], expected_node: Any, expected_field: str, relation: Any) -> None:
    parent_node = payload.get("parent_node")
    if parent_node != expected_node:
        raise ContractError(f"{relation} branch_context requires parent_node to match {expected_field}")


def _validate_new_solution_branch(from_node: dict[str, Any], payload: dict[str, Any]) -> None:
    new_ref = payload.get("hypothesis_ref")
    if not isinstance(new_ref, dict):
        raise ContractError("new_solution_branch requires payload.hypothesis_ref")
    solution_ref = payload.get("solution_ref")
    if not isinstance(solution_ref, dict) or not str(solution_ref.get("solution_id") or "").strip():
        raise ContractError("new_solution_branch requires payload.solution_ref.solution_id")
    from_ref = from_node.get("hypothesis_ref")
    if isinstance(from_ref, dict) and from_ref.get("hypothesis_id") != new_ref.get("hypothesis_id"):
        raise ContractError("new_solution_branch must keep the same hypothesis_id")
    from_solution = from_node.get("solution_ref")
    if isinstance(from_solution, dict) and from_solution.get("solution_id") == solution_ref.get("solution_id"):
        raise ContractError("new_solution_branch requires a new solution_ref.solution_id")


def _validate_new_hypothesis_branch(from_node: dict[str, Any], payload: dict[str, Any]) -> None:
    new_ref = payload.get("hypothesis_ref")
    if payload.get("phase") in HYPOTHESIS_REF_PHASES and not isinstance(new_ref, dict):
        raise ContractError("new_hypothesis_branch requires payload.hypothesis_ref for mechanism phases")
    from_ref = from_node.get("hypothesis_ref")
    if isinstance(from_ref, dict) and isinstance(new_ref, dict) and from_ref.get("hypothesis_id") == new_ref.get("hypothesis_id"):
        raise ContractError("new_hypothesis_branch requires a different hypothesis_id")


def _read_node(root: Path, node_id: str) -> dict[str, Any]:
    node_path = root / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise ContractError(f"missing node.json for {node_id}")
    node = read_json(node_path)
    if not isinstance(node, dict):
        raise ContractError(f"node.json for {node_id} must be an object")
    return node


def _next_node_id(tree: dict[str, Any]) -> str:
    numbers = []
    for entry in tree.get("nodes", []):
        if not isinstance(entry, dict):
            continue
        node_id = entry.get("node_id", "")
        if node_id.startswith("n") and node_id[1:].isdigit():
            numbers.append(int(node_id[1:]))
    return f"n{(max(numbers) + 1) if numbers else 1:03d}"
