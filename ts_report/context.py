"""Report context assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.io import read_json
from ts_workspace.validators.workspace import validate_workspace

from .extractors import (
    active_hypothesis,
    collect_connectivity,
    collect_distance_profile,
    collect_energy_profile,
    collect_limitations,
    collect_structures,
    collect_tsfreq,
    evidence_artifacts,
    reaction_center,
)
from .mechanism import build_mechanism_interpretation


def collect_report_context(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    validation = validate_workspace(root_path)
    if not validation["valid"]:
        errors = "; ".join(item["message"] for item in validation["findings"] if item["severity"] == "error")
        raise ValueError(f"workspace is invalid: {errors}")

    manifest = read_json(root_path / "manifest.json")
    tree = read_json(root_path / "tree.json")
    evidence = read_json(root_path / "evidence_registry.json")
    mechanism = read_json(root_path / "mechanism_model.json")
    pathway = read_json(root_path / "pathway_model.json")
    records = [item for item in evidence.get("evidence", []) if isinstance(item, dict)]
    nodes = [item for item in tree.get("nodes", []) if isinstance(item, dict)]
    accepted_refs = [str(item) for item in manifest.get("accepted_ts_refs", []) if item]
    active = active_hypothesis(mechanism)
    artifacts = evidence_artifacts(root_path, records)
    center = reaction_center(active)
    tsfreq = collect_tsfreq(root_path, records, artifacts)
    connectivity = collect_connectivity(records, artifacts)
    context: dict[str, Any] = {
        "workspace_root": str(root_path),
        "manifest": manifest,
        "pathway_model": pathway,
        "nodes": nodes,
        "evidence_records": records,
        "accepted_ts_refs": accepted_refs,
        "highest_validated_layer": highest_validated_layer(nodes, accepted_refs, records),
        "final_claim": final_claim(nodes, records),
        "active_hypothesis": active,
        "reaction_center": center,
        "structures": collect_structures(root_path, active, records, artifacts),
        "tsfreq": tsfreq,
        "connectivity": connectivity,
    }
    context["distance_profile"] = collect_distance_profile(active, tsfreq, connectivity)
    context["energy_profile"] = collect_energy_profile(tsfreq)
    context["limitations"] = collect_limitations(records, connectivity)
    context["mechanism_interpretation"] = build_mechanism_interpretation(context)
    context["assets"] = {}
    return context


def highest_validated_layer(nodes: list[dict[str, Any]], accepted_refs: list[str], records: list[dict[str, Any]]) -> str:
    for node in reversed(nodes):
        if node.get("phase") == "pathway_audit" and node.get("claim_verdict") == "supported":
            if pathway_audit_outcome_for_node(node.get("node_id"), records):
                return "pathway"
    if accepted_refs or any(node.get("phase") == "accepted_audit" and node.get("claim_verdict") == "supported" for node in nodes):
        return "accepted_ts"
    if any(node.get("phase") == "connectivity_validation" and node.get("claim_verdict") == "supported" for node in nodes):
        return "connectivity"
    if any(node.get("phase") == "tsfreq_validation" and node.get("claim_verdict") == "supported" for node in nodes):
        return "tsfreq"
    if any(node.get("phase") == "candidate_generation" and node.get("claim_verdict") == "supported" for node in nodes):
        return "candidate"
    return "endpoint"


def final_claim(nodes: list[dict[str, Any]], records: list[dict[str, Any]]) -> str:
    for node in reversed(nodes):
        if node.get("phase") != "pathway_audit":
            continue
        outcome = pathway_audit_outcome_for_node(node.get("node_id"), records)
        if outcome == "pathway_not_accepted":
            return "not_accepted"
        if outcome:
            return outcome
    if any(node.get("phase") == "accepted_audit" and node.get("claim_verdict") == "supported" for node in nodes):
        return "accepted_ts"
    return "incomplete"


def pathway_audit_outcome_for_node(node_id: Any, records: list[Any]) -> str | None:
    for record in records:
        if not isinstance(record, dict) or record.get("node_id") != node_id:
            continue
        quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
        facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
        decision = str(
            quality.get("strict_pathway_decision")
            or quality.get("audit_outcome")
            or facts.get("strict_pathway_decision")
            or facts.get("audit_outcome")
            or facts.get("verdict")
            or ""
        ).lower()
        if quality.get("strict_pathway_supported") is False or decision in {"not_accepted", "pathway_not_accepted"}:
            return "pathway_not_accepted"
        if decision in {"accepted", "pathway_accepted"} or quality.get("strict_pathway_supported") is True:
            return "accepted"
        if facts.get("whole_R_to_P_pathway_accepted") is False:
            return "pathway_not_accepted"
        if facts.get("whole_R_to_P_pathway_accepted") is True:
            return "accepted"
    return None
