"""Canonical file names and initial documents for workspace v3."""

from __future__ import annotations


RESEARCH_STATE_FILE = "research_state.json"
EVIDENCE_FILE = "evidence_registry.json"
GATE_RESULTS_FILE = "gate_results.json"
CLAIMS_FILE = "claims.json"

REQUIRED_FILES = frozenset({
    RESEARCH_STATE_FILE,
    EVIDENCE_FILE,
    GATE_RESULTS_FILE,
    CLAIMS_FILE,
    "decision_log.jsonl",
    "transaction_log.jsonl",
})
REQUIRED_DIRS = frozenset({"nodes", "decisions"})
OPTIONAL_DIRS = frozenset({"accepted", "inputs", "reports", "scratch"})


def initial_research_state() -> dict:
    return {
        "schema_version": "ts-research-state/3",
        "nodes": [],
        "edges": [],
        "open_nodes": [],
        "branch_events": [],
        "accepted_refs": [],
        "provenance": [],
    }


def initial_evidence_registry() -> dict:
    return {"schema_version": "ts-evidence-registry/2", "evidence": [], "events": []}


def initial_gate_registry() -> dict:
    return {"schema_version": "ts-gate-registry/1", "gate_results": []}


def initial_claim_registry() -> dict:
    return {"schema_version": "ts-claim-registry/1", "focus_claim_refs": [], "claims": []}
