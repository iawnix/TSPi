"""Deterministic, evidence-role-free gate evaluation for workspace v3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import now_iso
from .model_v3 import GATE_RESULT_SCHEMA, GATE_TYPES


POLICY_PATH = Path(__file__).resolve().parent / "contracts" / "gate_policies.json"
MISSING = object()


class GateEvaluationError(ValueError):
    """Raised when a gate request violates the deterministic policy contract."""


def load_gate_policies() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if value.get("schema_version") != "ts-gate-policies/1":
        raise GateEvaluationError("invalid gate policy schema_version")
    return value


def evaluate_gate(
    *,
    gate_result_id: str,
    node_id: str,
    gate: str,
    evidence_records: list[dict[str, Any]],
    evidence_refs: list[str],
    target_ref: str | None = None,
) -> dict[str, Any]:
    if gate not in GATE_TYPES:
        raise GateEvaluationError(f"unsupported gate: {gate}")
    policies = load_gate_policies()
    policy = policies["evaluators"].get(gate)
    if not isinstance(policy, dict):
        raise GateEvaluationError(f"gate has no evaluator policy: {gate}")
    if not evidence_refs or len(set(evidence_refs)) != len(evidence_refs):
        raise GateEvaluationError("gate evaluation requires unique evidence_refs")

    by_id = {
        str(item.get("evidence_id")): item
        for item in evidence_records
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    }
    missing_refs = [ref for ref in evidence_refs if ref not in by_id]
    if missing_refs:
        raise GateEvaluationError(f"gate evidence refs are unavailable: {', '.join(missing_refs)}")
    selected = [by_id[ref] for ref in evidence_refs]
    allowed_tiers = set(policy.get("allowed_tiers", []))
    disallowed = [
        str(item.get("evidence_id"))
        for item in selected
        if item.get("evidence_tier") not in allowed_tiers
    ]
    if disallowed:
        raise GateEvaluationError(
            f"gate {gate} does not accept the selected evidence tier: {', '.join(disallowed)}"
        )

    diagnostics: list[str] = []
    missing: list[str] = []
    for requirement in policy.get("requirements", []):
        path = str(requirement.get("path") or "")
        observed = [_fact_at(item.get("facts"), path) for item in selected]
        present = [value for value in observed if value is not MISSING]
        if not present:
            missing.append(path)
            continue
        if not all(_matches(value, requirement) for value in present):
            diagnostics.append(f"requirement failed: {path} {requirement.get('op')}")

    if diagnostics:
        verdict = "fail"
    elif missing:
        verdict = "inconclusive"
        diagnostics.extend(f"required fact missing: {path}" for path in missing)
    else:
        verdict = "pass"

    return {
        "schema_version": GATE_RESULT_SCHEMA,
        "gate_result_id": gate_result_id,
        "node_id": node_id,
        "gate": gate,
        "policy": str(policy["policy"]),
        "verdict": verdict,
        "target_ref": target_ref,
        "evidence_refs": list(evidence_refs),
        "evaluator": "deterministic-fact-policy/1",
        "diagnostics": diagnostics,
        "evaluated_at": now_iso(),
    }


def validate_audit_gate_results(
    policy_name: str,
    gate_results: list[dict[str, Any]],
    gate_result_refs: list[str],
    *,
    target_ref: str,
) -> dict[str, dict[str, Any]]:
    policies = load_gate_policies()
    policy = policies.get("audit_policies", {}).get(policy_name)
    if not isinstance(policy, dict):
        raise GateEvaluationError(f"unsupported audit policy: {policy_name}")
    by_id = {
        str(item.get("gate_result_id")): item
        for item in gate_results
        if isinstance(item, dict) and isinstance(item.get("gate_result_id"), str)
    }
    selected: dict[str, dict[str, Any]] = {}
    for ref in gate_result_refs:
        result = by_id.get(ref)
        if result is None:
            raise GateEvaluationError(f"audit gate result is unavailable: {ref}")
        if result.get("target_ref") not in {None, target_ref}:
            raise GateEvaluationError(f"audit gate result target does not match {target_ref}: {ref}")
        if result.get("verdict") != "pass":
            raise GateEvaluationError(f"audit gate result did not pass: {ref}")
        gate = str(result.get("gate") or "")
        if gate in selected:
            raise GateEvaluationError(f"audit contains duplicate gate result type: {gate}")
        selected[gate] = result
    missing = sorted(set(policy.get("required_gates", [])) - set(selected))
    if missing:
        raise GateEvaluationError(f"audit missing required gates: {', '.join(missing)}")
    allowed = set(policy.get("required_gates", [])) | set(policy.get("optional_gates", []))
    unexpected = sorted(set(selected) - allowed)
    if unexpected:
        raise GateEvaluationError(f"audit contains gates outside policy: {', '.join(unexpected)}")
    return selected


def _fact_at(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _matches(value: Any, requirement: dict[str, Any]) -> bool:
    operation = requirement.get("op")
    expected = requirement.get("value")
    if operation == "equals":
        return value == expected
    if operation == "one_of":
        return isinstance(expected, list) and value in expected
    if operation == "empty":
        return value in (None, "", [], {})
    if operation == "nonempty":
        return value not in (None, "", [], {})
    raise GateEvaluationError(f"unsupported gate requirement operation: {operation}")
