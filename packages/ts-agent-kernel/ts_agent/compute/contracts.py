"""JSON contracts for calculation intents and operational results.

The dependency-neutral implementation lives in :mod:`ts_agent.calculation_contracts`;
this module preserves the historical Compute-specific exception type and API.
"""

from __future__ import annotations

from typing import Any

from ts_agent.calculation_contracts import (
    CalculationContractError,
    CONTRACT_DIR,
    validate_calculation_contract,
    validate_calculation_result_binding as _validate_result_binding,
)


class ComputeContractError(ValueError):
    """Raised when a compute request crosses the operational contract."""


def validate_compute_contract(schema_name: str, instance: Any) -> None:
    try:
        validate_calculation_contract(schema_name, instance)
    except CalculationContractError as exc:
        raise ComputeContractError(str(exc)) from exc


def validate_calculation_result_binding(
    intent: dict[str, Any],
    result: dict[str, Any],
    *,
    label: str = "calculation result",
) -> None:
    """Validate one result and bind it to its immutable calculation intent."""

    try:
        _validate_result_binding(intent, result, label=label)
    except CalculationContractError as exc:
        raise ComputeContractError(str(exc)) from exc
