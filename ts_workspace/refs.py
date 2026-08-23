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
CALCULATION_ID_PATTERN = r"^calc_[1-9][0-9]*$"
CALCULATION_ID = re.compile(CALCULATION_ID_PATTERN)
SUBAGENT_RUN_ID_PATTERN = r"^sub_[1-9][0-9]*$"
SUBAGENT_RUN_ID = re.compile(SUBAGENT_RUN_ID_PATTERN)
ACTIVITY_ID_PATTERN = r"^op_[1-9][0-9]*$"
ACTIVITY_ID = re.compile(ACTIVITY_ID_PATTERN)
CLAIM_RELATION_ID_PATTERN = r"^rel_[1-9][0-9]*$"
CLAIM_RELATION_ID = re.compile(CLAIM_RELATION_ID_PATTERN)
OBSERVATION_ID_PATTERN = r"^obs_[1-9][0-9]*$"
OBSERVATION_ID = re.compile(OBSERVATION_ID_PATTERN)
FINDING_ID_PATTERN = r"^fnd_[1-9][0-9]*$"
FINDING_ID = re.compile(FINDING_ID_PATTERN)
VALIDATION_SPEC_ID_PATTERN = r"^gsp_[1-9][0-9]*$"
VALIDATION_SPEC_ID = re.compile(VALIDATION_SPEC_ID_PATTERN)
VALIDATION_RESULT_ID_PATTERN = r"^val_[1-9][0-9]*$"
VALIDATION_RESULT_ID = re.compile(VALIDATION_RESULT_ID_PATTERN)
ACCEPTANCE_ID_PATTERN = r"^acc_[1-9][0-9]*$"
ACCEPTANCE_ID = re.compile(ACCEPTANCE_ID_PATTERN)
ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{24}$")


class WorkspaceRefError(ValueError):
    """Raised when a v4 logical reference is invalid."""


def decision_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Decision ID."""

    return _ordinal(value, pattern=DECISION_ID, prefix="dec_", label="Decision")


def next_decision_ordinal(values: Any) -> int:
    """Allocate after the highest Decision ordinal recorded in workspace history."""

    return _next_ordinal(values, decision_ordinal)


def claim_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Claim ID."""

    return _ordinal(value, pattern=CLAIM_ID, prefix="claim_", label="Claim")


def next_claim_ordinal(values: Any) -> int:
    """Allocate after the highest existing Claim ordinal without reusing history."""

    return _next_ordinal(values, claim_ordinal)


def claim_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Claim IDs numerically while remaining defensive."""

    try:
        return (claim_ordinal(value), "")
    except WorkspaceRefError:
        return (2**63 - 1, str(value))


def act_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one canonical Act ID."""

    return _ordinal(value, pattern=ACT_ID, prefix="act_", label="ResearchAct")


def next_act_ordinal(values: Any) -> int:
    """Allocate after the highest existing ordinal without reusing history."""

    return _next_ordinal(values, act_ordinal)


def act_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Act IDs numerically while remaining defensive."""

    try:
        return (act_ordinal(value), "")
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


def observation_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one Observation ID."""

    return _ordinal(value, pattern=OBSERVATION_ID, prefix="obs_", label="Observation")


def next_observation_ordinal(values: Any) -> int:
    """Allocate after the highest existing Observation ordinal."""

    return _next_ordinal(values, observation_ordinal)


def observation_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Observation IDs numerically while remaining defensive."""

    return _sort_key(value, observation_ordinal)


def finding_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one Finding ID."""

    return _ordinal(value, pattern=FINDING_ID, prefix="fnd_", label="Finding")


def next_finding_ordinal(values: Any) -> int:
    """Allocate after the highest existing Finding ordinal."""

    return _next_ordinal(values, finding_ordinal)


def finding_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Finding IDs numerically while remaining defensive."""

    return _sort_key(value, finding_ordinal)


def validation_spec_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one GateSpec ID."""

    return _ordinal(value, pattern=VALIDATION_SPEC_ID, prefix="gsp_", label="GateSpec")


def next_validation_spec_ordinal(values: Any) -> int:
    """Allocate after the highest existing GateSpec ordinal."""

    return _next_ordinal(values, validation_spec_ordinal)


def validation_spec_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical GateSpec IDs numerically while remaining defensive."""

    return _sort_key(value, validation_spec_ordinal)


def validation_result_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one ValidationResult ID."""

    return _ordinal(value, pattern=VALIDATION_RESULT_ID, prefix="val_", label="ValidationResult")


def next_validation_result_ordinal(values: Any) -> int:
    """Allocate after the highest existing ValidationResult ordinal."""

    return _next_ordinal(values, validation_result_ordinal)


def validation_result_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical ValidationResult IDs numerically while remaining defensive."""

    return _sort_key(value, validation_result_ordinal)


def acceptance_ordinal(value: str) -> int:
    """Return the workspace-local ordinal encoded by one Acceptance ID."""

    return _ordinal(value, pattern=ACCEPTANCE_ID, prefix="acc_", label="Acceptance")


def next_acceptance_ordinal(values: Any) -> int:
    """Allocate after the highest existing Acceptance ordinal."""

    return _next_ordinal(values, acceptance_ordinal)


def acceptance_sort_key(value: str) -> tuple[int, str]:
    """Sort canonical Acceptance IDs numerically while remaining defensive."""

    return _sort_key(value, acceptance_ordinal)


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


def validate_artifact_bindings(record: dict[str, Any]) -> None:
    refs = record.get("artifact_refs")
    provenance = record.get("provenance")
    digests = provenance.get("source_digests") if isinstance(provenance, dict) else None
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ARTIFACT_ID.fullmatch(ref) for ref in refs):
        raise WorkspaceRefError("Observation artifact_refs must contain logical artifact IDs")
    if not isinstance(digests, dict) or set(digests) != set(refs):
        raise WorkspaceRefError("Observation source_digests must cover artifact_refs exactly")
