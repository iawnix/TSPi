"""Canonical workspace state document names and initial values."""

from __future__ import annotations

from typing import Any


WORKSPACE_FILE = "workspace.json"
RESEARCH_STATE_FILE = "research_state.json"
RESEARCH_PHASES_FILE = "phases.json"
CLAIMS_FILE = "claims.json"
CLAIM_RELATIONS_FILE = "claim_relations.json"
RESEARCH_NODES_FILE = "research_nodes.json"
OBSERVATIONS_FILE = "observations.json"
PROOF_SPECS_FILE = "proof_specs.json"
VALIDATION_RESULTS_FILE = "validation_results.json"
FINDINGS_FILE = "findings.json"
GATE_SPECS_FILE = "gate_specs.json"
GATE_RESULTS_FILE = "gate_results.json"

STATE_FILES = (
    WORKSPACE_FILE,
    RESEARCH_STATE_FILE,
    RESEARCH_PHASES_FILE,
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    RESEARCH_NODES_FILE,
    OBSERVATIONS_FILE,
    PROOF_SPECS_FILE,
    VALIDATION_RESULTS_FILE,
    FINDINGS_FILE,
)
# Gate registries are an additive protocol layer.  They are deliberately not
# required for protocol-6 workspaces; the first explicit gate mutation creates
# them and readers treat their absence as an empty registry.
OPTIONAL_STATE_FILES = (GATE_SPECS_FILE, GATE_RESULTS_FILE)
REQUIRED_FILES = frozenset((*STATE_FILES, "decision_log.jsonl", "transaction_log.jsonl"))
REQUIRED_DIRS = frozenset({"nodes", "acceptances", "decisions"})
OPTIONAL_DIRS = frozenset({"inputs", "reports", "scratch", "operations"})
UNSUPPORTED_MARKERS = frozenset({
    "acts",
    "evidence_registry.json",
    "research_acts.json",
})


def state_document_names(root: Any | None = None) -> tuple[str, ...]:
    """Return required state files plus present additive registries."""

    names = list(STATE_FILES)
    if root is not None:
        for name in OPTIONAL_STATE_FILES:
            path = root / name
            if path.exists():
                names.append(name)
    return tuple(names)


def document_state_names(documents: dict[str, Any]) -> tuple[str, ...]:
    """Return required state files plus optional registries in a document map."""

    return tuple((*STATE_FILES, *(name for name in OPTIONAL_STATE_FILES if name in documents)))


def initial_documents(workspace_id: str, created_at: str) -> dict[str, dict[str, Any]]:
    return {
        WORKSPACE_FILE: {
            "schema_version": "ts-workspace/6",
            "workspace_id": workspace_id,
            "kernel_protocol": "ts-research-kernel/6",
            "created_at": created_at,
        },
        RESEARCH_STATE_FILE: {
            "schema_version": "ts-research-state/6",
            "focus_claim_refs": [],
            "focus_node_refs": [],
            "acceptance_refs": [],
            "created_at": created_at,
        },
        RESEARCH_PHASES_FILE: {"schema_version": "ts-research-phase-registry/1", "phases": []},
        CLAIMS_FILE: {"schema_version": "ts-claim-registry/5", "claims": []},
        CLAIM_RELATIONS_FILE: {"schema_version": "ts-claim-relation-registry/1", "relations": []},
        RESEARCH_NODES_FILE: {"schema_version": "ts-research-node-registry/2", "nodes": []},
        OBSERVATIONS_FILE: {"schema_version": "ts-observation-registry/2", "observations": []},
        PROOF_SPECS_FILE: {"schema_version": "ts-proof-spec-registry/1", "proofs": []},
        VALIDATION_RESULTS_FILE: {"schema_version": "ts-validation-result-registry/3", "results": []},
        FINDINGS_FILE: {"schema_version": "ts-finding-registry/2", "findings": []},
    }


STATE_SCHEMAS = {
    WORKSPACE_FILE: "workspace.schema.json",
    RESEARCH_STATE_FILE: "research_state.schema.json",
    RESEARCH_PHASES_FILE: "research_phase_registry.schema.json",
    CLAIMS_FILE: "claim_registry.schema.json",
    CLAIM_RELATIONS_FILE: "claim_relation_registry.schema.json",
    RESEARCH_NODES_FILE: "research_node_registry.schema.json",
    OBSERVATIONS_FILE: "observation_registry.schema.json",
    PROOF_SPECS_FILE: "proof_spec_registry.schema.json",
    VALIDATION_RESULTS_FILE: "validation_result_registry.schema.json",
    FINDINGS_FILE: "finding_registry.schema.json",
}
