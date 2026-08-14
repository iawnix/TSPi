"""Small, authoritative vocabulary for the strategy-neutral workspace model."""

from __future__ import annotations

from typing import Any


DECISION_SCHEMA = "ts-decision/3"
NODE_SCHEMA = "ts-node/3"
EVIDENCE_SCHEMA = "ts-evidence/2"
GATE_RESULT_SCHEMA = "ts-gate-result/1"

NODE_STATES = frozenset({"open", "closed", "stopped"})
NODE_OUTCOMES = frozenset({"completed", "inconclusive", "blocked", "stopped"})
CLAIM_VERDICTS = frozenset({"supported", "contradicted", "inconclusive"})
AUDIT_VERDICTS = frozenset({"accepted", "not_accepted", "inconclusive"})
GATE_VERDICTS = frozenset({"pass", "fail", "inconclusive"})
GATE_TYPES = frozenset({
    "tsfreq",
    "mode_assignment",
    "connectivity",
    "stereochemistry",
    "endpoint_identity",
    "intermediate_identity",
    "electronic_structure",
    "state_character",
    "shared_basin_consistency",
    "method_robustness",
    "thermochemistry",
    "pathway_audit",
})


def node_state(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    state = value.get("state")
    return state if isinstance(state, str) and state in NODE_STATES else None


def node_tags(value: Any) -> frozenset[str]:
    if not isinstance(value, dict) or not isinstance(value.get("tags"), list):
        return frozenset()
    return frozenset(str(item) for item in value["tags"] if isinstance(item, str) and item)
