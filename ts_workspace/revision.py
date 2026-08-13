"""Deterministic workspace revision and report identity helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, sha256_json
from .state import EVIDENCE_FILE, HYPOTHESES_FILE, RESEARCH_STATE_FILE


def workspace_revision(root: str | Path) -> str:
    root_path = Path(root)
    return workspace_revision_from_documents(
        read_json(root_path / RESEARCH_STATE_FILE),
        read_json(root_path / HYPOTHESES_FILE),
        read_json(root_path / EVIDENCE_FILE),
    )


def workspace_revision_from_documents(
    research_state: Any,
    hypotheses: Any,
    evidence: Any,
) -> str:
    return sha256_json(
        {
            "research_state": research_state,
            "hypotheses": hypotheses,
            "evidence": evidence,
        }
    )


def report_id_for_revision(revision: str) -> str:
    digest = revision.split(":", 1)[-1]
    return f"rep_{digest[:16]}"
