"""Logical identifier and artifact binding validation for v4."""

from __future__ import annotations

import re
from typing import Any


ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{24}$")


class WorkspaceRefError(ValueError):
    """Raised when a v4 logical reference is invalid."""


def validate_artifact_bindings(record: dict[str, Any]) -> None:
    refs = record.get("artifact_refs")
    provenance = record.get("provenance")
    digests = provenance.get("source_digests") if isinstance(provenance, dict) else None
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ARTIFACT_ID.fullmatch(ref) for ref in refs):
        raise WorkspaceRefError("Observation artifact_refs must contain logical artifact IDs")
    if not isinstance(digests, dict) or set(digests) != set(refs):
        raise WorkspaceRefError("Observation source_digests must cover artifact_refs exactly")
