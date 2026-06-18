"""Pathway-model checks for ChemGate workspace validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.base.pathway_model import (
    PATHWAY_MODES,
    PATHWAY_STATUSES,
    STEP_STATUSES,
    derive_pathway_status,
)
from transition_state_workflow.config.state_contract import PATHWAY_MODEL_SCHEMA, derive_node_audit_view
from transition_state_workflow.gate.evidence import accepted_ts_missing_evidence_gates
from transition_state_workflow.util.path_utils import clean_string, relative_path_or_absolute

from .common import iter_object_records, register_unique_id, require_list_field, validate_known_node_ref
from .contracts import Finding
from .evidence import group_evidence_records_by_node


def validate_pathway_model(
    source: Path,
    model: dict[str, Any],
    node_json_by_id: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate optional pathway_model.json and node step references."""

    node_step_refs: dict[str, tuple[str, str]] = {}
    pathway_audit_refs: dict[str, str] = {}
    for node_id, node in node_json_by_id.items():
        pathway_id = clean_string(node.get("pathway_id"))
        step_id = clean_string(node.get("elementary_step_id"))
        audit = derive_node_audit_view(node)
        if clean_string(audit.get("claim_status")) == "accepted_pathway" or clean_string(node.get("phase")) == "pathway_audit":
            if pathway_id:
                pathway_audit_refs[node_id] = pathway_id
            elif step_id:
                node_step_refs[node_id] = (pathway_id, step_id)
            continue
        if pathway_id or step_id:
            node_step_refs[node_id] = (pathway_id, step_id)
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

    if clean_string(model.get("schema")) != PATHWAY_MODEL_SCHEMA:
        findings.append(Finding("error", "pathway_schema_invalid", f"pathway_model.json must declare schema={PATHWAY_MODEL_SCHEMA}", path="pathway_model.json"))
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
                node_audit = derive_node_audit_view(node)
                if clean_string(node_audit.get("claim_status")) != "accepted_ts":
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
        accepted_pathway_audit_node = clean_string(pathway.get("accepted_pathway_audit_node"))
        if accepted_pathway_audit_node:
            validate_known_node_ref(
                accepted_pathway_audit_node,
                known_nodes,
                findings,
                code="pathway_audit_node_missing",
                message="pathway accepted_pathway_audit_node is missing",
                path="pathway_model.json",
                node_id=accepted_pathway_audit_node,
                allow_empty=False,
            )
            audit_node = node_json_by_id.get(accepted_pathway_audit_node) or {}
            audit = derive_node_audit_view(audit_node)
            if audit_node and clean_string(audit.get("claim_status")) != "accepted_pathway":
                findings.append(
                    Finding(
                        "error",
                        "pathway_audit_node_not_accepted_pathway",
                        "pathway accepted_pathway_audit_node is not claim_status=accepted_pathway",
                        path="pathway_model.json",
                        node_id=accepted_pathway_audit_node,
                    )
                )
            if audit_node and clean_string(audit_node.get("pathway_id")) != pathway_id:
                findings.append(
                    Finding(
                        "error",
                        "pathway_audit_node_binding_conflict",
                        "pathway accepted_pathway_audit_node does not declare the same pathway_id",
                        path="pathway_model.json",
                        node_id=accepted_pathway_audit_node,
                    )
                )

    active_pathway = clean_string(model.get("active_pathway"))
    if active_pathway and active_pathway not in pathway_ids:
        findings.append(Finding("error", "active_pathway_missing", "active_pathway does not reference an existing pathway", path="pathway_model.json"))

    for node_id, pathway_id in pathway_audit_refs.items():
        if pathway_id not in pathway_ids:
            node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
            findings.append(
                Finding(
                    "error",
                    "pathway_audit_node_pathway_missing",
                    "pathway audit node references missing pathway",
                    path=node_path,
                    node_id=node_id,
                )
            )

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
        node_audit = derive_node_audit_view(node)
        if clean_string(node_audit.get("claim_status")) == "accepted_ts" and clean_string(step.get("accepted_ts_node")) != node_id:
            findings.append(
                Finding(
                    "error",
                    "accepted_node_not_bound_to_pathway_step",
                    "accepted_ts node declares a pathway step but pathway_model does not bind that step to this node",
                    path=node_path,
                    node_id=node_id,
                )
            )


__all__ = ["validate_pathway_model"]
