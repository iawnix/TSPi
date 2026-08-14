"""Validated v3 report context assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.evidence_v3 import evidence_view
from ts_workspace.io import read_json
from ts_workspace.operational import operational_snapshot
from ts_workspace.revision_v3 import workspace_revision_from_documents
from ts_workspace.state_v3 import CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE, RESEARCH_STATE_FILE
from ts_workspace.validator_v3 import validate_workspace


def collect_report_context(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    validation = validate_workspace(root_path)
    if not validation["valid"]:
        errors = "; ".join(
            item["message"] for item in validation["findings"] if item["severity"] == "error"
        )
        raise ValueError(f"workspace is invalid: {errors}")
    research = read_json(root_path / RESEARCH_STATE_FILE)
    claims = read_json(root_path / CLAIMS_FILE)
    evidence = read_json(root_path / EVIDENCE_FILE)
    gates = read_json(root_path / GATE_RESULTS_FILE)
    view = evidence_view(evidence["evidence"], evidence["events"])
    nodes = []
    for row in research["nodes"]:
        node = read_json(root_path / "nodes" / row["node_id"] / "node.json")
        nodes.append(node)
    accepted = [read_json(root_path / ref) for ref in research["accepted_refs"]]
    operations = operational_snapshot(root_path)
    return {
        "schema_version": "ts-report-context/3",
        "workspace_root": str(root_path),
        "workspace_revision": workspace_revision_from_documents(research, claims, evidence, gates),
        "focus_claim_refs": list(claims["focus_claim_refs"]),
        "claims": list(claims["claims"]),
        "gate_results": list(gates["gate_results"]),
        "evidence_records": list(view.active_records),
        "evidence_states": dict(view.state_by_id),
        "nodes": nodes,
        "branch_events": list(research["branch_events"]),
        "accepted_refs": list(research["accepted_refs"]),
        "accepted_artifacts": accepted,
        "operational_summary": operations["operational_summary"],
        "unresolved_controls": operations["unresolved_controls"],
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "validation_findings": validation["findings"],
    }


def node_label(node: dict[str, Any]) -> str:
    tags = ", ".join(str(value) for value in node.get("tags", []))
    return tags or "untagged"


def node_program_outcome(node: dict[str, Any]) -> str:
    result = node.get("result") if isinstance(node.get("result"), dict) else {}
    return str(result.get("outcome") or "pending")


def node_scientific_status(node: dict[str, Any]) -> str:
    return str(node.get("state") or "unknown")
