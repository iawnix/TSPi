"""Node-state checks for ChemGate workspace validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import (
    CLAIM_LEVEL_RANK,
    MAXIMUM_CLAIM_LEVEL_BY_CLAIM_STATUS,
    VALID_CLAIM_LEVELS,
    VALID_CLAIM_STATUSES,
    VALID_LIFECYCLE_STATES,
    VALID_NODE_DISPOSITIONS,
    VALID_OUTCOMES,
    VALID_RUN_STATES,
    VALID_WORKFLOW_PHASES,
    check_node_contract_violations,
    valid_outcomes_for_claim_status,
)
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, relative_path_or_absolute

from .contracts import Finding


def validate_nodes_contract(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    """Validate required node fields and forbid legacy node-level aliases."""

    for node_id, node_json in node_json_by_id.items():
        node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
        for code, message in check_node_contract_violations(node_id, node_json):
            findings.append(
                Finding("error", code, message, path=node_path, node_id=node_id)
            )


def validate_normalized_nodes(graph: dict[str, Any], findings: list[Finding]) -> None:
    """Validate normalized node state combinations and claim-level invariants."""

    for node in list_or_empty(graph.get("nodes")):
        if not isinstance(node, dict):
            continue
        node_id = clean_string(node.get("id"))
        lifecycle = clean_string(node.get("lifecycle_state"))
        run_state = clean_string(node.get("run_state"))
        claim = clean_string(node.get("claim_status"))
        outcome = clean_string(node.get("outcome"))
        claim_level = clean_string(node.get("claim_level"))
        outcome_code = node.get("outcome_code")
        if lifecycle not in VALID_LIFECYCLE_STATES:
            findings.append(Finding("error", "invalid_lifecycle_state", f"invalid lifecycle_state: {lifecycle}", node_id=node_id))
        if run_state not in VALID_RUN_STATES:
            findings.append(Finding("error", "invalid_run_state", f"invalid run_state: {run_state}", node_id=node_id))
        if claim not in VALID_CLAIM_STATUSES:
            findings.append(Finding("error", "invalid_claim_status", f"invalid claim_status: {claim}", node_id=node_id))
        if outcome not in VALID_OUTCOMES:
            findings.append(Finding("error", "invalid_outcome", f"invalid outcome: {outcome}", node_id=node_id))
        valid_outcomes = valid_outcomes_for_claim_status(claim)
        if valid_outcomes and outcome and outcome not in valid_outcomes:
            findings.append(
                Finding(
                    "error",
                    "claim_outcome_conflict",
                    f"outcome {outcome!r} is not valid for claim_status {claim!r}",
                    node_id=node_id,
                )
            )
        if claim_level not in VALID_CLAIM_LEVELS:
            findings.append(Finding("error", "invalid_claim_level", f"invalid claim_level: {claim_level}", node_id=node_id))
        max_level = MAXIMUM_CLAIM_LEVEL_BY_CLAIM_STATUS.get(claim)
        if max_level and CLAIM_LEVEL_RANK.get(claim_level, 99) > CLAIM_LEVEL_RANK[max_level]:
            findings.append(Finding("error", "claim_level_exceeds_claim_status", f"claim_level {claim_level} exceeds claim_status {claim}", node_id=node_id))
        if claim == "accepted_ts" and claim_level != "accepted_ts":
            findings.append(Finding("error", "accepted_claim_level_conflict", "accepted_ts requires claim_level=accepted_ts", node_id=node_id))
        if claim == "not_evaluated" and claim_level != "none":
            findings.append(Finding("error", "not_evaluated_claim_level_conflict", "not_evaluated requires claim_level=none", node_id=node_id))
        if outcome == "administrative_stop":
            if run_state != "stopped" or claim != "not_evaluated" or claim_level != "none":
                findings.append(Finding("error", "administrative_stop_state_conflict", "administrative_stop requires stopped/not_evaluated/none", node_id=node_id))
        if outcome != "none" and not outcome_code and outcome in {"chemical_failure", "numerical_failure", "wrong_mode", "wrong_endpoint", "administrative_stop", "parser_refused"}:
            findings.append(Finding("warning", "missing_outcome_code", f"outcome {outcome} should include outcome_code", node_id=node_id))
        if outcome == "chemical_failure" and claim == "not_evaluated":
            findings.append(Finding("error", "chemical_failure_not_evaluated", "chemical_failure cannot have claim_status=not_evaluated", node_id=node_id))

        phase = clean_string(node.get("phase"))
        disposition = clean_string(node.get("node_disposition"))
        if phase and phase not in VALID_WORKFLOW_PHASES:
            findings.append(Finding("error", "invalid_phase", f"invalid phase: {phase}", node_id=node_id))
        if disposition and disposition not in VALID_NODE_DISPOSITIONS:
            findings.append(Finding("error", "invalid_node_disposition", f"invalid node_disposition: {disposition}", node_id=node_id))
        if disposition == "Running" and run_state not in {"pending", "running", "parsing"}:
            findings.append(Finding("error", "running_disposition_state_conflict", "node_disposition=Running requires an active run_state", node_id=node_id))
        if disposition in {"Stopped", "Error", "Success"}:
            validate_closure_explanation(node_id, node, findings)


def validate_closure_explanation(
    node_id: str,
    node: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate the public closure explanation for a closed public node."""

    closure = node.get("closure_explanation")
    if not isinstance(closure, dict):
        findings.append(Finding("error", "missing_closure_explanation", "closed public nodes require closure_explanation", node_id=node_id))
        return
    for key in ("program", "mechanism"):
        block = closure.get(key)
        if not isinstance(block, dict):
            findings.append(Finding("error", f"missing_{key}_explanation", f"closure_explanation.{key} must be an object", node_id=node_id))
            continue
        if not clean_string(block.get("summary")):
            findings.append(Finding("error", f"missing_{key}_summary", f"closure_explanation.{key}.summary is required", node_id=node_id))
        facts = block.get("facts")
        if facts is not None and not isinstance(facts, list):
            findings.append(Finding("error", f"{key}_facts_not_list", f"closure_explanation.{key}.facts must be a list", node_id=node_id))
    if not clean_string(closure.get("implication")):
        findings.append(Finding("error", "missing_closure_implication", "closure_explanation.implication is required", node_id=node_id))


__all__ = [
    "validate_nodes_contract",
    "validate_normalized_nodes",
    "validate_closure_explanation",
]
