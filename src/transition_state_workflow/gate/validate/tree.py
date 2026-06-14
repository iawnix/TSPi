"""Tree, pathway, and event checks for ChemGate workspace validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.base.pathway_model import (
    PATHWAY_MODES,
    PATHWAY_STATUSES,
    STEP_STATUSES,
    derive_pathway_status,
)
from transition_state_workflow.config.state_contract import (
    TREE_LEGACY_TOP_LEVEL_FIELDS,
    VALID_BACKTRACK_EVENT_STATES,
)
from transition_state_workflow.gate.evidence import accepted_ts_missing_evidence_gates
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, relative_path_or_absolute

from .contracts import Finding
from .evidence import group_evidence_records_by_node


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

    active = set(clean_string(item) for item in list_or_empty(tree.get("active_frontier")) if clean_string(item))
    closed = set(clean_string(item) for item in list_or_empty(tree.get("closed_nodes")) if clean_string(item))
    accepted = set(clean_string(item) for item in list_or_empty(tree.get("accepted_nodes")) if clean_string(item))
    graph_active = set(clean_string(item) for item in list_or_empty(graph.get("active_frontier")) if clean_string(item))
    graph_closed = set(clean_string(item) for item in list_or_empty(graph.get("closed_nodes")) if clean_string(item))
    graph_accepted = set(clean_string(item) for item in list_or_empty(graph.get("accepted_nodes")) if clean_string(item))
    node_by_id = {clean_string(node.get("id")): node for node in list_or_empty(graph.get("nodes")) if isinstance(node, dict)}
    if active != graph_active:
        findings.append(Finding("warning", "active_index_drift", "tree active_frontier differs from normalized active_frontier", path="tree.json"))
    if closed != graph_closed:
        findings.append(Finding("warning", "closed_index_drift", "tree closed_nodes differs from normalized closed_nodes", path="tree.json"))
    if accepted != graph_accepted:
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
    if clean_string(node.get("claim_status")) != "accepted_ts":
        findings.append(
            Finding(
                "error",
                "manifest_accepted_claim_conflict",
                "manifest current_accepted_ts node is not claim_status=accepted_ts",
                path="manifest.json",
                node_id=current,
            )
        )
    accepted_nodes = {clean_string(item) for item in list_or_empty(tree.get("accepted_nodes")) if clean_string(item)}
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


def validate_pathway_model(
    source: Path,
    model: dict[str, Any],
    node_json_by_id: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate optional pathway_model.json and node step references."""

    node_step_refs = {
        node_id: (
            clean_string(node.get("pathway_id")),
            clean_string(node.get("elementary_step_id")),
        )
        for node_id, node in node_json_by_id.items()
        if clean_string(node.get("pathway_id")) or clean_string(node.get("elementary_step_id"))
    }
    if not model:
        for node_id in node_step_refs:
            findings.append(
                Finding(
                    "error",
                    "pathway_model_missing",
                    "node records pathway_id/elementary_step_id but pathway_model.json is missing",
                    path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                    node_id=node_id,
                )
            )
        return

    if clean_string(model.get("schema")) != "tssearch-pathway-model-v1":
        findings.append(Finding("error", "pathway_schema_invalid", "pathway_model.json must declare schema=tssearch-pathway-model-v1", path="pathway_model.json"))
    mode = clean_string(model.get("mode"))
    if mode not in PATHWAY_MODES:
        findings.append(Finding("error", "pathway_mode_invalid", f"invalid pathway mode: {mode}", path="pathway_model.json"))
    pathways = list_or_empty(model.get("pathways"))
    if not isinstance(model.get("pathways"), list):
        findings.append(Finding("error", "pathways_not_list", "pathway_model.json pathways must be a list", path="pathway_model.json"))
        pathways = []

    pathway_ids: set[str] = set()
    step_index: dict[tuple[str, str], dict[str, Any]] = {}
    accepted_step_by_node: dict[str, tuple[str, str]] = {}
    records_by_node = group_evidence_records_by_node(evidence)
    known_nodes = set(node_json_by_id)
    for p_index, pathway in enumerate(pathways):
        if not isinstance(pathway, dict):
            findings.append(Finding("error", "pathway_not_object", f"pathways[{p_index}] is not an object", path="pathway_model.json"))
            continue
        pathway_id = clean_string(pathway.get("pathway_id"))
        if not pathway_id:
            findings.append(Finding("error", "pathway_missing_id", f"pathways[{p_index}] missing pathway_id", path="pathway_model.json"))
            continue
        if pathway_id in pathway_ids:
            findings.append(Finding("error", "duplicate_pathway_id", f"duplicate pathway_id: {pathway_id}", path="pathway_model.json"))
        pathway_ids.add(pathway_id)
        status = clean_string(pathway.get("status")) or "hypothesis"
        if status not in PATHWAY_STATUSES:
            findings.append(Finding("error", "pathway_status_invalid", f"invalid pathway status: {status}", path="pathway_model.json"))
        steps = list_or_empty(pathway.get("steps"))
        if not isinstance(pathway.get("steps"), list):
            findings.append(Finding("error", "pathway_steps_not_list", f"pathway {pathway_id} steps must be a list", path="pathway_model.json"))
            steps = []
        step_ids: set[str] = set()
        for s_index, step in enumerate(steps):
            if not isinstance(step, dict):
                findings.append(Finding("error", "pathway_step_not_object", f"{pathway_id}.steps[{s_index}] is not an object", path="pathway_model.json"))
                continue
            step_id = clean_string(step.get("step_id"))
            if not step_id:
                findings.append(Finding("error", "pathway_step_missing_id", f"{pathway_id}.steps[{s_index}] missing step_id", path="pathway_model.json"))
                continue
            key = (pathway_id, step_id)
            if step_id in step_ids:
                findings.append(Finding("error", "duplicate_pathway_step_id", f"duplicate step_id in {pathway_id}: {step_id}", path="pathway_model.json"))
            step_ids.add(step_id)
            step_index[key] = step
            step_status = clean_string(step.get("status")) or "missing"
            if step_status not in STEP_STATUSES:
                findings.append(Finding("error", "pathway_step_status_invalid", f"invalid step status: {step_status}", path="pathway_model.json"))
            accepted_node = clean_string(step.get("accepted_ts_node"))
            if step_status == "accepted_ts" and not accepted_node:
                findings.append(Finding("error", "pathway_step_missing_accepted_node", "accepted pathway step is missing accepted_ts_node", path="pathway_model.json"))
            if accepted_node:
                node = node_json_by_id.get(accepted_node)
                if accepted_node not in known_nodes or not node:
                    findings.append(Finding("error", "pathway_step_missing_node", "pathway step accepted_ts_node is missing", path="pathway_model.json", node_id=accepted_node))
                elif clean_string(node.get("claim_status")) != "accepted_ts":
                    findings.append(Finding("error", "pathway_step_node_not_accepted_ts", "pathway step accepted_ts_node is not claim_status=accepted_ts", path="pathway_model.json", node_id=accepted_node))
                else:
                    previous_step = accepted_step_by_node.get(accepted_node)
                    if previous_step and previous_step != (pathway_id, step_id):
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_duplicate_accepted_node",
                                "one accepted_ts node is bound to multiple pathway steps",
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
                    accepted_step_by_node[accepted_node] = (pathway_id, step_id)
                    node_pathway_id = clean_string(node.get("pathway_id"))
                    node_step_id = clean_string(node.get("elementary_step_id"))
                    if node_pathway_id != pathway_id or node_step_id != step_id:
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_node_binding_conflict",
                                "pathway step accepted_ts_node does not declare the same pathway_id/elementary_step_id",
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
                    missing = accepted_ts_missing_evidence_gates(source, records_by_node.get(accepted_node, []))
                    if missing:
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_accepted_ts_missing_evidence_gates",
                                "pathway step accepted_ts_node lacks accepted_ts evidence gates: " + ", ".join(missing),
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
            status_node = clean_string(step.get("status_node"))
            if status_node and status_node not in known_nodes:
                findings.append(
                    Finding(
                        "error",
                        "pathway_step_status_node_missing",
                        "pathway step status_node is missing",
                        path="pathway_model.json",
                        node_id=status_node,
                    )
                )
        if steps:
            derived_status = derive_pathway_status([step for step in steps if isinstance(step, dict)])
            if status != derived_status:
                findings.append(
                    Finding(
                        "warning",
                        "pathway_status_not_derived",
                        f"pathway {pathway_id} status is {status}, expected derived status {derived_status}",
                        path="pathway_model.json",
                    )
                )

    active_pathway = clean_string(model.get("active_pathway"))
    if active_pathway and active_pathway not in pathway_ids:
        findings.append(Finding("error", "active_pathway_missing", "active_pathway does not reference an existing pathway", path="pathway_model.json"))

    for node_id, (pathway_id, step_id) in node_step_refs.items():
        node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
        if not pathway_id or not step_id:
            findings.append(Finding("error", "node_pathway_step_pair_incomplete", "pathway_id and elementary_step_id must be provided together", path=node_path, node_id=node_id))
            continue
        step = step_index.get((pathway_id, step_id))
        if not step:
            findings.append(Finding("error", "node_pathway_step_missing", "node references missing pathway step", path=node_path, node_id=node_id))
            continue
        node = node_json_by_id.get(node_id) or {}
        if clean_string(node.get("claim_status")) == "accepted_ts" and clean_string(step.get("accepted_ts_node")) != node_id:
            findings.append(
                Finding(
                    "error",
                    "accepted_node_not_bound_to_pathway_step",
                    "accepted_ts node declares a pathway step but pathway_model does not bind that step to this node",
                    path=node_path,
                    node_id=node_id,
                )
            )


def validate_tree_events(
    tree: dict[str, Any],
    node_ids: list[str],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate canonical timeline and backtrack events in tree.json."""

    if "branch_decisions" in tree:
        findings.append(Finding("error", "legacy_branch_decisions", "tree.json contains legacy branch_decisions; use events[]", path="tree.json"))
    if "backtrack_edges" in tree:
        findings.append(Finding("error", "legacy_backtrack_edges", "tree.json contains legacy backtrack_edges; use backtrack_events[]", path="tree.json"))
    known_nodes = set(node_ids)
    evidence_ids = {clean_string(item.get("evidence_id")) for item in list_or_empty(evidence.get("records")) if isinstance(item, dict)}
    seen_event_ids: set[str] = set()
    for index, event in enumerate(list_or_empty(tree.get("events"))):
        if not isinstance(event, dict):
            findings.append(Finding("error", "event_not_object", f"events[{index}] is not an object", path="tree.json"))
            continue
        event_id = clean_string(event.get("event_id"))
        node_id = clean_string(event.get("node_id"))
        if not event_id:
            findings.append(Finding("error", "event_missing_id", "event missing event_id", path="tree.json", node_id=node_id))
        elif event_id in seen_event_ids:
            findings.append(Finding("error", "duplicate_event_id", f"duplicate event_id: {event_id}", path="tree.json", node_id=node_id))
        else:
            seen_event_ids.add(event_id)
        if node_id and node_id not in known_nodes:
            findings.append(Finding("error", "event_missing_node", "event references missing node", path="tree.json", node_id=node_id))
        if "evidence" in event:
            findings.append(Finding("error", "legacy_event_evidence", "event uses legacy evidence; use evidence_refs", path="tree.json", node_id=node_id))
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "event_missing_evidence_ref", f"event references missing evidence_id {ref_id}", path="tree.json", node_id=node_id))
    seen_backtrack_ids: set[str] = set()
    active_backtrack_ids: list[str] = []
    for index, event in enumerate(list_or_empty(tree.get("backtrack_events"))):
        if not isinstance(event, dict):
            findings.append(Finding("error", "backtrack_event_not_object", f"backtrack_events[{index}] is not an object", path="tree.json"))
            continue
        event_id = clean_string(event.get("id"))
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        if not event_id:
            findings.append(Finding("error", "backtrack_missing_id", "backtrack event missing id", path="tree.json", node_id=from_node))
        elif event_id in seen_backtrack_ids:
            findings.append(Finding("error", "duplicate_backtrack_event_id", f"duplicate backtrack event id: {event_id}", path="tree.json", node_id=from_node))
        else:
            seen_backtrack_ids.add(event_id)
        if from_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_from_node", "backtrack from_node is missing", path="tree.json", node_id=from_node))
        if to_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_to_node", "backtrack to_node is missing", path="tree.json", node_id=to_node))
        state = clean_string(event.get("event_state")) or "active"
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", path="tree.json", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id or f"backtrack_events[{index}]")
        if "evidence" in event:
            findings.append(Finding("error", "legacy_backtrack_evidence", "backtrack event uses legacy evidence; use evidence_refs", path="tree.json", node_id=from_node))
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "backtrack_missing_evidence_ref", f"backtrack references missing evidence_id {ref_id}", path="tree.json", node_id=from_node))
    if len(active_backtrack_ids) > 1:
        findings.append(
            Finding(
                "error",
                "multiple_active_backtracks",
                f"tree.json has multiple active backtrack events: {', '.join(active_backtrack_ids)}",
                path="tree.json",
            )
        )


def validate_events(graph: dict[str, Any], node_ids: list[str], findings: list[Finding]) -> None:
    """Validate normalized graph events after normalizer processing."""

    known_nodes = set(node_ids)
    evidence_ids = {clean_string(item.get("evidence_id")) for item in list_or_empty(graph.get("evidence", {}).get("records")) if isinstance(item, dict)}
    for event in list_or_empty(graph.get("events")):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("event_id"))
        node_id = clean_string(event.get("node_id"))
        if not event_id:
            findings.append(Finding("error", "event_missing_id", "event missing event_id"))
        if node_id and node_id not in known_nodes:
            findings.append(Finding("error", "event_missing_node", "event references missing node", node_id=node_id))
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "event_missing_evidence_ref", f"event references missing evidence_id {ref_id}", node_id=node_id))
    active_backtrack_ids: list[str] = []
    for index, event in enumerate(list_or_empty(graph.get("backtrack_events"))):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("id")) or f"backtrack_events[{index}]"
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        if from_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_from_node", "backtrack from_node is missing", node_id=from_node))
        if to_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_to_node", "backtrack to_node is missing", node_id=to_node))
        state = clean_string(event.get("event_state"))
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id)
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "backtrack_missing_evidence_ref", f"backtrack references missing evidence_id {ref_id}", node_id=from_node))
    if len(active_backtrack_ids) > 1:
        findings.append(
            Finding(
                "error",
                "multiple_active_backtracks",
                f"normalized graph has multiple active backtrack events: {', '.join(active_backtrack_ids)}",
            )
        )


__all__ = [
    "validate_tree_top_level_contract",
    "validate_parent_graph",
    "validate_indexes",
    "validate_manifest_accepted_ts",
    "validate_pathway_model",
    "validate_tree_events",
    "validate_events",
]
