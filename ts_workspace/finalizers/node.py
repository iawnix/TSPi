"""Node close finalizer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import append_markdown, read_json, write_json


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
    _accepted_gate_evidence(root, evidence_refs)


def _update_mechanism_model(root: Path, node: dict[str, Any], closure: dict[str, Any]) -> None:
    path = root / "mechanism_model.json"
    model = read_json(path)
    entry = {
        "node_id": node["node_id"],
        "phase": node["phase"],
        "hypothesis": node["hypothesis"],
        "program_status": closure["program_status"],
        "claim_verdict": closure["claim_verdict"],
        "mechanism_summary": closure.get("mechanism", {}).get("summary", ""),
        "evidence_refs": sorted(set(node.get("evidence_refs", []) + closure.get("mechanism", {}).get("evidence_refs", []))),
    }
    bucket = {
        "supported": "accepted_facts",
        "refuted": "refuted_hypotheses",
        "inconclusive": "open_questions",
        "not_evaluated": "open_questions",
    }[closure["claim_verdict"]]
    model.setdefault(bucket, []).append(entry)
    write_json(path, model)


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
    for entry in registry.get("evidence", []):
        if not isinstance(entry, dict):
            continue
        evidence_id = entry.get("evidence_id")
        role = entry.get("role")
        if evidence_id in allowed_refs and role in {"connectivity_gate", "tsfreq_gate"}:
            gate_evidence[role] = evidence_id
    missing_gates = sorted({"connectivity_gate", "tsfreq_gate"} - set(gate_evidence))
    if missing_gates:
        raise ValueError(f"accepted audit missing required evidence gates: {', '.join(missing_gates)}")
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
