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

from .common import (
    clean_string_set,
    evidence_ids_from_records,
    iter_object_records,
    register_unique_id,
    require_list_field,
    validate_evidence_refs,
    validate_known_node_ref,
)
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

    active = clean_string_set(list_or_empty(tree.get("active_frontier")))
    closed = clean_string_set(list_or_empty(tree.get("closed_nodes")))
    accepted = clean_string_set(list_or_empty(tree.get("accepted_nodes")))
    graph_active = clean_string_set(list_or_empty(graph.get("active_frontier")))
    graph_closed = clean_string_set(list_or_empty(graph.get("closed_nodes")))
    graph_accepted = clean_string_set(list_or_empty(graph.get("accepted_nodes")))
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
    pathways = require_list_field(
        model,
        "pathways",
        findings,
        code="pathways_not_list",
        message="pathway_model.json pathways must be a list",
        path="pathway_model.json",
    )

    pathway_ids: set[str] = set()
    step_index: dict[tuple[str, str], dict[str, Any]] = {}
    accepted_step_by_node: dict[str, tuple[str, str]] = {}
    records_by_node = group_evidence_records_by_node(evidence)
    known_nodes = set(node_json_by_id)
    for p_index, pathway in iter_object_records(
        pathways,
        findings,
        code="pathway_not_object",
        message_template="pathways[{index}] is not an object",
        path="pathway_model.json",
    ):
        pathway_id = register_unique_id(
            pathway.get("pathway_id"),
            pathway_ids,
            findings,
            missing_code="pathway_missing_id",
            missing_message=f"pathways[{p_index}] missing pathway_id",
            duplicate_code="duplicate_pathway_id",
            duplicate_message_template="duplicate pathway_id: {value}",
            path="pathway_model.json",
        )
        if not pathway_id:
            continue
        status = clean_string(pathway.get("status")) or "hypothesis"
        if status not in PATHWAY_STATUSES:
            findings.append(Finding("error", "pathway_status_invalid", f"invalid pathway status: {status}", path="pathway_model.json"))
        steps = require_list_field(
            pathway,
            "steps",
            findings,
            code="pathway_steps_not_list",
            message=f"pathway {pathway_id} steps must be a list",
            path="pathway_model.json",
        )
        step_ids: set[str] = set()
        for s_index, step in iter_object_records(
            steps,
            findings,
            code="pathway_step_not_object",
            message_template=f"{pathway_id}.steps[{{index}}] is not an object",
            path="pathway_model.json",
        ):
            step_id = register_unique_id(
                step.get("step_id"),
                step_ids,
                findings,
                missing_code="pathway_step_missing_id",
                missing_message=f"{pathway_id}.steps[{s_index}] missing step_id",
                duplicate_code="duplicate_pathway_step_id",
                duplicate_message_template=f"duplicate step_id in {pathway_id}: {{value}}",
                path="pathway_model.json",
            )
            if not step_id:
                continue
            key = (pathway_id, step_id)
            step_index[key] = step
            step_status = clean_string(step.get("status")) or "missing"
            if step_status not in STEP_STATUSES:
                findings.append(Finding("error", "pathway_step_status_invalid", f"invalid step status: {step_status}", path="pathway_model.json"))
            accepted_node = clean_string(step.get("accepted_ts_node"))
            if step_status == "accepted_ts" and not accepted_node:
                findings.append(Finding("error", "pathway_step_missing_accepted_node", "accepted pathway step is missing accepted_ts_node", path="pathway_model.json"))
            if accepted_node:
                node = node_json_by_id.get(accepted_node)
                validate_known_node_ref(
                    accepted_node,
                    known_nodes,
                    findings,
                    code="pathway_step_missing_node",
                    message="pathway step accepted_ts_node is missing",
                    path="pathway_model.json",
                    node_id=accepted_node,
                    allow_empty=False,
                )
                if not node:
                    if accepted_node in known_nodes:
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_missing_node",
                                "pathway step accepted_ts_node is missing",
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
                    continue
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
            validate_known_node_ref(
                status_node,
                known_nodes,
                findings,
                code="pathway_step_status_node_missing",
                message="pathway step status_node is missing",
                path="pathway_model.json",
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
    evidence_ids = evidence_ids_from_records(evidence)
    seen_event_ids: set[str] = set()
    for _index, event in iter_object_records(
        list_or_empty(tree.get("events")),
        findings,
        code="event_not_object",
        message_template="events[{index}] is not an object",
        path="tree.json",
    ):
        node_id = clean_string(event.get("node_id"))
        register_unique_id(
            event.get("event_id"),
            seen_event_ids,
            findings,
            missing_code="event_missing_id",
            missing_message="event missing event_id",
            duplicate_code="duplicate_event_id",
            duplicate_message_template="duplicate event_id: {value}",
            path="tree.json",
            node_id=node_id,
        )
        validate_known_node_ref(
            node_id,
            known_nodes,
            findings,
            code="event_missing_node",
            message="event references missing node",
            path="tree.json",
        )
        if "evidence" in event:
            findings.append(Finding("error", "legacy_event_evidence", "event uses legacy evidence; use evidence_refs", path="tree.json", node_id=node_id))
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="event_missing_evidence_ref",
            message_template="event references missing evidence_id {ref_id}",
            path="tree.json",
            node_id=node_id,
        )
    seen_backtrack_ids: set[str] = set()
    active_backtrack_ids: list[str] = []
    for index, event in iter_object_records(
        list_or_empty(tree.get("backtrack_events")),
        findings,
        code="backtrack_event_not_object",
        message_template="backtrack_events[{index}] is not an object",
        path="tree.json",
    ):
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        event_id = register_unique_id(
            event.get("id"),
            seen_backtrack_ids,
            findings,
            missing_code="backtrack_missing_id",
            missing_message="backtrack event missing id",
            duplicate_code="duplicate_backtrack_event_id",
            duplicate_message_template="duplicate backtrack event id: {value}",
            path="tree.json",
            node_id=from_node,
        )
        validate_known_node_ref(
            from_node,
            known_nodes,
            findings,
            code="backtrack_missing_from_node",
            message="backtrack from_node is missing",
            path="tree.json",
            allow_empty=False,
        )
        validate_known_node_ref(
            to_node,
            known_nodes,
            findings,
            code="backtrack_missing_to_node",
            message="backtrack to_node is missing",
            path="tree.json",
            allow_empty=False,
        )
        state = clean_string(event.get("event_state")) or "active"
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", path="tree.json", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id or f"backtrack_events[{index}]")
        if "evidence" in event:
            findings.append(Finding("error", "legacy_backtrack_evidence", "backtrack event uses legacy evidence; use evidence_refs", path="tree.json", node_id=from_node))
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="backtrack_missing_evidence_ref",
            message_template="backtrack references missing evidence_id {ref_id}",
            path="tree.json",
            node_id=from_node,
        )
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
    evidence_ids = evidence_ids_from_records(graph.get("evidence", {}))
    for event in list_or_empty(graph.get("events")):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("event_id"))
        node_id = clean_string(event.get("node_id"))
        if not event_id:
            findings.append(Finding("error", "event_missing_id", "event missing event_id"))
        validate_known_node_ref(
            node_id,
            known_nodes,
            findings,
            code="event_missing_node",
            message="event references missing node",
        )
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="event_missing_evidence_ref",
            message_template="event references missing evidence_id {ref_id}",
            node_id=node_id,
        )
    active_backtrack_ids: list[str] = []
    for index, event in enumerate(list_or_empty(graph.get("backtrack_events"))):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("id")) or f"backtrack_events[{index}]"
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        validate_known_node_ref(
            from_node,
            known_nodes,
            findings,
            code="backtrack_missing_from_node",
            message="backtrack from_node is missing",
            allow_empty=False,
        )
        validate_known_node_ref(
            to_node,
            known_nodes,
            findings,
            code="backtrack_missing_to_node",
            message="backtrack to_node is missing",
            allow_empty=False,
        )
        state = clean_string(event.get("event_state"))
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id)
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="backtrack_missing_evidence_ref",
            message_template="backtrack references missing evidence_id {ref_id}",
            node_id=from_node,
        )
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
