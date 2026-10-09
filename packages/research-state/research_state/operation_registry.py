"""Canonical ResearchMap ChangeSet operation catalog.

Public tools, operation discovery and write validation share operations.json.
The Research State filesystem boundary owns reference checks and mutation
semantics; this module does not maintain a second state model.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path

from jsonschema import Draft7Validator

from .errors import ContractError

CONTRACT_ROOT = Path(__file__).parent / "contracts"
GATE_CONTRACT = json.loads((CONTRACT_ROOT / "gates.json").read_text())
OPERATION_CONTRACT = json.loads((CONTRACT_ROOT / "operations.json").read_text())


def _resolve_schema(value):
    """Inline only the two local contract sources; never resolve remote references."""
    if isinstance(value, list):
        return [_resolve_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if reference.startswith("#/$defs/"):
            return _resolve_schema(OPERATION_CONTRACT["$defs"][reference.removeprefix("#/$defs/")])
        if reference.startswith("gates.json#/"):
            return _resolve_schema(GATE_CONTRACT[reference.removeprefix("gates.json#/")])
        raise ValueError(f"unsupported ResearchMap contract reference: {reference}")
    return {key: _resolve_schema(item) for key, item in value.items()}


OPERATION_SCHEMAS = {
    name: _resolve_schema(schema)
    for name, schema in OPERATION_CONTRACT["operations"].items()
}
_OPERATION_VALIDATORS = {name: Draft7Validator(schema) for name, schema in OPERATION_SCHEMAS.items()}
_CHECKPOINT_VALIDATOR = Draft7Validator(_resolve_schema(OPERATION_CONTRACT["$defs"]["checkpoint_request"]))


def validate_checkpoint_request(value: dict[str, object]) -> None:
    error = next(_CHECKPOINT_VALIDATOR.iter_errors(value), None)
    if error is not None:
        path = ".".join(str(part) for part in error.absolute_path)
        raise ContractError(f"checkpoint_request.{path}: {error.message}")


@dataclass(frozen=True)
class OperationContract:
    required: frozenset[str]
    optional: frozenset[str] = frozenset()


INPUT_OPERATION_CONTRACTS: dict[str, OperationContract] = {
    name: OperationContract(
        required=frozenset(schema["required"]),
        optional=frozenset(schema["properties"]) - frozenset(schema["required"]),
    )
    for name, schema in OPERATION_SCHEMAS.items()
}


def validate_input_operation_keys(
    value: dict[str, object],
    *,
    operation: str | None = None,
) -> None:
    """Reject missing or unknown fields for one canonical operation."""

    if not isinstance(value, dict):
        raise ContractError("ResearchMap operation must be an object")
    name = operation or str(value.get("type") or "")
    contract = INPUT_OPERATION_CONTRACTS.get(name)
    if contract is None:
        raise ContractError(f"unsupported ResearchMap operation: {name}")
    if value.get("type") != name:
        raise ContractError(f"operation type {value.get('type')!r} does not match {name!r}")
    missing = sorted(contract.required - set(value))
    unknown = sorted(set(value) - contract.required - contract.optional)
    if missing:
        raise ContractError(f"{name} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{name} contains unsupported fields: {', '.join(unknown)}")
    if name == "set_node_state":
        state = value.get("state")
        has_outcome = "outcome" in value and value.get("outcome") is not None
        if state == "closed" and not has_outcome:
            raise ContractError("set_node_state closed requires outcome")
        if state != "closed" and has_outcome:
            raise ContractError("set_node_state outcome is only valid when state is closed")


def validate_input_operation(value: dict[str, object]) -> None:
    """Validate the same complete public operation schema used by the Agent tools."""
    validate_input_operation_keys(value)
    name = str(value["type"])
    error = next(_OPERATION_VALIDATORS[name].iter_errors(value), None)
    if error is not None:
        path = ".".join(str(part) for part in error.absolute_path)
        location = f"{name}.{path}" if path else name
        raise ContractError(f"{location}: {error.message}")


def input_operation_names() -> frozenset[str]:
    """Return the canonical ResearchMap operation names."""

    return frozenset(INPUT_OPERATION_CONTRACTS)


def operation_catalog(operation: str | None = None) -> dict[str, object]:
    """Return the same lightweight field catalog exposed by the Research State."""

    names = input_operation_names()
    selected = sorted(names if operation is None else {
        name for name in names if name == operation or operation in INPUT_OPERATION_CONTRACTS[name].required
        or operation in INPUT_OPERATION_CONTRACTS[name].optional
    })
    return {
        "schema_version": "research-operation-catalog/1",
        "selected_operation": operation,
        "operations": [
            {
                "type": name,
                "required_fields": sorted(INPUT_OPERATION_CONTRACTS[name].required),
                "optional_fields": sorted(INPUT_OPERATION_CONTRACTS[name].optional),
                "schema": copy.deepcopy(OPERATION_SCHEMAS[name]),
                **({"nested_schema": {"criteria": GATE_CONTRACT["criterion"]}} if name in {"create_gate", "revise_gate"} else {}),
                **({"nested_schema": {"assessments": GATE_CONTRACT["assessment"]}} if name == "evaluate_gate" else {}),
                **({"example": GATE_CONTRACT["examples"][name]} if name in GATE_CONTRACT["examples"] else {}),
            }
            for name in selected
        ],
    }


__all__ = [
    "INPUT_OPERATION_CONTRACTS",
    "OPERATION_CONTRACT",
    "OPERATION_SCHEMAS",
    "OperationContract",
    "input_operation_names",
    "operation_catalog",
    "validate_input_operation_keys",
    "validate_input_operation",
]
