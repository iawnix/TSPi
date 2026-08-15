"""Deterministic construction of canonical workspace decisions."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from .decision_validator_v3 import ContractError, validate_decision
from .reader_v3 import report_workspace
from .schema_validation import SchemaValidationError, validate_contract


FACT_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "gaussian_tsfreq/1": {
        "stationary_point": ("stationary_point_found",),
        "route_match": ("route_consistent",),
    },
    "mode_assignment/1": {
        "mode_matches_declared_reaction_coordinate": (
            "reaction_coordinate_match",
            "imaginary_mode_matches",
        ),
    },
}


def draft_decision(
    root: str | Path,
    request: dict[str, Any],
    *,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """Build a canonical decision while keeping technical IDs kernel-owned."""

    if not isinstance(request, dict):
        raise ContractError("decision draft request must be an object")
    _reject_kernel_owned_ids(request.get("payload"))
    try:
        validate_contract("decision_draft_input.schema.json", request)
    except SchemaValidationError as exc:
        raise ContractError(str(exc)) from exc

    allocated_decision_id = decision_id or f"dec_{uuid4()}"
    payload = deepcopy(request["payload"])
    allocated_refs = _normalize_update_payload(payload, allocated_decision_id)
    report = report_workspace(root)
    decision = {
        "schema_version": "ts-decision/3",
        "decision_id": allocated_decision_id,
        "action": request["action"],
        "rationale": request["rationale"],
        "basis_refs": list(request["basis_refs"]),
        "report_ref": {
            "report_id": report["report_id"],
            "workspace_root": report["workspace_root"],
        },
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }
    validate_decision(decision)
    return {
        "decision": decision,
        "workspace_revision": report["workspace_revision"],
        "allocated_refs": allocated_refs,
    }


def _reject_kernel_owned_ids(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for item in _items(payload.get("append_evidence")):
        if isinstance(item, dict) and "evidence_id" in item:
            raise ContractError("append_evidence.evidence_id is kernel-owned; omit it")
    for item in _items(payload.get("evaluate_gate")):
        if isinstance(item, dict) and "gate_result_id" in item:
            raise ContractError("evaluate_gate.gate_result_id is kernel-owned; omit it")


def _normalize_update_payload(payload: dict[str, Any], decision_id: str) -> dict[str, list[str]]:
    allocated = {"evidence": [], "gate_results": []}
    for index, item in enumerate(_items(payload.get("append_evidence"))):
        evidence_id = _allocated_id("ev", decision_id, "append_evidence", index)
        item["evidence_id"] = evidence_id
        item["facts"] = _project_facts(str(item.get("kind") or ""), item.get("facts"))
        allocated["evidence"].append(evidence_id)
    for index, item in enumerate(_items(payload.get("evaluate_gate"))):
        gate_result_id = _allocated_id("gr", decision_id, "evaluate_gate", index)
        item["gate_result_id"] = gate_result_id
        allocated["gate_results"].append(gate_result_id)
    return allocated


def _project_facts(kind: str, value: Any) -> dict[str, Any]:
    facts = deepcopy(value)
    if not isinstance(facts, dict):
        return facts
    for canonical, aliases in FACT_ALIASES.get(kind, {}).items():
        candidates = [(name, facts[name]) for name in (canonical, *aliases) if name in facts]
        if not candidates:
            continue
        reference_name, reference_value = candidates[0]
        for name, candidate in candidates[1:]:
            if not _json_equal(reference_value, candidate):
                raise ContractError(
                    f"conflicting facts for {canonical}: {reference_name} and {name}"
                )
        facts.setdefault(canonical, deepcopy(reference_value))
    return facts


def _allocated_id(prefix: str, decision_id: str, field: str, index: int) -> str:
    material = f"ts-workspace-draft/1\0{decision_id}\0{field}\0{index}".encode("utf-8")
    return f"{prefix}_{hashlib.sha256(material).hexdigest()[:24]}"


def _json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right,
        sort_keys=True,
        separators=(",", ":"),
    )


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
