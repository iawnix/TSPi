"""Canonical research-node ontology and legacy phase mappings."""

from __future__ import annotations

from typing import Any


DECISION_SCHEMA = "ts-decision/2"
NODE_SCHEMA = "ts-node/2"

NODE_TYPES = {
    "intake",
    "mechanism",
    "candidate_search",
    "validation",
    "audit",
}

MECHANISM_ACTIONS = {"propose", "compare", "revise", "evaluate"}
CANDIDATE_KINDS = {"transition_state", "endpoint_conformer", "intermediate", "crossing_point"}
VALIDATION_SCOPES = {
    "tsfreq",
    "connectivity",
    "electronic_structure",
    "state_character",
    "thermochemistry",
    "method_robustness",
    "geometry_identity",
}
AUDIT_SCOPES = {"transition_state", "elementary_step", "pathway", "study"}
ATTEMPT_KINDS = {"primary", "recalculation"}
HYPOTHESIS_STATUSES = {"supported", "unsupported", "ambiguous"}
PROGRAM_OUTCOMES = {"success", "failure", "not_run"}
AUDIT_STATUSES = {"accepted", "not_accepted", "ambiguous"}
INTAKE_STATUSES = {"ready", "needs_input"}

LEGACY_PHASE_TO_NODE_TYPE = {
    "preflight": "intake",
    "endpoint": "intake",
    "hypothesis_generation": "mechanism",
    "rp_conformer_generation": "candidate_search",
    "candidate_generation": "candidate_search",
    "tsfreq_validation": "validation",
    "connectivity_validation": "validation",
    "accepted_audit": "audit",
    "pathway_audit": "audit",
}

LEGACY_PHASE_TO_SCOPE = {
    "preflight": None,
    "endpoint": None,
    "hypothesis_generation": "propose",
    "rp_conformer_generation": "endpoint_conformer",
    "candidate_generation": "transition_state",
    "tsfreq_validation": "tsfreq",
    "connectivity_validation": "connectivity",
    "accepted_audit": "transition_state",
    "pathway_audit": "pathway",
}


def node_type_of(value: Any) -> str | None:
    """Return the canonical node type for a v2 or legacy node-like object."""

    if not isinstance(value, dict):
        return None
    node_type = value.get("node_type")
    if isinstance(node_type, str) and node_type in NODE_TYPES:
        return node_type
    phase = value.get("phase")
    return LEGACY_PHASE_TO_NODE_TYPE.get(phase) if isinstance(phase, str) else None


def node_scope_of(value: Any) -> str | None:
    """Return the primary operation scope for a v2 or legacy node-like object."""

    if not isinstance(value, dict):
        return None
    node_type = node_type_of(value)
    field = {
        "mechanism": "mechanism_action",
        "candidate_search": "candidate_kind",
        "validation": "validation_scope",
        "audit": "audit_scope",
    }.get(node_type)
    if field and isinstance(value.get(field), str):
        return value[field]
    phase = value.get("phase")
    return LEGACY_PHASE_TO_SCOPE.get(phase) if isinstance(phase, str) else None


def is_v2(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schema_version") in {DECISION_SCHEMA, NODE_SCHEMA}
