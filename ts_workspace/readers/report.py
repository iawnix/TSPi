"""LLM-facing workspace report builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import compact_id_time, read_json, write_json
from ..validators.workspace import validate_workspace

PATHWAY_AUDIT_PHASE = "pathway_audit"


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
    claim_prediction_status = _claim_prediction_rows(prediction_status)
    supported = _prediction_ids_by_verdict(claim_prediction_status, "supported")
    refuted = _prediction_ids_by_verdict(claim_prediction_status, "refuted")
    all_predictions = active.get("testable_predictions", []) if isinstance(active, dict) else []
    known_prediction_ids = supported | refuted | _prediction_ids_by_verdict(claim_prediction_status, "inconclusive")
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
        "pathway_audits": _pathway_audit_summaries(prediction_status, evidence),
    }


def _claim_prediction_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Rows whose verdict directly evaluates the referenced prediction."""
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("phase") != PATHWAY_AUDIT_PHASE
    ]


def _pathway_audit_summaries(rows: list[Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_records = evidence.get("evidence", []) if isinstance(evidence, dict) else []
    summaries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("phase") != PATHWAY_AUDIT_PHASE:
            continue
        outcome = _pathway_audit_outcome(row, evidence_records)
        item = {
            "node_id": row.get("node_id"),
            "claim_verdict": row.get("claim_verdict"),
            "prediction_ids": [str(item) for item in row.get("prediction_ids", []) if item],
            "evidence_refs": [str(item) for item in row.get("evidence_refs", []) if item],
            "audit_outcome": outcome,
        }
        if outcome in {"pathway_not_accepted", "not_accepted"}:
            item["recommended_next_action"] = "start_new_branch"
        summaries.append(item)
    return summaries


def _pathway_audit_outcome(row: dict[str, Any], evidence_records: list[Any]) -> str | None:
    evidence_refs = set(str(item) for item in row.get("evidence_refs", []) if item)
    for record in evidence_records:
        if not isinstance(record, dict) or str(record.get("evidence_id")) not in evidence_refs:
            continue
        quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
        facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
        decision = str(quality.get("strict_pathway_decision") or quality.get("audit_outcome") or "").lower()
        if not decision:
            decision = str(facts.get("strict_pathway_decision") or facts.get("audit_outcome") or facts.get("verdict") or "").lower()
        if decision == "not_accepted":
            return "pathway_not_accepted"
        if decision:
            return decision
        if quality.get("strict_pathway_supported") is False or facts.get("whole_R_to_P_pathway_accepted") is False:
            return "pathway_not_accepted"
    if row.get("claim_verdict") == "supported":
        return "audit_supported"
    return None


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
