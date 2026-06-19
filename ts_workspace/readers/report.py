"""LLM-facing workspace report builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import compact_id_time, read_json, write_json
from ..validators.workspace import validate_workspace


def report_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    validation = validate_workspace(root_path)
    report_id = f"rep_{compact_id_time()}"

    manifest = _read_or_empty(root_path / "manifest.json")
    tree = _read_or_empty(root_path / "tree.json")
    evidence = _read_or_empty(root_path / "evidence_registry.json")
    pathway = _read_or_empty(root_path / "pathway_model.json")

    nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
    open_nodes = [item for item in nodes if item.get("lifecycle") == "running"]
    closed_nodes = [item for item in nodes if item.get("lifecycle") in {"closed", "stopped"}]

    report = {
        "report_id": report_id,
        "workspace_root": str(root_path),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "current_node": tree.get("current_node"),
            "focus_pathway_id": pathway.get("focus_pathway_id"),
            "accepted_ts_refs": manifest.get("accepted_ts_refs", []),
        },
        "node_index": nodes,
        "open_nodes": open_nodes,
        "closed_node_count": len(closed_nodes),
        "evidence_count": len(evidence.get("evidence", [])) if isinstance(evidence, dict) else 0,
        "backtrack_events": tree.get("backtrack_events", []),
        "ledger_refs": {
            "manifest": "manifest.json",
            "tree": "tree.json",
            "evidence_registry": "evidence_registry.json",
            "mechanism_model": "mechanism_model.json",
            "pathway_model": "pathway_model.json",
            "knowledge_base": "knowledge_base.md",
        },
        "allowed_decision_actions": ["start_node", "end_node", "update_workspace", "ask_user", "stop"],
        "decision_contract": {
            "schema_version": "ts-decision",
            "requires_report_ref": ["start_node", "end_node", "update_workspace"],
            "mutation_channel": "ts_workspace",
        },
    }
    write_json(root_path / "reports" / f"{report_id}.json", report)
    return report


def _read_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001
        return {}
