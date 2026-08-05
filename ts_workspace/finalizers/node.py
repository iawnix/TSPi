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
from ..evidence_lifecycle import evidence_lifecycle_view
from ..io import read_json
from ..state import HYPOTHESES_FILE, RESEARCH_STATE_FILE
from ..validators.decision import WORKSPACE_HYPOTHESIS_CREATION_PHASES

PATHWAY_STEP_STATUS_PHASES = {"connectivity_validation", "accepted_audit"}
IMPACT_SCOPES = {"solution_only", "prediction", "pathway_step", "hypothesis"}


def compute_close_changes(
    root: Path,
    node: dict[str, Any],
    decision: dict[str, Any],
    research_state: dict[str, Any],
) -> dict[Path, Any]:
    """Return proposed writes for closing a node without touching disk.

    Values are dicts (written as JSON) or strings (written as UTF-8 text).
    """
    closure = node["closure"]
    changes: dict[Path, Any] = {}
    hypotheses_path = root / HYPOTHESES_FILE
    hypotheses = read_json(hypotheses_path)
    _update_mechanism_model(root, hypotheses, node, closure)
    _update_pathway_model(hypotheses, node, closure)
    changes[hypotheses_path] = hypotheses
    _write_acceptance_artifact(root, node, closure, research_state, changes)
    return changes


def validate_accepted_audit_gates(root: Path, node: dict[str, Any], closure: dict[str, Any], evidence_refs: list[str]) -> None:
    if node["phase"] != "accepted_audit":
        return
    if closure["program_status"] != "completed" or closure["claim_verdict"] != "supported":
        return
    _validated_acceptance_evidence(root, node, evidence_refs)


def validate_pathway_audit_gates(root: Path, node: dict[str, Any], closure: dict[str, Any], evidence_refs: list[str]) -> None:
    if node["phase"] != "pathway_audit":
        return
    if closure["program_status"] != "completed" or closure["claim_verdict"] != "supported":
        return
    registry = read_json(root / "evidence_registry.json")
    strict_decision = strict_pathway_decision(registry.get("evidence", []), evidence_refs)
    if strict_decision is None:
        raise ValueError("pathway_audit requires pathway_audit_summary evidence with quality.strict_pathway_decision")
    if strict_decision != STRICT_PATHWAY_ACCEPTED:
        return
    hypothesis = _hypothesis_for_node(root, node)
    hypothesis_id = node.get("hypothesis_ref", {}).get("hypothesis_id") if isinstance(node.get("hypothesis_ref"), dict) else None
    _validate_declared_mechanism_reflection_gates(
        registry.get("evidence", []),
        evidence_refs,
        hypothesis,
        hypothesis_id,
        include_shared_basin=True,
    )


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
        "phase": "accepted_audit",
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


def _update_mechanism_model(root: Path, model: dict[str, Any], node: dict[str, Any], closure: dict[str, Any]) -> None:
    model.setdefault("focus_hypothesis_id", None)
    if _is_hypothesis_creation_node(node):
        _finalize_initial_hypothesis(root, model, node, closure)
        return
    if node.get("phase") == "endpoint":
        return

    mechanism = closure.get("mechanism", {}) if isinstance(closure.get("mechanism"), dict) else {}
    ref = mechanism.get("hypothesis_ref") if isinstance(mechanism.get("hypothesis_ref"), dict) else {}
    hypothesis_id = ref.get("hypothesis_id")
    hypothesis = _find_hypothesis(model, hypothesis_id)
    evidence_refs = sorted(set(hypothesis.get("evidence_refs", []) + node.get("evidence_refs", []) + mechanism.get("evidence_refs", [])))
    hypothesis["evidence_refs"] = evidence_refs
    impact_scope = _impact_scope(node, closure)
    if impact_scope in {"prediction", "pathway_step", "hypothesis"}:
        _append_prediction_status(hypothesis, node, closure, ref, mechanism)
    if impact_scope == "hypothesis":
        _apply_revision(model, hypothesis, node, closure, mechanism)

    if (
        impact_scope == "hypothesis"
        and node.get("phase") == "accepted_audit"
        and closure["program_status"] == "completed"
        and closure["claim_verdict"] == "supported"
    ):
        hypothesis["status"] = "supported"
        model.setdefault("accepted_facts", []).append(_mechanism_entry(node, closure, hypothesis_id, evidence_refs))
    elif closure["claim_verdict"] in {"inconclusive", "not_evaluated"}:
        model.setdefault("open_questions", []).append(_mechanism_entry(node, closure, hypothesis_id, evidence_refs))


def _finalize_initial_hypothesis(root: Path, model: dict[str, Any], node: dict[str, Any], closure: dict[str, Any]) -> None:
    if closure.get("program_status") != "completed":
        return
    initial = node.get("initial_mechanism_hypothesis")
    if not isinstance(initial, dict):
        raise ValueError("completed hypothesis-creation node missing initial_mechanism_hypothesis")

    mechanism = closure.get("mechanism", {}) if isinstance(closure.get("mechanism"), dict) else {}
    hypothesis = dict(initial)
    hypothesis_id = str(hypothesis.get("hypothesis_id") or _next_hypothesis_id(model))
    _ensure_unique_hypothesis_id(model, hypothesis_id)
    evidence_refs = sorted(set(hypothesis.get("evidence_refs", []) + node.get("evidence_refs", []) + mechanism.get("evidence_refs", [])))
    _require_initial_hypothesis_evidence(root, evidence_refs)
    hypothesis.update(
        {
            "hypothesis_id": hypothesis_id,
            "source_node": node["node_id"],
            "status": "active" if closure.get("claim_verdict") == "supported" else "refuted",
            "evidence_refs": evidence_refs,
        }
    )
    hypothesis.setdefault("parent_hypothesis_id", None)
    hypothesis.setdefault("prediction_status", [])
    if closure.get("claim_verdict") == "supported":
        model.setdefault("hypotheses", []).append(hypothesis)
        model["focus_hypothesis_id"] = hypothesis_id
    else:
        model.setdefault("refuted_hypotheses", []).append(_mechanism_entry(node, closure, hypothesis_id, evidence_refs))


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


def _next_hypothesis_id(model: dict[str, Any]) -> str:
    used: set[int] = set()
    for group in ("hypotheses", "refuted_hypotheses"):
        for item in model.get(group, []):
            if not isinstance(item, dict):
                continue
            raw = str(item.get("hypothesis_id") or "")
            if raw.startswith("hyp_") and raw[4:].isdigit():
                used.add(int(raw[4:]))
    number = 1
    while number in used:
        number += 1
    return f"hyp_{number:04d}"


def _ensure_unique_hypothesis_id(model: dict[str, Any], hypothesis_id: str) -> None:
    for group in ("hypotheses", "refuted_hypotheses"):
        for item in model.get(group, []):
            if isinstance(item, dict) and item.get("hypothesis_id") == hypothesis_id:
                raise ValueError(f"duplicate hypothesis_id: {hypothesis_id}")


def _require_initial_hypothesis_evidence(root: Path, evidence_refs: list[str]) -> None:
    registry = read_json(root / "evidence_registry.json")
    view = evidence_lifecycle_view(registry.get("evidence", []))
    resolved_refs = set(view.resolve_refs(evidence_refs))
    for entry in view.active_records:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") in resolved_refs and entry.get("role") == "initial_mechanism_hypothesis":
            return
    raise ValueError("initial hypothesis requires evidence role initial_mechanism_hypothesis")


def _append_prediction_status(
    hypothesis: dict[str, Any],
    node: dict[str, Any],
    closure: dict[str, Any],
    ref: dict[str, Any],
    mechanism: dict[str, Any],
) -> None:
    prediction_ids = ref.get("prediction_ids", [])
    if not prediction_ids:
        return
    hypothesis.setdefault("prediction_status", []).append(
        {
            "node_id": node["node_id"],
            "phase": node["phase"],
            "claim_verdict": closure["claim_verdict"],
            "prediction_ids": prediction_ids,
            "evidence_refs": sorted(set(node.get("evidence_refs", []) + mechanism.get("evidence_refs", []))),
        }
    )


def _apply_revision(
    model: dict[str, Any],
    hypothesis: dict[str, Any],
    node: dict[str, Any],
    closure: dict[str, Any],
    mechanism: dict[str, Any],
) -> None:
    revision = mechanism.get("revision")
    if not isinstance(revision, dict):
        return
    action = revision.get("action")
    if action == "refute_hypothesis":
        hypothesis["status"] = "refuted"
        model.setdefault("refuted_hypotheses", []).append(
            _mechanism_entry(node, closure, hypothesis.get("hypothesis_id"), hypothesis.get("evidence_refs", []))
        )
    elif action == "supersede_hypothesis":
        hypothesis["status"] = "superseded"
    elif action == "revise_hypothesis":
        hypothesis.setdefault("open_revisions", []).append(
            {
                "node_id": node["node_id"],
                "changed_variable": revision.get("changed_variable"),
                "prediction_ids": revision.get("prediction_ids", []),
            }
        )


def _mechanism_entry(
    node: dict[str, Any],
    closure: dict[str, Any],
    hypothesis_id: str | None,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "node_id": node["node_id"],
        "phase": node["phase"],
        "hypothesis_id": hypothesis_id,
        "hypothesis": node["hypothesis"],
        "program_status": closure["program_status"],
        "claim_verdict": closure["claim_verdict"],
        "mechanism_summary": closure.get("mechanism", {}).get("summary", ""),
        "evidence_refs": sorted(set(evidence_refs)),
    }


def _update_pathway_model(model: dict[str, Any], node: dict[str, Any], closure: dict[str, Any]) -> None:
    pathway_ref = node.get("pathway_ref")
    if not pathway_ref:
        return
    pathway_id = pathway_ref["pathway_id"]
    step_id = pathway_ref["step_id"]
    pathway = _ensure_pathway(model, pathway_id)
    step = _ensure_step(pathway, step_id)
    if node["phase"] == "pathway_audit":
        _record_pathway_audit(pathway, step, node, closure)
        return
    if node["phase"] not in PATHWAY_STEP_STATUS_PHASES:
        return
    if _impact_scope(node, closure) != "pathway_step":
        return
    verdict = closure["claim_verdict"]
    if verdict == "supported":
        step["status"] = "supported"
        step.setdefault("supporting_nodes", []).append(node["node_id"])
    elif verdict == "refuted":
        step["status"] = "refuted"
        step.setdefault("refuting_nodes", []).append(node["node_id"])
    elif verdict == "inconclusive":
        step["status"] = "active"
        step.setdefault("inconclusive_nodes", []).append(node["node_id"])
    pathway["status"] = _pathway_status_from_steps(pathway["steps"])


def _record_pathway_audit(
    pathway: dict[str, Any],
    step: dict[str, Any],
    node: dict[str, Any],
    closure: dict[str, Any],
) -> None:
    audit_record = {
        "node_id": node["node_id"],
        "program_status": closure["program_status"],
        "claim_verdict": closure["claim_verdict"],
        "reason_code": closure.get("reason_code"),
    }
    pathway.setdefault("audit_nodes", []).append(audit_record)
    step.setdefault("audit_nodes", []).append(audit_record)


def _write_acceptance_artifact(
    root: Path,
    node: dict[str, Any],
    closure: dict[str, Any],
    research_state: dict[str, Any],
    changes: dict[Path, Any],
) -> None:
    if node["phase"] != "accepted_audit":
        return
    if closure["program_status"] != "completed" or closure["claim_verdict"] != "supported":
        return
    hypothesis = _hypothesis_for_node(root, node)
    require_stereo = hypothesis_requires_stereochemical_gate(hypothesis)
    gate_evidence, mechanism_roles = _validated_acceptance_evidence(root, node, node.get("evidence_refs", []))
    required_gates = ["tsfreq_gate", "connectivity_gate"]
    evidence_refs = [
        gate_evidence["tsfreq_gate"]["evidence_id"],
        gate_evidence["connectivity_gate"]["evidence_id"],
    ]
    if require_stereo:
        required_gates.append(STEREOCHEMICAL_GATE_ROLE)
        evidence_refs.append(gate_evidence[STEREOCHEMICAL_GATE_ROLE]["evidence_id"])
    for role in sorted(mechanism_roles):
        required_gates.append(role)
        evidence_refs.append(gate_evidence[role]["evidence_id"])
    artifact = {
        "accepted_id": f"accepted_ts_{node['node_id']}",
        "node_id": node["node_id"],
        "phase": node["phase"],
        "hypothesis_ref": node.get("hypothesis_ref"),
        "required_gates": required_gates,
        "evidence_refs": evidence_refs,
    }
    artifact_path = root / "accepted" / f"{artifact['accepted_id']}.json"
    changes[artifact_path] = artifact
    research_state.setdefault("accepted_ts_refs", []).append(str(artifact_path.relative_to(root)))
    changes[root / RESEARCH_STATE_FILE] = research_state


def _ensure_pathway(model: dict[str, Any], pathway_id: str) -> dict[str, Any]:
    for pathway in model.setdefault("pathways", []):
        if pathway.get("pathway_id") == pathway_id:
            return pathway
    pathway = {
        "pathway_id": pathway_id,
        "label": pathway_id,
        "pattern": "unspecified",
        "status": "active",
        "steps": [],
    }
    model["pathways"].append(pathway)
    model["focus_pathway_id"] = pathway_id
    return pathway


def _ensure_step(pathway: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in pathway.setdefault("steps", []):
        if step.get("step_id") == step_id:
            return step
    step = {"step_id": step_id, "from": "unknown", "to": "unknown", "status": "active"}
    pathway["steps"].append(step)
    return step


def _pathway_status_from_steps(steps: list[dict[str, Any]]) -> str:
    statuses = {step.get("status") for step in steps}
    if "refuted" in statuses:
        return "refuted"
    if statuses and statuses <= {"supported"}:
        return "supported"
    return "active"


def _impact_scope(node: dict[str, Any], closure: dict[str, Any]) -> str:
    mechanism = closure.get("mechanism", {}) if isinstance(closure.get("mechanism"), dict) else {}
    explicit = mechanism.get("impact_scope")
    if explicit in IMPACT_SCOPES:
        return explicit
    if closure.get("claim_verdict") != "supported":
        return "solution_only"
    phase = node.get("phase")
    if phase == "accepted_audit":
        return "hypothesis"
    if phase in PATHWAY_STEP_STATUS_PHASES:
        return "pathway_step"
    if phase != "endpoint" and not _is_hypothesis_creation_node(node):
        return "prediction"
    return "solution_only"


def _is_hypothesis_creation_node(node: dict[str, Any]) -> bool:
    phase = node.get("phase")
    if phase in WORKSPACE_HYPOTHESIS_CREATION_PHASES:
        return True
    return phase == "endpoint" and isinstance(node.get("initial_mechanism_hypothesis"), dict)


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
