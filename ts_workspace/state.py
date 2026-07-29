"""Canonical workspace state layout and legacy-state conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import now_iso, read_json

RESEARCH_STATE_FILE = "research_state.json"
HYPOTHESES_FILE = "hypotheses.json"
EVIDENCE_FILE = "evidence_registry.json"

CORE_STATE_FILES = {RESEARCH_STATE_FILE, HYPOTHESES_FILE, EVIDENCE_FILE}
LEGACY_STATE_FILES = {
    "manifest.json",
    "tree.json",
    "mechanism_model.json",
    "pathway_model.json",
    "knowledge_base.md",
}


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
    }


def read_research_state(root: str | Path) -> dict[str, Any]:
    return read_json(Path(root) / RESEARCH_STATE_FILE)


def read_hypotheses(root: str | Path) -> dict[str, Any]:
    return read_json(Path(root) / HYPOTHESES_FILE)


def state_layout(root: str | Path) -> str:
    root_path = Path(root)
    core_count = sum((root_path / name).exists() for name in CORE_STATE_FILES)
    legacy_count = sum((root_path / name).exists() for name in LEGACY_STATE_FILES)
    if core_count == len(CORE_STATE_FILES):
        return "current"
    has_current_models = any(
        (root_path / name).exists()
        for name in (RESEARCH_STATE_FILE, HYPOTHESES_FILE)
    )
    if not has_current_models and (root_path / EVIDENCE_FILE).exists() and legacy_count == len(LEGACY_STATE_FILES):
        return "legacy"
    if core_count or legacy_count:
        return "incomplete"
    return "missing"


def convert_legacy_state(root: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build current state objects from a complete legacy workspace without writing."""

    root_path = Path(root)
    if state_layout(root_path) != "legacy":
        raise ValueError("legacy conversion requires a complete legacy state layout")

    manifest = read_json(root_path / "manifest.json")
    tree = read_json(root_path / "tree.json")
    mechanism = read_json(root_path / "mechanism_model.json")
    pathway = read_json(root_path / "pathway_model.json")

    research_state = {
        "schema_version": "ts-research-state",
        "created_at": manifest.get("created_at") or now_iso(),
        "hypothesis_contract_version": manifest.get("hypothesis_contract_version", "strict"),
        "accepted_ts_refs": list(manifest.get("accepted_ts_refs", [])),
        "provenance": list(manifest.get("provenance", [])),
        "nodes": list(tree.get("nodes", [])),
        "edges": list(tree.get("edges", [])),
        "current_node": tree.get("current_node"),
        "branch_events": list(tree.get("branch_events", [])),
    }
    hypotheses = {
        "schema_version": "ts-hypotheses",
        "focus_hypothesis_id": mechanism.get("focus_hypothesis_id"),
        "hypotheses": list(mechanism.get("hypotheses", [])),
        "accepted_facts": list(mechanism.get("accepted_facts", [])),
        "refuted_hypotheses": list(mechanism.get("refuted_hypotheses", [])),
        "open_questions": list(mechanism.get("open_questions", [])),
        "focus_pathway_id": pathway.get("focus_pathway_id"),
        "pathways": list(pathway.get("pathways", [])),
    }
    return research_state, hypotheses
