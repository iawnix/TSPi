"""Report context assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.io import read_json, sha256_json
from ts_workspace.ontology import node_scope_of, node_type_of
from ts_workspace.state import EVIDENCE_FILE, HYPOTHESES_FILE, RESEARCH_STATE_FILE
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

    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    hypotheses = read_json(root_path / HYPOTHESES_FILE)
    evidence = read_json(root_path / EVIDENCE_FILE)
    manifest = research_state
    tree = research_state
    mechanism = hypotheses
    pathway = hypotheses
    records = [item for item in evidence.get("evidence", []) if isinstance(item, dict)]
    nodes = [item for item in tree.get("nodes", []) if isinstance(item, dict)]
    accepted_refs = [str(item) for item in manifest.get("accepted_ts_refs", []) if item]
    active = active_hypothesis(mechanism)
    artifacts = evidence_artifacts(root_path, records)
    center = reaction_center(active)
    tsfreq = collect_tsfreq(root_path, records, artifacts)
    connectivity = collect_connectivity(records, artifacts)
    validation_scopes = validation_scopes_reached(nodes, records)
    context: dict[str, Any] = {
        "workspace_root": str(root_path),
        "workspace_revision": sha256_json(
            {"research_state": research_state, "hypotheses": hypotheses, "evidence": evidence}
        ),
        "manifest": manifest,
        "pathway_model": pathway,
        "nodes": nodes,
        "evidence_records": records,
        "accepted_ts_refs": accepted_refs,
        "highest_validated_layer": highest_validated_layer(nodes, accepted_refs, records),
        "validation_scopes_reached": validation_scopes,
        "final_claim": final_claim(nodes, records),
        "active_hypothesis": active,
        "reaction_center": center,
        "structures": collect_structures(root_path, active, records, artifacts),
        "tsfreq": tsfreq,
        "connectivity": connectivity,
    }
    context["distance_profile"] = collect_distance_profile(active, tsfreq, connectivity)
    context["energy_profile"] = collect_energy_profile(records, artifacts, tsfreq)
    context["limitations"] = collect_limitations(records, connectivity)
    context["mechanism_interpretation"] = build_mechanism_interpretation(context)
    context["assets"] = {}
    return context


def highest_validated_layer(nodes: list[dict[str, Any]], accepted_refs: list[str], records: list[dict[str, Any]]) -> str:
    for node in reversed(nodes):
        if _is_pathway_audit(node) and _node_is_closed(node):
            if pathway_audit_outcome_for_node(node.get("node_id"), records):
                return "pathway"
    if accepted_refs or any(_is_accepted_ts_audit(node) for node in nodes):
        return "accepted_ts"
    if any(_v2_validation_reached(node, records, "connectivity", "connectivity_gate") for node in nodes) or any(
        node.get("phase") == "connectivity_validation" and node.get("claim_verdict") == "supported" for node in nodes
    ):
        return "connectivity"
    if any(_v2_validation_reached(node, records, "tsfreq", "tsfreq_gate") for node in nodes) or any(
        node.get("phase") == "tsfreq_validation" and node.get("claim_verdict") == "supported" for node in nodes
    ):
        return "tsfreq"
    if validation_scopes_reached(nodes, records):
        return "validation"
    if any(_v2_candidate_reached(node, records) for node in nodes) or any(
        node.get("phase") == "candidate_generation" and node.get("claim_verdict") == "supported" for node in nodes
    ):
        return "candidate"
    return "intake" if any(_is_v2_node(node) for node in nodes) else "endpoint"


def validation_scopes_reached(nodes: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[str]:
    scopes: set[str] = set()
    for node in nodes:
        if (
            _is_v2_node(node)
            and node_type_of(node) == "validation"
            and _node_is_closed(node)
            and node_program_outcome(node) == "success"
            and _node_has_any_evidence(node, records)
        ):
            scope = node_scope_of(node)
            if scope:
                scopes.add(scope)
    return sorted(scopes)


def final_claim(nodes: list[dict[str, Any]], records: list[dict[str, Any]]) -> str:
    for node in reversed(nodes):
        if not _is_pathway_audit(node):
            continue
        outcome = pathway_audit_outcome_for_node(node.get("node_id"), records)
        if outcome == "pathway_not_accepted":
            return "not_accepted"
        if outcome:
            return outcome
    if any(_is_accepted_ts_audit(node) for node in nodes):
        return "accepted_ts"
    return "incomplete"


def node_label(node: dict[str, Any]) -> str:
    if not _is_v2_node(node):
        return str(node.get("phase") or "unknown")
    node_type = node_type_of(node) or "unknown"
    scope = node_scope_of(node)
    return f"{node_type}/{scope}" if scope else node_type


def node_program_outcome(node: dict[str, Any]) -> str:
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    program = closure.get("program") if isinstance(closure.get("program"), dict) else {}
    if _is_v2_node(node):
        return str(node.get("program_outcome") or program.get("outcome") or "")
    return str(node.get("program_status") or closure.get("program_status") or "")


def node_hypothesis_status(node: dict[str, Any]) -> str:
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    hypothesis = closure.get("hypothesis") if isinstance(closure.get("hypothesis"), dict) else {}
    return str(node.get("hypothesis_status") or hypothesis.get("status") or "")


def node_audit_status(node: dict[str, Any]) -> str:
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
    return str(node.get("audit_status") or audit.get("status") or "")


def node_scientific_status(node: dict[str, Any]) -> str:
    if not _is_v2_node(node):
        closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
        return str(node.get("claim_verdict") or closure.get("claim_verdict") or "open")
    if node_type_of(node) == "mechanism":
        return node_hypothesis_status(node) or "open"
    if node_type_of(node) == "audit":
        return node_audit_status(node) or "open"
    if node_type_of(node) == "intake":
        closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
        intake = closure.get("intake") if isinstance(closure.get("intake"), dict) else {}
        return str(node.get("intake_status") or intake.get("status") or "open")
    return "evidence_only"


def _is_pathway_audit(node: dict[str, Any]) -> bool:
    return node.get("phase") == "pathway_audit" or (
        node_type_of(node) == "audit" and node_scope_of(node) == "pathway"
    )


def _is_accepted_ts_audit(node: dict[str, Any]) -> bool:
    if not _node_is_closed(node):
        return False
    if node.get("phase") == "accepted_audit":
        return node.get("claim_verdict") == "supported"
    return (
        node_type_of(node) == "audit"
        and node_scope_of(node) in {"transition_state", "elementary_step"}
        and node_audit_status(node) == "accepted"
    )


def _node_is_closed(node: dict[str, Any]) -> bool:
    return node.get("lifecycle") in {"closed", "stopped"}


def _is_v2_node(node: dict[str, Any]) -> bool:
    return isinstance(node.get("node_type"), str)


def _v2_validation_reached(
    node: dict[str, Any],
    records: list[dict[str, Any]],
    scope: str,
    role: str,
) -> bool:
    return (
        _is_v2_node(node)
        and node_type_of(node) == "validation"
        and node_scope_of(node) == scope
        and _node_is_closed(node)
        and node_program_outcome(node) == "success"
        and _node_has_evidence_role(node, records, {role})
    )


def _v2_candidate_reached(node: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    return (
        _is_v2_node(node)
        and node_type_of(node) == "candidate_search"
        and _node_is_closed(node)
        and node_program_outcome(node) == "success"
        and _node_has_evidence_role(
            node,
            records,
            {"candidate_geometry", "candidate_generation_log", "endpoint_conformer_ensemble"},
        )
    )


def _node_has_evidence_role(
    node: dict[str, Any],
    records: list[dict[str, Any]],
    roles: set[str],
) -> bool:
    refs = set(str(item) for item in node.get("evidence_refs", []) if item)
    node_id = node.get("node_id")
    return any(
        record.get("role") in roles
        and (record.get("node_id") == node_id or record.get("evidence_id") in refs)
        for record in records
    )


def _node_has_any_evidence(node: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    refs = set(str(item) for item in node.get("evidence_refs", []) if item)
    node_id = node.get("node_id")
    return any(
        record.get("node_id") == node_id or record.get("evidence_id") in refs
        for record in records
    )


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
