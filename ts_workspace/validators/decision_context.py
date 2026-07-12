"""Workspace-aware validation for mutation decisions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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

_PROTOCOL_VARIANT_RE = re.compile(r"^(irc_.*|integrator|step_size|corrector)", re.IGNORECASE)
_PROGRAM_FAILURE_RE = re.compile(r"(convergence_failed|scheduler_failure|parser_failure)", re.IGNORECASE)
_STRATEGY_TOKEN_RE = re.compile(r"(candidate|geometry|search|seed|method|route)", re.IGNORECASE)


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


def detect_decision_warnings(root: str | Path, decision: dict[str, Any]) -> list[dict[str, str]]:
    """Return non-blocking hints for suspicious decision patterns.

    Warnings never reject a decision; they surface likely-misclassification
    signals so the agent can reconsider. Empty list means no signals fired.
    """
    if decision.get("action") != "start_node":
        return []
    payload = decision.get("payload") or {}
    context = payload.get("branch_context") if isinstance(payload.get("branch_context"), dict) else {}
    relation = context.get("relation")
    if relation != "new_solution_branch":
        return []

    warnings: list[dict[str, str]] = []
    phase = payload.get("phase")
    changed_variable = str(context.get("changed_variable") or "")
    reason_code = str(context.get("reason_code") or "")

    if phase == "connectivity_validation" and changed_variable and _PROTOCOL_VARIANT_RE.match(changed_variable):
        warnings.append(
            {
                "code": "suspicious_new_solution_branch_for_protocol_variant",
                "message": (
                    "new_solution_branch used with an IRC-protocol changed_variable "
                    f"({changed_variable!r}) on a connectivity_validation node; "
                    "same-claim IRC parameter changes are usually continue_parent."
                ),
            }
        )
    if reason_code and _PROGRAM_FAILURE_RE.search(reason_code):
        warnings.append(
            {
                "code": "program_failure_used_as_new_solution_branch",
                "message": (
                    "new_solution_branch driven by a program-level failure "
                    f"({reason_code!r}); program failure is not automatically a new branch."
                ),
            }
        )

    hypothesis_ref = payload.get("hypothesis_ref") if isinstance(payload.get("hypothesis_ref"), dict) else {}
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    if hypothesis_id and _hypothesis_had_recent_tsfreq_support(Path(root), hypothesis_id) and (
        not changed_variable or not _STRATEGY_TOKEN_RE.search(changed_variable)
    ):
        warnings.append(
            {
                "code": "same_claim_reused_as_new_solution_branch",
                "message": (
                    "new_solution_branch under a hypothesis that already has a "
                    "TS/Freq-supported node in the last 24h with no candidate/geometry/search-level "
                    "changed_variable; reconsider continue_parent."
                ),
            }
        )

    return warnings


def _hypothesis_had_recent_tsfreq_support(root: Path, hypothesis_id: str) -> bool:
    tree_path = root / "tree.json"
    if not tree_path.exists():
        return False
    try:
        tree = read_json(tree_path)
    except Exception:  # noqa: BLE001
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for entry in tree.get("nodes", []):
        if entry.get("phase") != "tsfreq_validation":
            continue
        if entry.get("claim_verdict") != "supported":
            continue
        node_path = root / "nodes" / str(entry.get("node_id")) / "node.json"
        if not node_path.exists():
            continue
        try:
            node = read_json(node_path)
        except Exception:  # noqa: BLE001
            continue
        node_hyp = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
        if node_hyp.get("hypothesis_id") != hypothesis_id:
            continue
        closed_at = node.get("closure", {}).get("closed_at") if isinstance(node.get("closure"), dict) else None
        if not closed_at:
            continue
        try:
            closed_ts = datetime.fromisoformat(closed_at)
        except ValueError:
            continue
        if closed_ts.tzinfo is None:
            closed_ts = closed_ts.replace(tzinfo=timezone.utc)
        if closed_ts >= cutoff:
            return True
    return False


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
    payload = decision["payload"]
    repair = payload.get("repair_branch_anchor")
    if repair is not None:
        entries = repair if isinstance(repair, list) else [repair]
        for entry in entries:
            _validate_branch_anchor_repair(root, entry)

    evidence = payload.get("append_evidence")
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


def _validate_branch_anchor_repair(root: Path, repair: Any) -> None:
    if not isinstance(repair, dict):
        raise ContractError("repair_branch_anchor entries must be objects")
    node_id = repair.get("node_id")
    new_anchor = repair.get("new_anchor_node")
    if not isinstance(node_id, str) or not node_id:
        raise ContractError("repair_branch_anchor.node_id is required")
    if not isinstance(new_anchor, str) or not new_anchor:
        raise ContractError("repair_branch_anchor.new_anchor_node is required")
    if not (root / "nodes" / new_anchor / "node.json").exists():
        raise ContractError(f"repair_branch_anchor.new_anchor_node does not exist: {new_anchor}")
    node = _read_node(root, node_id)
    if node.get("lifecycle") == "running":
        raise ContractError(f"repair_branch_anchor refuses to reparent running node: {node_id}")
    context = node.get("branch_context") if isinstance(node.get("branch_context"), dict) else {}
    if context.get("relation") != "new_solution_branch":
        raise ContractError(f"repair_branch_anchor only applies to new_solution_branch nodes: {node_id}")
    hypothesis_ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
    source_node = _hypothesis_source_node(root, hypothesis_ref.get("hypothesis_id"))
    if source_node is None:
        raise ContractError(f"repair_branch_anchor cannot resolve hypothesis source_node for {node_id}")
    if new_anchor != source_node:
        raise ContractError(
            "repair_branch_anchor.new_anchor_node must match the hypothesis source_node: "
            f"node_id={node_id}, source_node={source_node}, new_anchor_node={new_anchor}"
        )


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
        _validate_solution_branch_anchor_matches_hypothesis_source(root, payload)
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


def _validate_solution_branch_anchor_matches_hypothesis_source(root: Path, payload: dict[str, Any]) -> None:
    context = payload.get("branch_context") if isinstance(payload.get("branch_context"), dict) else {}
    anchor_node_id = context.get("anchor_node")
    hypothesis_ref = payload.get("hypothesis_ref") if isinstance(payload.get("hypothesis_ref"), dict) else {}
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    source_node = _hypothesis_source_node(root, hypothesis_id)
    if source_node is None:
        return
    if anchor_node_id != source_node:
        raise ContractError(
            "new_solution_branch anchor_node must match the hypothesis source_node: "
            f"hypothesis_id={hypothesis_id}, source_node={source_node}, anchor_node={anchor_node_id}"
        )


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


def _hypothesis_source_node(root: Path, hypothesis_id: Any) -> str | None:
    if not isinstance(hypothesis_id, str) or not hypothesis_id:
        return None
    model = read_json(root / "mechanism_model.json")
    for hypothesis in model.get("hypotheses", []):
        if not isinstance(hypothesis, dict):
            continue
        if hypothesis.get("hypothesis_id") == hypothesis_id:
            source_node = hypothesis.get("source_node")
            return source_node if isinstance(source_node, str) and source_node else None
    return None


def _next_node_id(tree: dict[str, Any]) -> str:
    numbers = []
    for entry in tree.get("nodes", []):
        if not isinstance(entry, dict):
            continue
        node_id = entry.get("node_id", "")
        if node_id.startswith("n") and node_id[1:].isdigit():
            numbers.append(int(node_id[1:]))
    return f"n{(max(numbers) + 1) if numbers else 1:03d}"
