"""Canonical ResearchMap ChangeSet operation catalog.

The Research State filesystem boundary is the source of mutation semantics. This module only
describes the small public envelope used by callers that need to inspect the
available operation fields; it intentionally has no second compiler or state
model.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .errors import ContractError

GATE_CONTRACT = json.loads((Path(__file__).parent / 'contracts/gates.json').read_text())


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
        optional=frozenset({"status", "predictions", "falsifiers", "source_refs", "constraints", "created_at", "metadata"}),
    ),
    "assess_claim": OperationContract(
        required=frozenset({"type", "id", "claim_id", "verdict", "reason"}),
        optional=frozenset({"evidence_refs", "actor", "metadata", "created_at"}),
    ),
    "revise_claim": OperationContract(
        required=frozenset({"type", "source_claim_id", "target_claim_id", "statement", "reason"}),
        optional=frozenset({"revision_id", "relation", "predictions", "falsifiers", "actor", "metadata", "created_at"}),
    ),
    "create_node": OperationContract(
        required=frozenset({"type", "id", "title", "objective"}),
        optional=frozenset({"phase_id", "claim_ids", "dependency_ids", "completion_exemption", "created_at", "metadata"}),
    ),
    "create_finding": OperationContract(
        required=frozenset({"type", "id", "node_id", "statement", "kind"}),
        optional=frozenset({
            "claim_ids", "source_refs", "value", "datatype", "unit", "provenance",
            "status", "severity", "resolution", "created_at", "metadata",
        }),
    ),
    "create_gate": OperationContract(
        required=frozenset({"type", "id", "scope", "target_id", "criteria"}),
        optional=frozenset({"created_at", "metadata"}),
    ),
    "set_lifecycle_action": OperationContract(
        required=frozenset({"type", "id", "scope", "target_id", "action"}),
        optional=frozenset({"status", "reason", "request_id", "created_at", "metadata"}),
    ),
    "resolve_lifecycle_action": OperationContract(
        required=frozenset({"type", "id", "status"}),
        optional=frozenset({"reason", "request_id"}),
    ),
    "revise_gate": OperationContract(required=frozenset({"type", "gate_id", "criteria", "reason"})),
    "evaluate_gate": OperationContract(
        required=frozenset({"type", "gate_id", "verdict", "assessments"}),
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
    if name == "set_node_state":
        state = value.get("state")
        has_outcome = "outcome" in value and value.get("outcome") is not None
        if state == "closed" and not has_outcome:
            raise ContractError("set_node_state closed requires outcome")
        if state != "closed" and has_outcome:
            raise ContractError("set_node_state outcome is only valid when state is closed")


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
                **({"nested_schema": {"criteria": GATE_CONTRACT["criterion"]}} if name in {"create_gate", "revise_gate"} else {}),
                **({"nested_schema": {"assessments": GATE_CONTRACT["assessment"]}} if name == "evaluate_gate" else {}),
                **({"example": GATE_CONTRACT["examples"][name]} if name in GATE_CONTRACT["examples"] else {}),
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
