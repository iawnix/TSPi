"""Node close finalizer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..evidence_gates import (
    STRICT_PATHWAY_ACCEPTED,
    STEREOCHEMICAL_GATE_ROLE,
    accepted_gate_evidence,
    hypothesis_requires_stereochemical_gate,
    mechanism_reflection_gate_evidence,
    mechanism_reflection_required_roles,
    strict_pathway_decision,
    validate_mechanism_reflection_gate,
    validate_stereochemical_connectivity_gate,
    validate_strict_connectivity_gate,
)
from ..io import read_json
from ..state import HYPOTHESES_FILE, RESEARCH_STATE_FILE


def validate_v2_audit_gates(root: Path, node: dict[str, Any], closure: dict[str, Any], evidence_refs: list[str]) -> None:
    """Validate scientific gates before closing a v2 audit node."""

    if node.get("node_type") != "audit":
        return
    audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
    status = audit.get("status")
    if status in {"accepted", "not_accepted"} and closure.get("program", {}).get("outcome") == "failure":
        raise ValueError("an audit with program.outcome=failure cannot be accepted or not_accepted")

    scope = node.get("audit_scope")
    if scope == "pathway":
        registry = read_json(root / "evidence_registry.json")
        strict_decision = strict_pathway_decision(registry.get("evidence", []), evidence_refs)
        if strict_decision is None:
            raise ValueError(
                "audit_scope=pathway requires pathway_audit_summary evidence with quality.strict_pathway_decision"
            )
        expected_status = "accepted" if strict_decision == STRICT_PATHWAY_ACCEPTED else "not_accepted"
        if status != expected_status:
            raise ValueError(
                "closure.audit.status must match pathway_audit_summary quality.strict_pathway_decision"
            )
        if strict_decision == STRICT_PATHWAY_ACCEPTED:
            hypothesis = _hypothesis_for_node(root, node)
            hypothesis_id = _node_hypothesis_id(node)
            _validate_declared_mechanism_reflection_gates(
                registry.get("evidence", []),
                evidence_refs,
                hypothesis,
                hypothesis_id,
                include_shared_basin=True,
            )
        return

    if status == "accepted" and scope in {"transition_state", "elementary_step"}:
        _validated_acceptance_evidence(root, node, evidence_refs)


def compute_v2_close_changes(
    root: Path,
    node: dict[str, Any],
    research_state: dict[str, Any],
) -> dict[Path, Any]:
    """Return accepted-TS artifact writes for a closed v2 audit."""

    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
    if (
        node.get("node_type") != "audit"
        or node.get("audit_scope") not in {"transition_state", "elementary_step"}
        or audit.get("status") != "accepted"
    ):
        return {}

    gate_evidence, mechanism_roles = _validated_acceptance_evidence(root, node, node.get("evidence_refs", []))
    required_gates = ["tsfreq_gate", "connectivity_gate"]
    evidence_refs = [
        gate_evidence["tsfreq_gate"]["evidence_id"],
        gate_evidence["connectivity_gate"]["evidence_id"],
    ]
    if STEREOCHEMICAL_GATE_ROLE in gate_evidence:
        required_gates.append(STEREOCHEMICAL_GATE_ROLE)
        evidence_refs.append(gate_evidence[STEREOCHEMICAL_GATE_ROLE]["evidence_id"])
    for role in sorted(mechanism_roles):
        required_gates.append(role)
        evidence_refs.append(gate_evidence[role]["evidence_id"])

    accepted_id = f"accepted_ts_{node['node_id']}"
    artifact = {
        "schema_version": "ts-accepted/2",
        "accepted_id": accepted_id,
        "node_id": node["node_id"],
        "node_type": "audit",
        "audit_scope": node["audit_scope"],
        "hypothesis_ref": node.get("hypothesis_ref"),
        "required_gates": required_gates,
        "evidence_refs": evidence_refs,
    }
    artifact_path = root / "accepted" / f"{accepted_id}.json"
    artifact_ref = str(artifact_path.relative_to(root))
    if artifact_ref not in research_state.setdefault("accepted_ts_refs", []):
        research_state["accepted_ts_refs"].append(artifact_ref)
    return {
        artifact_path: artifact,
        root / RESEARCH_STATE_FILE: research_state,
    }


def _find_hypothesis(model: dict[str, Any], hypothesis_id: str | None) -> dict[str, Any]:
    for hypothesis in model.setdefault("hypotheses", []):
        if isinstance(hypothesis, dict) and hypothesis.get("hypothesis_id") == hypothesis_id:
            return hypothesis
    raise ValueError(f"unknown hypothesis_id: {hypothesis_id}")


def _hypothesis_for_node(root: Path, node: dict[str, Any]) -> dict[str, Any]:
    model = read_json(root / HYPOTHESES_FILE)
    return _find_hypothesis(model, _node_hypothesis_id(node))


def _node_hypothesis_id(node: dict[str, Any]) -> str | None:
    hypothesis_ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    return str(hypothesis_id) if hypothesis_id else None


def _validated_acceptance_evidence(
    root: Path,
    node: dict[str, Any],
    evidence_refs: list[str],
) -> tuple[dict[str, Any], set[str]]:
    registry = read_json(root / "evidence_registry.json")
    evidence_records = registry.get("evidence", [])
    hypothesis = _hypothesis_for_node(root, node)
    hypothesis_id = _node_hypothesis_id(node)
    require_stereo = hypothesis_requires_stereochemical_gate(hypothesis)
    gate_evidence = accepted_gate_evidence(
        evidence_records,
        evidence_refs,
        require_stereochemical_gate=require_stereo,
    )
    if gate_evidence.get("__hypothesis_id") != hypothesis_id:
        raise ValueError("accepted audit gate evidence must match node.hypothesis_ref")
    validate_strict_connectivity_gate(gate_evidence["connectivity_gate"])
    if require_stereo:
        validate_stereochemical_connectivity_gate(gate_evidence[STEREOCHEMICAL_GATE_ROLE])

    mechanism_roles = mechanism_reflection_required_roles(hypothesis, include_shared_basin=False)
    mechanism_evidence = mechanism_reflection_gate_evidence(
        evidence_records,
        evidence_refs,
        mechanism_roles,
    )
    if mechanism_roles and mechanism_evidence.get("__hypothesis_id") != hypothesis_id:
        raise ValueError("mechanism reflection gate evidence must match node.hypothesis_ref")
    for role in sorted(mechanism_roles):
        validate_mechanism_reflection_gate(mechanism_evidence[role], role)
        gate_evidence[role] = mechanism_evidence[role]
    return gate_evidence, mechanism_roles


def _validate_declared_mechanism_reflection_gates(
    evidence_records: list[Any],
    evidence_refs: list[str],
    hypothesis: dict[str, Any] | None,
    hypothesis_id: str | None,
    *,
    include_shared_basin: bool,
) -> None:
    roles = mechanism_reflection_required_roles(hypothesis, include_shared_basin=include_shared_basin)
    gate_evidence = mechanism_reflection_gate_evidence(evidence_records, evidence_refs, roles)
    if roles and gate_evidence.get("__hypothesis_id") != hypothesis_id:
        raise ValueError("mechanism reflection gate evidence must match node.hypothesis_ref")
    for role in sorted(roles):
        validate_mechanism_reflection_gate(gate_evidence[role], role)
