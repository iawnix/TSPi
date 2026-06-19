"""Build a final Markdown report from a validated workspace."""

from __future__ import annotations

from pathlib import Path

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
        lines.append(f"- {node['node_id']}: {node['phase']} / {node['lifecycle']} / {node.get('claim_verdict', 'open')}")
    return "\n".join(lines) + "\n"
