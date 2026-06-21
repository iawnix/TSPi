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
    lines = [
        "# Transition-State Report",
        "",
        f"- workspace: {root_path}",
        f"- accepted TS refs: {len(manifest.get('accepted_ts_refs', []))}",
        f"- nodes: {len(tree.get('nodes', []))}",
        f"- evidence entries: {len(evidence.get('evidence', []))}",
        "",
        "## Evidence Layers",
        "",
        "- Candidate evidence is not an accepted TS.",
        "- TS/Freq validation requires a phase closure with a supported claim.",
        "- Connectivity validation requires endpoint assignment evidence.",
        "- Accepted TS requires the workspace accepted audit artifact.",
        "",
        "## Nodes",
        "",
    ]
    for node in tree.get("nodes", []):
        audit_note = _pathway_audit_note(node, evidence.get("evidence", []))
        lines.append(
            f"- {node['node_id']}: {node['phase']} / {node['lifecycle']} / "
            f"{node.get('claim_verdict', 'open')}{audit_note}"
        )
    return "\n".join(lines) + "\n"


def _pathway_audit_note(node: dict[str, Any], evidence_records: list[Any]) -> str:
    if node.get("phase") != "pathway_audit":
        return ""
    node_id = node.get("node_id")
    for record in evidence_records:
        if not isinstance(record, dict) or record.get("node_id") != node_id:
            continue
        quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
        decision = str(quality.get("strict_pathway_decision") or quality.get("audit_outcome") or "").lower()
        if quality.get("strict_pathway_supported") is False or decision in {"not_accepted", "pathway_not_accepted"}:
            return " (audit_outcome=pathway_not_accepted)"
    reason = str(node.get("reason_code") or "").lower()
    if "not_accepted" in reason or "missing" in reason:
        return " (audit_outcome=pathway_not_accepted)"
    return ""
