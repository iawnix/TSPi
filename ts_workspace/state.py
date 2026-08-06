"""Canonical workspace state layout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import now_iso, read_json

RESEARCH_STATE_FILE = "research_state.json"
HYPOTHESES_FILE = "hypotheses.json"
EVIDENCE_FILE = "evidence_registry.json"

CORE_STATE_FILES = {RESEARCH_STATE_FILE, HYPOTHESES_FILE, EVIDENCE_FILE}


def initial_research_state(*, created_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "ts-research-state",
        "created_at": created_at or now_iso(),
        "hypothesis_contract_version": "strict",
        "accepted_ts_refs": [],
        "provenance": [],
        "nodes": [],
        "edges": [],
        "current_node": None,
        "branch_events": [],
    }


def initial_hypotheses() -> dict[str, Any]:
    return {
        "schema_version": "ts-hypotheses",
        "focus_hypothesis_id": None,
        "hypotheses": [],
        "accepted_facts": [],
        "refuted_hypotheses": [],
        "open_questions": [],
        "focus_pathway_id": None,
        "pathways": [],
        "audit_records": [],
    }


def read_research_state(root: str | Path) -> dict[str, Any]:
    return read_json(Path(root) / RESEARCH_STATE_FILE)


def read_hypotheses(root: str | Path) -> dict[str, Any]:
    return read_json(Path(root) / HYPOTHESES_FILE)
