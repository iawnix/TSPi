"""Candidate validation boundary owned by the active domain provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_compute.analysis import ANALYSIS_CAPABILITY_REGISTRY
from .candidates import FindingCandidateError


def load_analysis_candidate(
    root: str | Path, artifact: dict[str, Any], node_id: str, candidate_id: str,
) -> dict[str, Any]:
    try:
        for registration in ANALYSIS_CAPABILITY_REGISTRY.registrations():
            provider = registration.provider
            validator = getattr(provider, "validate_candidate", None)
            if callable(validator):
                return validator(Path(root), artifact, node_id, candidate_id)
        raise FindingCandidateError("analysis candidate provider unavailable")
    except FindingCandidateError:
        raise
    except Exception as exc:
        raise FindingCandidateError(f"analysis provider rejected candidate: {exc}") from exc


__all__ = ["FindingCandidateError", "load_analysis_candidate"]
