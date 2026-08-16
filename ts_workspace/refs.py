"""Logical identifier and artifact binding validation for v4."""

from __future__ import annotations

import re
from typing import Any


DECISION_ID_PATTERN = r"^dec_[1-9][0-9]*$"
DECISION_ID = re.compile(DECISION_ID_PATTERN)
CLAIM_ID_PATTERN = r"^claim_[1-9][0-9]*$"
CLAIM_ID = re.compile(CLAIM_ID_PATTERN)
ACT_ID_PATTERN = r"^act_[1-9][0-9]*$"
ACT_ID = re.compile(ACT_ID_PATTERN)
ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{24}$")


class WorkspaceRefError(ValueError):
    """Raised when a v4 logical reference is invalid."""


def decision_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Decision ID."""

    if not isinstance(value, str) or DECISION_ID.fullmatch(value) is None:
        raise WorkspaceRefError(f"invalid Decision ID: {value!r}")
    return int(value.removeprefix("dec_"))


def next_decision_ordinal(values: Any) -> int:
    """Allocate after the highest Decision ordinal recorded in workspace history."""

    ordinals = [decision_ordinal(value) for value in values]
    return max(ordinals, default=0) + 1


def claim_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Claim ID."""

    if not isinstance(value, str) or CLAIM_ID.fullmatch(value) is None:
        raise WorkspaceRefError(f"invalid Claim ID: {value!r}")
    return int(value.removeprefix("claim_"))


def next_claim_ordinal(values: Any) -> int:
    """Allocate after the highest existing Claim ordinal without reusing history."""

    ordinals = [claim_ordinal(value) for value in values]
    return max(ordinals, default=0) + 1


def claim_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Claim IDs numerically while remaining defensive."""

    try:
        return (claim_ordinal(value), "")
    except WorkspaceRefError:
        return (2**63 - 1, str(value))


def act_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Act ID."""

    if not isinstance(value, str) or ACT_ID.fullmatch(value) is None:
        raise WorkspaceRefError(f"invalid ResearchAct ID: {value!r}")
    return int(value.removeprefix("act_"))


def next_act_ordinal(values: Any) -> int:
    """Allocate after the highest existing ordinal without reusing history."""

    ordinals = [act_ordinal(value) for value in values]
    return max(ordinals, default=0) + 1


def act_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Act IDs numerically while remaining defensive."""

    try:
        return (act_ordinal(value), "")
    except WorkspaceRefError:
        return (2**63 - 1, str(value))


def validate_artifact_bindings(record: dict[str, Any]) -> None:
    refs = record.get("artifact_refs")
    provenance = record.get("provenance")
    digests = provenance.get("source_digests") if isinstance(provenance, dict) else None
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ARTIFACT_ID.fullmatch(ref) for ref in refs):
        raise WorkspaceRefError("Observation artifact_refs must contain logical artifact IDs")
    if not isinstance(digests, dict) or set(digests) != set(refs):
        raise WorkspaceRefError("Observation source_digests must cover artifact_refs exactly")
