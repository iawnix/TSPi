"""Candidate validation boundary owned by the active domain provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_compute.provider import ProviderUnavailable, resolve_compute_provider


class FindingCandidateError(ValueError):
    """The provider produced an invalid or stale finding candidate."""


def load_analysis_candidate(
    root: str | Path, artifact: dict[str, Any], node_id: str, candidate_id: str,
) -> dict[str, Any]:
    try:
        return resolve_compute_provider("chemical").validate_candidate(
            Path(root), artifact, node_id, candidate_id,
        )
    except FindingCandidateError:
        raise
    except ProviderUnavailable as exc:
        raise FindingCandidateError(str(exc)) from exc
    except Exception as exc:
        raise FindingCandidateError(f"analysis provider rejected candidate: {exc}") from exc


__all__ = ["FindingCandidateError", "load_analysis_candidate"]
