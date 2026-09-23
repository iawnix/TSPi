"""Canonical ResearchMap ChangeSet operation catalog.

The ResearchKernel is the source of mutation semantics. This module only
describes the small public envelope used by callers that need to inspect the
available operation fields; it intentionally has no second compiler or state
model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ContractError


@dataclass(frozen=True)
class OperationContract:
    required: frozenset[str]
    optional: frozenset[str] = frozenset()


INPUT_OPERATION_CONTRACTS: dict[str, OperationContract] = {
    "create_phase": OperationContract(
        required=frozenset({"type", "id", "title"}),
        optional=frozenset({"objective", "created_at", "metadata"}),
    ),
    "create_claim": OperationContract(
        required=frozenset({"type", "id", "statement"}),
        optional=frozenset({"status", "predictions", "falsifiers", "created_at", "metadata"}),
    ),
    "create_node": OperationContract(
        required=frozenset({"type", "id", "title", "objective"}),
        optional=frozenset({"phase_id", "claim_ids", "dependency_ids", "created_at", "metadata"}),
    ),
    "create_finding": OperationContract(
        required=frozenset({"type", "id", "node_id", "statement", "kind"}),
        optional=frozenset({
            "claim_ids", "source_refs", "value", "datatype", "unit", "provenance",
            "status", "severity", "resolution", "created_at", "metadata",
        }),
    ),
    "create_gate": OperationContract(
        required=frozenset({"type", "id", "scope", "target_id"}),
        optional=frozenset({"criteria", "created_at", "metadata"}),
    ),
    "set_continuation": OperationContract(
        required=frozenset({"type", "id", "scope", "target_id", "action"}),
        optional=frozenset({"status", "reason", "request_id", "created_at", "metadata"}),
    ),
    "resolve_continuation": OperationContract(
        required=frozenset({"type", "id", "status"}),
        optional=frozenset({"reason", "request_id"}),
    ),
    "evaluate_gate": OperationContract(
        required=frozenset({"type", "gate_id", "verdict"}),
        optional=frozenset({"message", "evidence_refs", "created_at"}),
    ),
    "set_node_state": OperationContract(
        required=frozenset({"type", "node_id", "state"}),
        optional=frozenset({"outcome", "summary"}),
    ),
    "set_claim_status": OperationContract(
        required=frozenset({"type", "claim_id", "status"}),
    ),
    "relate_claims": OperationContract(
        required=frozenset({"type", "source_id", "target_id", "relation"}),
    ),
    "set_focus": OperationContract(
        required=frozenset({"type", "claim_ids", "node_ids"}),
    ),
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


def input_operation_names() -> frozenset[str]:
    """Return the canonical ResearchMap operation names."""

    return frozenset(INPUT_OPERATION_CONTRACTS)


def operation_catalog(operation: str | None = None) -> dict[str, object]:
    """Return the same lightweight field catalog exposed by the Kernel."""

    names = input_operation_names()
    if operation is not None and operation not in names:
        raise ContractError(f"unsupported ResearchMap operation: {operation}")
    selected = sorted(names if operation is None else {operation})
    return {
        "schema_version": "research-operation-catalog/1",
        "selected_operation": operation,
        "operations": [
            {
                "type": name,
                "required_fields": sorted(INPUT_OPERATION_CONTRACTS[name].required),
                "optional_fields": sorted(INPUT_OPERATION_CONTRACTS[name].optional),
            }
            for name in selected
        ],
    }


__all__ = [
    "INPUT_OPERATION_CONTRACTS",
    "OperationContract",
    "input_operation_names",
    "operation_catalog",
    "validate_input_operation_keys",
]
