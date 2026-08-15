"""Core predicates over immutable semantic Observations."""

from __future__ import annotations

import math
from typing import Any

from ..observations import ObservationSelectionError, select_observations
from ..registry import PredicateRegistry


def register_core_predicates(registry: PredicateRegistry) -> None:
    registry.register("observation.exists", "1", _exists)
    registry.register("observation.equals", "1", _equals)
    registry.register("observation.empty", "1", _empty)
    registry.register("observation.nonempty", "1", _nonempty)
    registry.register("observation.one_of", "1", _one_of)
    registry.register("observation.number_range", "1", _number_range)
    registry.register("observation.count", "1", _count)


def _exists(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    selected = _select(parameters, observations)
    minimum = parameters.get("minimum", 1)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        return _error("minimum must be a positive integer")
    return _verdict(len(selected) >= minimum, selected, f"matched {len(selected)} observation(s)")


def _equals(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    selected = _select(parameters, observations)
    if not selected:
        return _inconclusive("no matching observation")
    expected = parameters.get("expected")
    mode = _mode(parameters)
    if mode is None:
        return _error("mode must be exactly_one, any, or all")
    if mode == "exactly_one" and len(selected) != 1:
        return _error(f"expected exactly one observation, found {len(selected)}", selected)
    values = [item.get("value") for item in selected]
    passed = any(value == expected for value in values) if mode == "any" else all(value == expected for value in values)
    return _verdict(passed, selected, f"observed={values!r}; expected={expected!r}")


def _empty(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    return _collection_state(parameters, observations, want_empty=True)


def _nonempty(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    return _collection_state(parameters, observations, want_empty=False)


def _one_of(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    allowed = parameters.get("allowed")
    if not isinstance(allowed, list) or not allowed:
        return _error("allowed must be a non-empty array")
    selected = _select(parameters, observations)
    if not selected:
        return _inconclusive("no matching observation")
    mode = _mode(parameters)
    if mode is None:
        return _error("mode must be exactly_one, any, or all")
    if mode == "exactly_one" and len(selected) != 1:
        return _error(f"expected exactly one observation, found {len(selected)}", selected)
    values = [item.get("value") for item in selected]
    passed = any(value in allowed for value in values) if mode == "any" else all(value in allowed for value in values)
    return _verdict(passed, selected, f"observed={values!r}; allowed={allowed!r}")


def _number_range(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    selected = _select(parameters, observations)
    if not selected:
        return _inconclusive("no matching observation")
    if len(selected) != 1:
        return _error(f"expected exactly one observation, found {len(selected)}", selected)
    value = selected[0].get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return _error("selected observation is not a finite number", selected)
    minimum = parameters.get("minimum")
    maximum = parameters.get("maximum")
    if minimum is None and maximum is None:
        return _error("number_range requires minimum or maximum", selected)
    if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, (int, float))):
        return _error("minimum must be numeric", selected)
    if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, (int, float))):
        return _error("maximum must be numeric", selected)
    passed = (minimum is None or value >= minimum) and (maximum is None or value <= maximum)
    return _verdict(passed, selected, f"observed={value!r}; range=[{minimum!r}, {maximum!r}]")


def _count(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    selected = _select(parameters, observations)
    minimum = parameters.get("minimum")
    maximum = parameters.get("maximum")
    if minimum is None and maximum is None:
        return _error("count requires minimum or maximum")
    for name, value in (("minimum", minimum), ("maximum", maximum)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return _error(f"{name} must be a non-negative integer")
    passed = (minimum is None or len(selected) >= minimum) and (maximum is None or len(selected) <= maximum)
    return _verdict(passed, selected, f"matched={len(selected)}; range=[{minimum!r}, {maximum!r}]")


def _collection_state(
    parameters: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    want_empty: bool,
) -> dict[str, Any]:
    selected = _select(parameters, observations)
    if not selected:
        return _inconclusive("no matching observation")
    if len(selected) != 1:
        return _error(f"expected exactly one observation, found {len(selected)}", selected)
    value = selected[0].get("value")
    if not isinstance(value, (list, dict, str)):
        return _error("selected observation is not a collection or string", selected)
    passed = (len(value) == 0) if want_empty else (len(value) > 0)
    return _verdict(passed, selected, f"observed length={len(value)}")


def _select(parameters: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        return select_observations(observations, parameters.get("selector"))
    except ObservationSelectionError as exc:
        raise ValueError(str(exc)) from exc


def _mode(parameters: dict[str, Any]) -> str | None:
    value = parameters.get("mode", "exactly_one")
    return value if value in {"exactly_one", "any", "all"} else None


def _verdict(
    passed: bool,
    selected: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:
    return {
        "verdict": "pass" if passed else "fail",
        "observation_refs": [str(item.get("observation_id")) for item in selected],
        "message": message,
    }


def _inconclusive(message: str) -> dict[str, Any]:
    return {"verdict": "inconclusive", "observation_refs": [], "message": message}


def _error(message: str, selected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "verdict": "error",
        "observation_refs": [str(item.get("observation_id")) for item in selected or []],
        "message": message,
    }
