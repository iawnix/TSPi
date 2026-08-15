"""Observation selection with exact semantic concepts and no alias guessing."""

from __future__ import annotations

from typing import Any


class ObservationSelectionError(ValueError):
    """Raised when a predicate selector is malformed."""


def select_observations(
    observations: list[dict[str, Any]],
    selector: dict[str, Any],
) -> list[dict[str, Any]]:
    allowed = {"concept_id", "subject_ref", "qualifiers"}
    if not isinstance(selector, dict) or set(selector) - allowed:
        raise ObservationSelectionError("observation selector contains unsupported fields")
    concept_id = selector.get("concept_id")
    if not isinstance(concept_id, str) or not concept_id:
        raise ObservationSelectionError("observation selector requires concept_id")
    subject_ref = selector.get("subject_ref")
    if subject_ref is not None and (not isinstance(subject_ref, str) or not subject_ref):
        raise ObservationSelectionError("selector subject_ref must be a non-empty string")
    qualifiers = selector.get("qualifiers", {})
    if not isinstance(qualifiers, dict):
        raise ObservationSelectionError("selector qualifiers must be an object")

    selected = []
    for observation in observations:
        if observation.get("concept_id") != concept_id:
            continue
        if subject_ref is not None and observation.get("subject_ref") != subject_ref:
            continue
        actual_qualifiers = observation.get("qualifiers", {})
        if not isinstance(actual_qualifiers, dict):
            continue
        if any(actual_qualifiers.get(key) != value for key, value in qualifiers.items()):
            continue
        selected.append(observation)
    return sorted(selected, key=lambda value: str(value.get("observation_id") or ""))
