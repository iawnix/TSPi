"""Logical identifier and artifact binding validation."""

from __future__ import annotations

import re
from typing import Any


CLAIM_ID_PATTERN = r"^claim_[1-9][0-9]*$"
CLAIM_ID = re.compile(CLAIM_ID_PATTERN)
PHASE_ID_PATTERN = r"^phase_[1-9][0-9]*$"
PHASE_ID = re.compile(PHASE_ID_PATTERN)
NODE_ID_PATTERN = r"^node_[1-9][0-9]*$"
NODE_ID = re.compile(NODE_ID_PATTERN)
CALCULATION_ID_PATTERN = r"^calc_[1-9][0-9]*$"
CALCULATION_ID = re.compile(CALCULATION_ID_PATTERN)
SUBAGENT_RUN_ID_PATTERN = r"^sub_[1-9][0-9]*$"
SUBAGENT_RUN_ID = re.compile(SUBAGENT_RUN_ID_PATTERN)
ACTIVITY_ID_PATTERN = r"^op_[1-9][0-9]*$"
ACTIVITY_ID = re.compile(ACTIVITY_ID_PATTERN)
CLAIM_RELATION_ID_PATTERN = r"^rel_[1-9][0-9]*$"
CLAIM_RELATION_ID = re.compile(CLAIM_RELATION_ID_PATTERN)
FINDING_ID_PATTERN = r"^fnd_[1-9][0-9]*$"
FINDING_ID = re.compile(FINDING_ID_PATTERN)
GATE_ID_PATTERN = r"^gate_[1-9][0-9]*$"
GATE_ID = re.compile(GATE_ID_PATTERN)
ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{24}$")
MONITOR_ID = re.compile(r"^mon_[0-9a-f]{24}$")
MONITOR_EVENT_ID = re.compile(r"^evt_[0-9a-f]{32}$")


class WorkspaceRefError(ValueError):
    """Raised when a logical workspace reference is invalid."""


def claim_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Claim ID."""

    return _ordinal(value, pattern=CLAIM_ID, prefix="claim_", label="Claim")


def next_claim_ordinal(values: Any) -> int:
    """Allocate after the highest existing Claim ordinal without reusing history."""

    return _next_ordinal(values, claim_ordinal)


def phase_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one ResearchPhase ID."""

    return _ordinal(value, pattern=PHASE_ID, prefix="phase_", label="ResearchPhase")


def next_phase_ordinal(values: Any) -> int:
    """Allocate after the highest existing ResearchPhase ordinal."""

    return _next_ordinal(values, phase_ordinal)


def phase_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical ResearchPhase IDs numerically while remaining defensive."""

    return _sort_key(value, phase_ordinal)


def claim_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Claim IDs numerically while remaining defensive."""

    try:
        return (claim_ordinal(value), "")
    except WorkspaceRefError:
        return (2**63 - 1, str(value))


def node_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Node ID."""

    return _ordinal(value, pattern=NODE_ID, prefix="node_", label="ResearchNode")


def next_node_ordinal(values: Any) -> int:
    """Allocate after the highest existing ordinal without reusing history."""

    return _next_ordinal(values, node_ordinal)


def node_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Node IDs numerically while remaining defensive."""

    try:
        return (node_ordinal(value), "")
    except WorkspaceRefError:
        return (2**63 - 1, str(value))


def claim_relation_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one ClaimRelation ID."""

    return _ordinal(value, pattern=CLAIM_RELATION_ID, prefix="rel_", label="ClaimRelation")


def next_claim_relation_ordinal(values: Any) -> int:
    """Allocate after the highest existing ClaimRelation ordinal."""

    return _next_ordinal(values, claim_relation_ordinal)


def claim_relation_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical ClaimRelation IDs numerically while remaining defensive."""

    return _sort_key(value, claim_relation_ordinal)


def finding_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one Finding ID."""

    return _ordinal(value, pattern=FINDING_ID, prefix="fnd_", label="Finding")


def next_finding_ordinal(values: Any) -> int:
    """Allocate after the highest existing Finding ordinal."""

    return _next_ordinal(values, finding_ordinal)


def finding_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Finding IDs numerically while remaining defensive."""

    return _sort_key(value, finding_ordinal)


def gate_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one Gate ID."""

    return _ordinal(value, pattern=GATE_ID, prefix="gate_", label="Gate")


def next_gate_ordinal(values: Any) -> int:
    return _next_ordinal(values, gate_ordinal)


def _ordinal(value: str, *, pattern: re.Pattern[str], prefix: str, label: str) -> int:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise WorkspaceRefError(f"invalid {label} ID: {value!r}")
    return int(value.removeprefix(prefix))


def _next_ordinal(values: Any, parser: Any) -> int:
    ordinals = [parser(value) for value in values]
    return max(ordinals, default=0) + 1


def _sort_key(value: str, parser: Any) -> tuple[int, str]:
    try:
        return (parser(value), "")
    except WorkspaceRefError:
        return (2**63 - 1, str(value))
