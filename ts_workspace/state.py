"""Canonical v4 state document names and initial values."""

from __future__ import annotations

from typing import Any


WORKSPACE_FILE = "workspace.json"
RESEARCH_STATE_FILE = "research_state.json"
CLAIMS_FILE = "claims.json"
CLAIM_RELATIONS_FILE = "claim_relations.json"
RESEARCH_ACTS_FILE = "research_acts.json"
OBSERVATIONS_FILE = "observations.json"
VALIDATION_SPECS_FILE = "validation_specs.json"
VALIDATION_RESULTS_FILE = "validation_results.json"
FINDINGS_FILE = "findings.json"

STATE_FILES = (
    WORKSPACE_FILE,
    RESEARCH_STATE_FILE,
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    RESEARCH_ACTS_FILE,
    OBSERVATIONS_FILE,
    VALIDATION_SPECS_FILE,
    VALIDATION_RESULTS_FILE,
    FINDINGS_FILE,
)
REQUIRED_FILES = frozenset((*STATE_FILES, "decision_log.jsonl", "transaction_log.jsonl"))
REQUIRED_DIRS = frozenset({"acts", "acceptances", "decisions"})
OPTIONAL_DIRS = frozenset({"inputs", "reports", "scratch", "operations"})
LEGACY_MARKERS = frozenset({"evidence_registry.json", "gate_results.json", "nodes"})


def initial_documents(workspace_id: str, created_at: str) -> dict[str, dict[str, Any]]:
    return {
        WORKSPACE_FILE: {
            "schema_version": "ts-workspace/4",
            "workspace_id": workspace_id,
            "kernel_protocol": "ts-research-kernel/4",
            "created_at": created_at,
        },
        RESEARCH_STATE_FILE: {
            "schema_version": "ts-research-state/4",
            "focus_claim_refs": [],
            "focus_act_refs": [],
            "acceptance_refs": [],
            "created_at": created_at,
        },
        CLAIMS_FILE: {"schema_version": "ts-claim-registry/2", "claims": []},
        CLAIM_RELATIONS_FILE: {"schema_version": "ts-claim-relation-registry/1", "relations": []},
        RESEARCH_ACTS_FILE: {"schema_version": "ts-research-act-registry/3", "acts": []},
        OBSERVATIONS_FILE: {"schema_version": "ts-observation-registry/1", "observations": []},
        VALIDATION_SPECS_FILE: {"schema_version": "ts-validation-spec-registry/1", "specs": []},
        VALIDATION_RESULTS_FILE: {"schema_version": "ts-validation-result-registry/1", "results": []},
        FINDINGS_FILE: {"schema_version": "ts-finding-registry/1", "findings": []},
    }


STATE_SCHEMAS = {
    WORKSPACE_FILE: "workspace.schema.json",
    RESEARCH_STATE_FILE: "research_state.schema.json",
    CLAIMS_FILE: "claim_registry.schema.json",
    CLAIM_RELATIONS_FILE: "claim_relation_registry.schema.json",
    RESEARCH_ACTS_FILE: "research_act_registry.schema.json",
    OBSERVATIONS_FILE: "observation_registry.schema.json",
    VALIDATION_SPECS_FILE: "validation_spec_registry.schema.json",
    VALIDATION_RESULTS_FILE: "validation_result_registry.schema.json",
    FINDINGS_FILE: "finding_registry.schema.json",
}
