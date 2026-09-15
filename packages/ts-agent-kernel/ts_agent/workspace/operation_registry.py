"""Single source for the public ``ts_change`` operation shapes.

The registry deliberately describes only the input envelope (required and
optional keys).  Value semantics, cross-record references, and deterministic
record construction remain in :mod:`ts_agent.workspace.decision`.
Keeping the key contract here lets the compiler, tests, and documentation
refer to one maintained vocabulary instead of silently drifting copies.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ContractError


@dataclass(frozen=True)
class OperationContract:
    required: frozenset[str]
    optional: frozenset[str] = frozenset()
    public_name: str | None = None
    variant: str = "default"
    template_name: str | None = None

    def exposed_name(self, registry_name: str) -> str:
        return self.public_name or registry_name

    def template_ref(self, registry_name: str) -> str:
        """Return the packaged operation snippet for this exact variant."""

        filename = self.template_name or f"{self.exposed_name(registry_name)}.json"
        return f"skills/tspi-orchestration/assets/templates/decision/{filename}"


INPUT_OPERATION_CONTRACTS: dict[str, OperationContract] = {
    "create_phase": OperationContract(
        required=frozenset({"op", "local_ref", "title", "objective"}),
    ),
    "create_claim": OperationContract(
        required=frozenset({
            "op", "local_ref", "question", "claimType", "statement", "scope",
            "uncertainty", "predictions", "falsifiers",
        }),
        optional=frozenset({"createdByNode", "assumptions", "tags"}),
    ),
    "relate_claims": OperationContract(
        required=frozenset({
            "op", "local_ref", "sourceClaimRef", "targetClaimRef",
            "relationType", "rationale",
        }),
    ),
    "start_node": OperationContract(
        required=frozenset({
            "op", "local_ref", "phaseRef", "title", "objective", "deliverable",
        }),
        optional=frozenset({"dependencyRefs", "primaryClaimRef", "claimRefs", "tags"}),
    ),
    "record_observation": OperationContract(
        required=frozenset({
            "op", "local_ref", "nodeRef", "conceptId", "subjectRef", "value",
            "datatype", "summary", "provenance",
        }),
        optional=frozenset({"unit", "qualifiers", "artifacts"}),
        variant="direct",
    ),
    # Candidate observations are parser-owned and intentionally have a smaller
    # caller envelope.  ``candidate`` is selected as a variant before the
    # normal observation contract is checked.
    "record_observation_candidate": OperationContract(
        required=frozenset({
            "op", "local_ref", "nodeRef", "candidate", "conceptId", "subjectRef",
            "summary",
        }),
        optional=frozenset({"qualifiers"}),
        public_name="record_observation",
        variant="candidate",
        template_name="record_observation_candidate.json",
    ),
    "record_finding": OperationContract(
        required=frozenset({"op", "local_ref", "findingType", "severity", "statement"}),
        optional=frozenset({"claimRefs", "nodeRefs", "basisObservationRefs"}),
    ),
    "freeze_proof_spec": OperationContract(
        required=frozenset({
            "op", "local_ref", "nodeRef", "targetClaimRef", "dimension",
        }),
        optional=frozenset({"template", "definition", "title"}),
    ),
    "evaluate_proof": OperationContract(
        required=frozenset({"op", "local_ref", "nodeRef", "proofRef", "observationRefs"}),
    ),
    "accept_claim": OperationContract(
        required=frozenset({"op", "local_ref", "claimRef", "profile", "summary"}),
    ),
    "update_claim": OperationContract(
        required=frozenset({"op", "claimRef", "status", "summary"}),
        optional=frozenset({"observationRefs", "validationResultRefs"}),
    ),
    "complete_node": OperationContract(
        required=frozenset({"op", "nodeRef", "outcome", "summary"}),
        optional=frozenset({"openQuestions"}),
    ),
    "resolve_finding": OperationContract(
        required=frozenset({"op", "findingRef", "status", "summary"}),
        optional=frozenset({"basisObservationRefs"}),
    ),
    "set_focus": OperationContract(
        required=frozenset({"op", "claimRefs", "nodeRefs"}),
    ),
}


def validate_input_operation_keys(
    value: dict[str, object],
    *,
    operation: str | None = None,
) -> None:
    """Reject missing or unknown keys using the registered operation shape."""

    if not isinstance(value, dict):
        raise ContractError("change operation must be an object")
    registry_name = operation or str(value.get("op") or "")
    contract = INPUT_OPERATION_CONTRACTS.get(registry_name)
    if contract is None:
        raise ContractError(f"unsupported change operation: {registry_name}")
    expected_public_name = contract.exposed_name(registry_name)
    if value.get("op") != expected_public_name:
        raise ContractError(
            f"change operation selector {operation!r} does not match value op {value.get('op')!r}"
        )
    name = contract.exposed_name(registry_name)
    missing = sorted(contract.required - set(value))
    unknown = sorted(set(value) - contract.required - contract.optional)
    if missing:
        raise ContractError(f"{name} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{name} contains unsupported fields: {', '.join(unknown)}")


def input_operation_names() -> frozenset[str]:
    """Return only callable operation names (excluding internal variants)."""

    return frozenset(
        contract.exposed_name(name)
        for name, contract in INPUT_OPERATION_CONTRACTS.items()
    )


def operation_catalog(operation: str | None = None) -> dict[str, object]:
    """Return an on-demand public field catalog without inflating tool schemas."""

    public_names = input_operation_names()
    if operation is not None and operation not in public_names:
        raise ContractError(f"unsupported change operation: {operation}")
    selected = sorted(public_names if operation is None else {operation})
    rows = []
    for public_name in selected:
        variants = []
        for registry_name, contract in INPUT_OPERATION_CONTRACTS.items():
            if contract.exposed_name(registry_name) != public_name:
                continue
            variants.append({
                "variant": contract.variant,
                "template_ref": contract.template_ref(registry_name),
                "required_fields": sorted(contract.required),
                "optional_fields": sorted(contract.optional),
            })
        rows.append({
            "op": public_name,
            # The default snippet remains the stable operation-level entry;
            # each variant below points at its own exact snippet.
            "template_ref": _primary_template_ref(public_name),
            "variants": variants,
            **({"value_constraints": {"severity": ["blocking", "warning", "informational"]}} if public_name == "record_finding" else {}),
            **({"value_constraints": {"direct_provenance": {"required": ["producer"], "optional": ["producerVersion"]},
                "datatype": ["boolean", "integer", "number", "string", "string_array", "number_array", "object", "json"],
                "artifact_binding": {"required": ["artifactId"], "optional": ["sha256"]},
                "candidate": "Use returned artifactId/candidateId; omit direct value/datatype/provenance fields."}} if public_name == "record_observation" else {}),
        })
    return {
        "schema_version": "ts-change-operation-catalog/1",
        "selected_operation": operation,
        "operations": rows,
    }


def _primary_template_ref(public_name: str) -> str:
    """Select the operation-level snippet while allowing named variants."""

    matches = [
        (registry_name, contract)
        for registry_name, contract in INPUT_OPERATION_CONTRACTS.items()
        if contract.exposed_name(registry_name) == public_name
    ]
    if not matches:
        raise ContractError(f"unsupported change operation: {public_name}")
    registry_name, contract = next(
        ((name, item) for name, item in matches if item.variant == "default"),
        matches[0],
    )
    return contract.template_ref(registry_name)
