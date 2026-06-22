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
    mechanism = _read_or_empty(root_path / "mechanism_model.json")

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
            "focus_hypothesis_id": mechanism.get("focus_hypothesis_id"),
            "accepted_ts_refs": manifest.get("accepted_ts_refs", []),
        },
        "hypothesis_context": _build_hypothesis_context(mechanism, evidence),
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


def _build_hypothesis_context(mechanism: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    focus_id = mechanism.get("focus_hypothesis_id")
    hypotheses = [item for item in mechanism.get("hypotheses", []) if isinstance(item, dict)]
    active = next((item for item in hypotheses if item.get("hypothesis_id") == focus_id), None)
    if active is None and hypotheses:
        active = hypotheses[-1]
        focus_id = active.get("hypothesis_id")
    prediction_status = active.get("prediction_status", []) if isinstance(active, dict) else []
    supported = _prediction_ids_by_verdict(prediction_status, "supported")
    refuted = _prediction_ids_by_verdict(prediction_status, "refuted")
    all_predictions = active.get("testable_predictions", []) if isinstance(active, dict) else []
    known_prediction_ids = supported | refuted | _prediction_ids_by_verdict(prediction_status, "inconclusive")
    open_predictions = [
        item for item in all_predictions
        if isinstance(item, dict) and item.get("prediction_id") not in known_prediction_ids
    ]
    evidence_roles = {
        item.get("role")
        for item in evidence.get("evidence", [])
        if isinstance(item, dict) and _evidence_matches_hypothesis(item, focus_id)
    }
    required_next = [
        role for role in (active.get("required_evidence", []) if isinstance(active, dict) else [])
        if role not in evidence_roles
    ]
    return {
        "focus_hypothesis_id": focus_id,
        "active_hypothesis": active or {},
        "open_predictions": open_predictions,
        "supported_predictions": sorted(supported),
        "refuted_predictions": sorted(refuted),
        "required_next_evidence": required_next,
    }


def _prediction_ids_by_verdict(rows: list[Any], verdict: str) -> set[str]:
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("claim_verdict") != verdict:
            continue
        out.update(str(item) for item in row.get("prediction_ids", []) if item)
    return out


def _evidence_matches_hypothesis(record: dict[str, Any], hypothesis_id: Any) -> bool:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    return bool(hypothesis_id and quality.get("hypothesis_id") == hypothesis_id)
