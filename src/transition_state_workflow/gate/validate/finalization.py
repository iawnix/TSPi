"""Finalization artifact checks for ChemGate workspace validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.base.rationale import lint_node_rationale
from transition_state_workflow.gate.evidence import accepted_ts_missing_evidence_gates
from transition_state_workflow.util.path_utils import clean_string, relative_path_or_absolute

from .contracts import Finding, REFLECTION_TEMPLATE_MARKERS
from .evidence import (
    group_evidence_records_by_node,
    group_registry_paths_by_node,
    validate_node_evidence_registry_coverage,
)


def validate_node_finalization_artifacts(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    parent_by_node: dict[str, str],
    input_refs_by_node: dict[str, list[str]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate post-execution node closure across reflection and evidence records."""

    records_by_node = group_evidence_records_by_node(evidence)
    registry_paths_by_node = group_registry_paths_by_node(source, evidence)
    for node_id, node_json in node_json_by_id.items():
        if not node_json:
            continue
        lifecycle = clean_string(node_json.get("lifecycle_state"))
        run_state = clean_string(node_json.get("run_state"))
        claim = clean_string(node_json.get("claim_status"))
        has_post_execution_state = lifecycle == "closed" or run_state in {"completed", "error", "stopped"}
        reflection_path = source / "nodes" / node_id / "reflection.md"
        validate_pre_execution_rationale(source, node_id, node_json, findings)
        if has_post_execution_state:
            validate_reflection_is_finalized(source, node_id, reflection_path, claim, findings)
        if claim != "not_evaluated" and not records_by_node.get(node_id):
            findings.append(
                Finding(
                    "warning",
                    "claim_without_evidence",
                    "node has evaluated claim_status but no evidence_registry record",
                    path="evidence_registry.json",
                    node_id=node_id,
                )
            )
        if claim == "accepted_ts":
            missing = accepted_ts_missing_evidence_gates(source, records_by_node.get(node_id, []))
            if missing:
                findings.append(
                    Finding(
                        "error",
                        "accepted_ts_missing_evidence_gates",
                        "accepted_ts requires supporting TS/Freq and connectivity evidence; "
                        f"missing gates: {', '.join(missing)}",
                        path="evidence_registry.json",
                        node_id=node_id,
                    )
                )
        if claim == "candidate_found" and not candidate_has_endpoint_gate(
            node_id=node_id,
            node_json_by_id=node_json_by_id,
            parent_by_node=parent_by_node,
            input_refs_by_node=input_refs_by_node,
        ):
            pathway_id = clean_string(node_json.get("pathway_id"))
            step_id = clean_string(node_json.get("elementary_step_id"))
            code = "pathway_candidate_without_step_endpoint_gate" if pathway_id or step_id else "candidate_without_endpoint_gate"
            suffix = " in the same pathway step" if pathway_id or step_id else ""
            findings.append(
                Finding(
                    "error",
                    code,
                    "candidate_found requires an upstream or dependency node with "
                    f"claim_status=endpoint_minima_ready{suffix}",
                    path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                    node_id=node_id,
                )
            )
        validate_node_evidence_registry_coverage(
            source=source,
            node_id=node_id,
            node_json=node_json,
            registry_paths=registry_paths_by_node.get(node_id, set()),
            findings=findings,
        )


def candidate_has_endpoint_gate(
    *,
    node_id: str,
    node_json_by_id: dict[str, dict[str, Any]],
    parent_by_node: dict[str, str],
    input_refs_by_node: dict[str, list[str]],
) -> bool:
    """Return true when a candidate has an upstream endpoint-minima claim."""

    target = node_json_by_id.get(node_id) or {}
    target_pathway_id = clean_string(target.get("pathway_id"))
    target_step_id = clean_string(target.get("elementary_step_id"))
    for upstream_id in iter_upstream_nodes(node_id, parent_by_node, input_refs_by_node):
        upstream = node_json_by_id.get(upstream_id) or {}
        if clean_string(upstream.get("claim_status")) == "endpoint_minima_ready":
            if target_pathway_id or target_step_id:
                if (
                    clean_string(upstream.get("pathway_id")) == target_pathway_id
                    and clean_string(upstream.get("elementary_step_id")) == target_step_id
                ):
                    return True
                continue
            return True
    return False


def iter_upstream_nodes(
    node_id: str,
    parent_by_node: dict[str, str],
    input_refs_by_node: dict[str, list[str]],
) -> list[str]:
    """Return transitive parent and dependency nodes for one branch node."""

    out: list[str] = []
    seen: set[str] = {node_id}

    def visit(current: str) -> None:
        for upstream in [parent_by_node.get(current, ""), *input_refs_by_node.get(current, [])]:
            upstream = clean_string(upstream)
            if not upstream or upstream in seen:
                continue
            seen.add(upstream)
            out.append(upstream)
            visit(upstream)

    visit(node_id)
    return out


def validate_pre_execution_rationale(
    source: Path,
    node_id: str,
    node_json: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate the node's pre-execution hypothesis and decision card rationale."""

    rationale = lint_node_rationale(source, node_id, node_json)
    if rationale.ok_to_start:
        return
    findings.append(
        Finding(
            rationale_finding_severity(node_json, rationale),
            "incomplete_pre_execution_rationale",
            rationale.summary(),
            path=relative_path_or_absolute(source, source / "nodes" / node_id / "decision_card.md"),
            node_id=node_id,
        )
    )


def rationale_finding_severity(node_json: dict[str, Any], rationale: Any | None = None) -> str:
    """Return validator severity for an incomplete pre-execution rationale."""

    if rationale is not None and getattr(rationale, "legacy_provenance_gap", False):
        return "info"
    lifecycle = clean_string(node_json.get("lifecycle_state"))
    run_state = clean_string(node_json.get("run_state"))
    claim = clean_string(node_json.get("claim_status"))
    if claim == "accepted_ts" or lifecycle in {"active", "closed", "superseded", "archived"}:
        return "error"
    if run_state in {"pending", "running", "parsing", "completed", "error", "stopped"}:
        return "error"
    return "warning"


def validate_reflection_is_finalized(
    source: Path,
    node_id: str,
    reflection_path: Path,
    claim_status: str,
    findings: list[Finding],
) -> None:
    """Warn when reflection.md still looks like the pre-execution template."""

    relative_path = relative_path_or_absolute(source, reflection_path)
    if not reflection_path.exists():
        findings.append(
            Finding(
                "warning",
                "missing_reflection",
                "closed or completed node is missing reflection.md",
                path=relative_path,
                node_id=node_id,
            )
        )
        return
    text = reflection_path.read_text(encoding="utf-8", errors="replace")
    lower_text = text.lower()
    template_hits = [line.strip() for line in text.splitlines() if line.strip() in REFLECTION_TEMPLATE_MARKERS]
    if template_hits:
        findings.append(
            Finding(
                "warning",
                "template_reflection_closed_node",
                "closed or completed node still contains template reflection text",
                path=relative_path,
                node_id=node_id,
            )
        )
    if claim_status != "not_evaluated":
        required_sections = ("Computational Outcome", "Mechanistic Implication", "Next Branch")
        missing_sections = [section for section in required_sections if f"## {section}".lower() not in lower_text]
        if missing_sections:
            findings.append(
                Finding(
                    "warning",
                    "reflection_missing_required_sections",
                    f"finalized evaluated node reflection is missing sections: {', '.join(missing_sections)}",
                    path=relative_path,
                    node_id=node_id,
                )
            )
        if reflection_has_empty_template_bullets(text):
            findings.append(
                Finding(
                    "warning",
                    "template_reflection_closed_node",
                    "closed or completed node still contains empty template bullets",
                    path=relative_path,
                    node_id=node_id,
                )
            )
    if claim_status == "accepted_ts" and ("not accepted" in lower_text or "not yet proven" in lower_text):
        findings.append(
            Finding(
                "warning",
                "reflection_claim_conflict",
                "node is accepted_ts but reflection text says the claim is not accepted or not proven",
                path=relative_path,
                node_id=node_id,
            )
        )
    if claim_status == "not_evaluated" and "accepted ts" in lower_text:
        findings.append(
            Finding(
                "warning",
                "reflection_claim_conflict",
                "node is not_evaluated but reflection text appears to claim an accepted TS",
                path=relative_path,
                node_id=node_id,
            )
        )


def reflection_has_empty_template_bullets(text: str) -> bool:
    """Return true when reflection sections still contain only dash placeholders."""

    lines = [line.rstrip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        body: list[str] = []
        for next_line in lines[index + 1 :]:
            if next_line.startswith("## "):
                break
            stripped = next_line.strip()
            if stripped:
                body.append(stripped)
        if body == ["-"] or body == ["- Validated facts:", "- Refuted hypotheses:", "- Open questions:"]:
            return True
    return False


__all__ = [
    "validate_node_finalization_artifacts",
    "candidate_has_endpoint_gate",
    "iter_upstream_nodes",
    "validate_pre_execution_rationale",
    "validate_reflection_is_finalized",
    "reflection_has_empty_template_bullets",
]
