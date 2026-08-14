"""Revision identity for the v3 scientific state documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, sha256_json
from .state_v3 import CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE, RESEARCH_STATE_FILE


def workspace_revision(root: str | Path) -> str:
    root_path = Path(root)
    return workspace_revision_from_documents(
        read_json(root_path / RESEARCH_STATE_FILE),
        read_json(root_path / CLAIMS_FILE),
        read_json(root_path / EVIDENCE_FILE),
        read_json(root_path / GATE_RESULTS_FILE),
    )


def workspace_revision_from_documents(research: Any, claims: Any, evidence: Any, gates: Any) -> str:
    return sha256_json({"research": research, "claims": claims, "evidence": evidence, "gates": gates})


def report_id_for_revision(revision: str) -> str:
    return "rep_" + revision.split(":", 1)[-1][:16]
