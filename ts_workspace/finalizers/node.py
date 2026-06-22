"""Node close finalizer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import append_markdown, read_json, write_json

PATHWAY_STEP_STATUS_PHASES = {"connectivity_validation", "accepted_audit"}
INITIAL_HYPOTHESIS_PHASES = {"preflight", "endpoint"}


def finalize_closed_node(root: Path, node: dict[str, Any], decision: dict[str, Any]) -> None:
    closure = node["closure"]
    _update_mechanism_model(root, node, closure)
    _update_pathway_model(root, node, closure)
    _append_knowledge(root, node, closure)
    _write_acceptance_artifact(root, node, closure)


def validate_accepted_audit_gates(root: Path, node: dict[str, Any], closure: dict[str, Any], evidence_refs: list[str]) -> None:
    if node["phase"] != "accepted_audit":
        return
    if closure["program_status"] != "completed" or closure["claim_verdict"] != "supported":
        return
    gate_evidence = _accepted_gate_evidence(root, evidence_refs)
    hypothesis_id = node.get("hypothesis_ref", {}).get("hypothesis_id") if isinstance(node.get("hypothesis_ref"), dict) else None
    if gate_evidence.get("__hypothesis_id") != hypothesis_id:
        raise ValueError("accepted audit gate evidence must match node.hypothesis_ref")


def _update_mechanism_model(root: Path, node: dict[str, Any], closure: dict[str, Any]) -> None:
    path = root / "mechanism_model.json"
    model = read_json(path)
    model.setdefault("focus_hypothesis_id", None)
    if node.get("phase") in INITIAL_HYPOTHESIS_PHASES:
        _finalize_initial_hypothesis(root, model, node, closure)
        write_json(path, model)
        return

    mechanism = closure.get("mechanism", {}) if isinstance(closure.get("mechanism"), dict) else {}
    ref = mechanism.get("hypothesis_ref") if isinstance(mechanism.get("hypothesis_ref"), dict) else {}
    hypothesis_id = ref.get("hypothesis_id")
    hypothesis = _find_hypothesis(model, hypothesis_id)
    evidence_refs = sorted(set(hypothesis.get("evidence_refs", []) + node.get("evidence_refs", []) + mechanism.get("evidence_refs", [])))
    hypothesis["evidence_refs"] = evidence_refs
    _append_prediction_status(hypothesis, node, closure, ref, mechanism)
    _apply_revision(model, hypothesis, node, closure, mechanism)

    if node.get("phase") == "accepted_audit" and closure["program_status"] == "completed" and closure["claim_verdict"] == "supported":
        hypothesis["status"] = "supported"
        model.setdefault("accepted_facts", []).append(_mechanism_entry(node, closure, hypothesis_id, evidence_refs))
    elif closure["claim_verdict"] in {"inconclusive", "not_evaluated"}:
        model.setdefault("open_questions", []).append(_mechanism_entry(node, closure, hypothesis_id, evidence_refs))
    write_json(path, model)


def _finalize_initial_hypothesis(root: Path, model: dict[str, Any], node: dict[str, Any], closure: dict[str, Any]) -> None:
    if closure.get("program_status") != "completed":
        return
    initial = node.get("initial_mechanism_hypothesis")
    if not isinstance(initial, dict):
        raise ValueError("completed endpoint/preflight node missing initial_mechanism_hypothesis")

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
    for entry in registry.get("evidence", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") in evidence_refs and entry.get("role") == "initial_mechanism_hypothesis":
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


def _update_pathway_model(root: Path, node: dict[str, Any], closure: dict[str, Any]) -> None:
    pathway_ref = node.get("pathway_ref")
    if not pathway_ref:
        return
    path = root / "pathway_model.json"
    model = read_json(path)
    pathway_id = pathway_ref["pathway_id"]
    step_id = pathway_ref["step_id"]
    pathway = _ensure_pathway(model, pathway_id)
    step = _ensure_step(pathway, step_id)
    if node["phase"] == "pathway_audit":
        _record_pathway_audit(pathway, step, node, closure)
        write_json(path, model)
        return
    if node["phase"] not in PATHWAY_STEP_STATUS_PHASES:
        write_json(path, model)
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
    write_json(path, model)


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


def _append_knowledge(root: Path, node: dict[str, Any], closure: dict[str, Any]) -> None:
    body = "\n".join(
        [
            f"- node: {node['node_id']}",
            f"- phase: {node['phase']}",
            f"- program_status: {closure['program_status']}",
            f"- claim_verdict: {closure['claim_verdict']}",
            f"- program: {closure.get('program', {}).get('summary', '')}",
            f"- mechanism: {closure.get('mechanism', {}).get('summary', '')}",
            f"- implication: {closure.get('implication', '')}",
        ]
    )
    append_markdown(root / "knowledge_base.md", f"Node {node['node_id']} closure", body)


def _write_acceptance_artifact(root: Path, node: dict[str, Any], closure: dict[str, Any]) -> None:
    if node["phase"] != "accepted_audit":
        return
    if closure["program_status"] != "completed" or closure["claim_verdict"] != "supported":
        return
    gate_evidence = _accepted_gate_evidence(root, node.get("evidence_refs", []))
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path)
    artifact = {
        "accepted_id": f"accepted_ts_{node['node_id']}",
        "node_id": node["node_id"],
        "phase": node["phase"],
        "hypothesis_ref": node.get("hypothesis_ref"),
        "required_gates": ["tsfreq_gate", "connectivity_gate"],
        "evidence_refs": [gate_evidence["tsfreq_gate"], gate_evidence["connectivity_gate"]],
    }
    artifact_path = root / "accepted" / f"{artifact['accepted_id']}.json"
    write_json(artifact_path, artifact)
    manifest.setdefault("accepted_ts_refs", []).append(str(artifact_path.relative_to(root)))
    write_json(manifest_path, manifest)


def _accepted_gate_evidence(root: Path, evidence_refs: list[str]) -> dict[str, str]:
    registry = read_json(root / "evidence_registry.json")
    allowed_refs = set(evidence_refs)
    gate_evidence: dict[str, str] = {}
    gate_hypothesis_ids: set[str] = set()
    for entry in registry.get("evidence", []):
        if not isinstance(entry, dict):
            continue
        evidence_id = entry.get("evidence_id")
        role = entry.get("role")
        if evidence_id in allowed_refs and role in {"connectivity_gate", "tsfreq_gate"}:
            gate_evidence[role] = evidence_id
            quality = entry.get("quality") if isinstance(entry.get("quality"), dict) else {}
            hypothesis_id = quality.get("hypothesis_id")
            if not hypothesis_id:
                raise ValueError(f"accepted audit gate evidence missing quality.hypothesis_id: {evidence_id}")
            gate_hypothesis_ids.add(str(hypothesis_id))
    missing_gates = sorted({"connectivity_gate", "tsfreq_gate"} - set(gate_evidence))
    if missing_gates:
        raise ValueError(f"accepted audit missing required evidence gates: {', '.join(missing_gates)}")
    if len(gate_hypothesis_ids) != 1:
        raise ValueError("accepted audit gate evidence must share one hypothesis_id")
    gate_evidence["__hypothesis_id"] = next(iter(gate_hypothesis_ids))
    return gate_evidence


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
