"""Build a final Markdown report from a validated workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.io import read_json
from ts_workspace.validators.workspace import validate_workspace


def build_final_report(root: str | Path) -> str:
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

    evidence_records = [item for item in evidence.get("evidence", []) if isinstance(item, dict)]
    nodes = [item for item in tree.get("nodes", []) if isinstance(item, dict)]
    accepted_refs = [str(item) for item in manifest.get("accepted_ts_refs", []) if item]
    highest_layer = _highest_validated_layer(nodes, accepted_refs, evidence_records)
    final_claim = _final_claim(highest_layer, nodes, evidence_records)

    lines = [
        "# Transition-State Search Report",
        "",
        "## 1. Executive Verdict",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Workspace | `{root_path}` |",
        f"| Highest validated layer | `{highest_layer}` |",
        f"| Final claim | `{final_claim}` |",
        f"| Accepted TS refs | `{', '.join(accepted_refs) or 'none'}` |",
        f"| Nodes | {len(nodes)} |",
        f"| Evidence entries | {len(evidence_records)} |",
        "",
        _conclusion_sentence(highest_layer, final_claim, accepted_refs),
        "",
        "## 2. Reaction And Hypothesis Scope",
        "",
        *_hypothesis_scope_lines(mechanism),
        "",
        "## 3. Evidence Layers",
        "",
        *_evidence_layer_lines(evidence_records, accepted_refs),
        "",
        "## 4. Search Tree Summary",
        "",
        "| Node | Phase | Lifecycle | Program status | Claim verdict | Audit outcome |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for node in nodes:
        audit_note = _pathway_audit_note(node, evidence_records)
        audit_outcome = audit_note.removeprefix(" (audit_outcome=").removesuffix(")") if audit_note else ""
        lines.append(
            f"| `{node['node_id']}` | {node['phase']} | {node['lifecycle']} | "
            f"{node.get('program_status', '')} | {node.get('claim_verdict', 'open')} | {audit_outcome} |"
        )

    # Keep the compact node index for compatibility with existing consumers.
    lines.extend(["", "Node index:", ""])
    for node in nodes:
        audit_note = _pathway_audit_note(node, evidence_records)
        lines.append(
            f"- {node['node_id']}: {node['phase']} / {node['lifecycle']} / "
            f"{node.get('claim_verdict', 'open')}{audit_note}"
        )

    lines.extend(
        [
            "",
            "## 5. Pathway Model",
            "",
            *_pathway_lines(pathway, evidence_records),
            "",
            "## 6. Artifact And Evidence Appendix",
            "",
            "| Evidence ID | Role | Kind | Node | Path | Summary |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for record in evidence_records:
        lines.append(
            f"| `{record.get('evidence_id', '')}` | {record.get('role', '')} | {record.get('kind', '')} | "
            f"`{record.get('node_id', '')}` | `{record.get('path', '')}` | {_escape_table(str(record.get('summary', '')))} |"
        )
    return "\n".join(lines) + "\n"


def _highest_validated_layer(nodes: list[dict[str, Any]], accepted_refs: list[str], evidence_records: list[dict[str, Any]]) -> str:
    for node in reversed(nodes):
        if node.get("phase") == "pathway_audit" and node.get("claim_verdict") == "supported":
            if _pathway_audit_outcome_for_node(node.get("node_id"), evidence_records):
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


def _final_claim(highest_layer: str, nodes: list[dict[str, Any]], evidence_records: list[dict[str, Any]]) -> str:
    if highest_layer == "pathway":
        for node in reversed(nodes):
            if node.get("phase") == "pathway_audit":
                outcome = _pathway_audit_outcome_for_node(node.get("node_id"), evidence_records)
                if outcome == "pathway_not_accepted":
                    return "not_accepted"
                if outcome:
                    return outcome
    if highest_layer == "accepted_ts":
        return "accepted_ts"
    return "incomplete"


def _conclusion_sentence(highest_layer: str, final_claim: str, accepted_refs: list[str]) -> str:
    if highest_layer == "pathway" and final_claim in {"accepted", "pathway_accepted"}:
        return (
            "**Conclusion.** The workspace evidence supports the audited pathway. "
            f"Accepted TS artifacts: `{', '.join(accepted_refs)}`."
        )
    if highest_layer == "pathway" and final_claim == "not_accepted":
        return "**Conclusion.** The pathway audit supports a negative conclusion; the audited pathway is not accepted."
    if highest_layer == "accepted_ts":
        return (
            "**Conclusion.** The transition state is accepted by TS/Freq and connectivity gates, "
            "but no accepted pathway audit is present."
        )
    return f"**Conclusion.** Highest supported layer is `{highest_layer}`; do not report beyond that layer."


def _hypothesis_scope_lines(mechanism: dict[str, Any]) -> list[str]:
    focus_id = mechanism.get("focus_hypothesis_id")
    hypotheses = [item for item in mechanism.get("hypotheses", []) if isinstance(item, dict)]
    active = next((item for item in hypotheses if item.get("hypothesis_id") == focus_id), hypotheses[-1] if hypotheses else {})
    derived = active.get("derived_from") if isinstance(active.get("derived_from"), dict) else {}
    lines = [
        "| Item | Value |",
        "| --- | --- |",
        f"| Hypothesis | `{active.get('hypothesis_id', focus_id or '')}` |",
        f"| Summary | {_escape_table(str(active.get('summary', '')))} |",
        f"| Reactant | `{derived.get('reactant_ref', '')}` |",
        f"| Product | `{derived.get('product_ref', '')}` |",
        f"| Charge / multiplicity | `{derived.get('charge', '')} / {derived.get('multiplicity', '')}` |",
    ]
    claim = active.get("structured_claim") if isinstance(active.get("structured_claim"), dict) else {}
    center = claim.get("reaction_center") if isinstance(claim.get("reaction_center"), dict) else {}
    forming = ", ".join(item.get("label", str(item.get("atoms", ""))) for item in center.get("forming_bonds", []) if isinstance(item, dict))
    breaking = ", ".join(item.get("label", str(item.get("atoms", ""))) for item in center.get("breaking_bonds", []) if isinstance(item, dict))
    lines.append(f"| Forming bonds | {forming or ''} |")
    lines.append(f"| Breaking bonds | {breaking or ''} |")
    return lines


def _evidence_layer_lines(evidence_records: list[dict[str, Any]], accepted_refs: list[str]) -> list[str]:
    return [
        "### TS/Freq",
        "",
        *_role_table(evidence_records, {"tsfreq_gate", "mode_assignment"}),
        "",
        "### Connectivity / IRC",
        "",
        *_role_table(evidence_records, {"connectivity_gate", "irc_endpoint_assignment"}),
        "",
        "### Accepted TS",
        "",
        f"- Accepted artifacts: `{', '.join(accepted_refs) or 'none'}`",
        "",
        "### Pathway Audit",
        "",
        *_role_table(evidence_records, {"pathway_audit", "pathway_audit_summary"}),
    ]


def _role_table(evidence_records: list[dict[str, Any]], roles: set[str]) -> list[str]:
    rows = [record for record in evidence_records if record.get("role") in roles]
    if not rows:
        return ["- none"]
    lines = ["| Evidence | Role | Key facts | Path |", "| --- | --- | --- | --- |"]
    for record in rows:
        lines.append(
            f"| `{record.get('evidence_id', '')}` | {record.get('role', '')} | "
            f"{_escape_table(_key_facts(record))} | `{record.get('path', '')}` |"
        )
    return lines


def _key_facts(record: dict[str, Any]) -> str:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
    merged = {**quality, **facts}
    preferred = [
        "method",
        "basis",
        "electronic_energy_hartree",
        "imaginary_frequency_count",
        "imaginary_frequencies_cm-1",
        "verdict_against_prediction",
        "reverse_assignment",
        "forward_assignment",
        "strict_pathway_decision",
        "strict_pathway_supported",
        "whole_R_to_P_pathway_accepted",
    ]
    parts = [f"{key}={merged[key]}" for key in preferred if key in merged]
    if not parts:
        return str(record.get("summary", ""))
    return "; ".join(str(item) for item in parts)


def _pathway_lines(pathway: dict[str, Any], evidence_records: list[dict[str, Any]]) -> list[str]:
    lines = [f"- focus_pathway_id: `{pathway.get('focus_pathway_id', '')}`"]
    for item in pathway.get("pathways", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- `{item.get('pathway_id', '')}`: status `{item.get('status', '')}`, pattern `{item.get('pattern', '')}`")
    outcomes = [
        _pathway_audit_outcome_for_node(record.get("node_id"), evidence_records)
        for record in evidence_records
        if record.get("role") in {"pathway_audit", "pathway_audit_summary"}
    ]
    outcomes = [item for item in outcomes if item]
    if outcomes:
        lines.append(f"- latest pathway audit outcome: `{outcomes[-1]}`")
    return lines


def _pathway_audit_note(node: dict[str, Any], evidence_records: list[Any]) -> str:
    if node.get("phase") != "pathway_audit":
        return ""
    outcome = _pathway_audit_outcome_for_node(node.get("node_id"), evidence_records)
    if outcome:
        return f" (audit_outcome={outcome})"
    reason = str(node.get("reason_code") or "").lower()
    if "not_accepted" in reason or "missing" in reason:
        return " (audit_outcome=pathway_not_accepted)"
    return ""


def _pathway_audit_outcome_for_node(node_id: Any, evidence_records: list[Any]) -> str | None:
    for record in evidence_records:
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


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
