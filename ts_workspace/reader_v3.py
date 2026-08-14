"""Read-only reports and claim-scoped review snapshots for workspace v3."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .evidence_v3 import EvidenceStateError, evidence_view
from .identity import IDENTITY_REF, WorkspaceIdentityError, read_workspace_identity
from .io import read_json, write_json
from .operational import operational_snapshot
from .revision_v3 import report_id_for_revision, workspace_revision_from_documents
from .state_v3 import CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE, RESEARCH_STATE_FILE
from .validator_v3 import validate_workspace


def report_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    validation = validate_workspace(root_path)
    research = _read_or_empty(root_path / RESEARCH_STATE_FILE)
    claims = _read_or_empty(root_path / CLAIMS_FILE)
    evidence = _read_or_empty(root_path / EVIDENCE_FILE)
    gates = _read_or_empty(root_path / GATE_RESULTS_FILE)
    revision = workspace_revision_from_documents(research, claims, evidence, gates)
    operations = operational_snapshot(root_path)
    try:
        identity = read_workspace_identity(root_path)
    except WorkspaceIdentityError:
        identity = {}

    evidence_rows = _dict_rows(evidence.get("evidence"))
    try:
        view = evidence_view(evidence_rows, _dict_rows(evidence.get("events")))
        active_evidence = view.active_records
        evidence_states: dict[str, int] = {}
        for state in view.state_by_id.values():
            evidence_states[state] = evidence_states.get(state, 0) + 1
    except EvidenceStateError:
        active_evidence = evidence_rows
        evidence_states = {"unresolved": len(evidence_rows)}

    nodes = _dict_rows(research.get("nodes"))
    open_nodes = [row for row in nodes if row.get("state") == "open"]
    claim_rows = _dict_rows(claims.get("claims"))
    gate_rows = _dict_rows(gates.get("gate_results"))
    focus_refs = list(claims.get("focus_claim_refs", []))
    focus_claims = [row for row in claim_rows if row.get("claim_id") in focus_refs]
    report = {
        "schema_version": "ts-workspace-report/3",
        "report_id": report_id_for_revision(revision),
        "workspace_id": identity.get("workspace_id"),
        "workspace_revision": revision,
        "operational_revision": operations["operational_revision"],
        "workspace_root": str(root_path),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "current_node": open_nodes[-1]["node_id"] if open_nodes else None,
            "open_node_refs": [row["node_id"] for row in open_nodes],
            "focus_claim_refs": focus_refs,
            "accepted_refs": list(research.get("accepted_refs", [])),
        },
        "focus_claims": [_claim_capsule(row) for row in focus_claims],
        "node_index": nodes,
        "open_nodes": open_nodes,
        "closed_node_count": sum(1 for row in nodes if row.get("state") in {"closed", "stopped"}),
        "claim_count": len(claim_rows),
        "claim_status_counts": _count_by(claim_rows, "status"),
        "evidence_count": len(active_evidence),
        "evidence_history_count": len(evidence_rows),
        "evidence_states": evidence_states,
        "gate_result_count": len(gate_rows),
        "gate_verdict_counts": _count_by(gate_rows, "verdict"),
        "branch_events": list(research.get("branch_events", [])),
        "accepted_refs": list(research.get("accepted_refs", [])),
        "agent_runs": operations["agent_runs"],
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "review_disposition_count": operations["review_disposition_count"],
        "pending_controls": operations["pending_controls"],
        "unresolved_controls": operations["unresolved_controls"],
        "ambiguous_submissions": operations["ambiguous_submissions"],
        "ambiguous_cancellations": operations["ambiguous_cancellations"],
        "retryable_controls": operations["retryable_controls"],
        "operational_summary": operations["operational_summary"],
        "workspace_state_refs": {
            "workspace_identity": IDENTITY_REF,
            "research_state": RESEARCH_STATE_FILE,
            "claims": CLAIMS_FILE,
            "evidence_registry": EVIDENCE_FILE,
            "gate_results": GATE_RESULTS_FILE,
        },
        "allowed_decision_actions": ["start_node", "update_workspace", "end_node", "ask_user", "stop"],
        "decision_contract": {
            "schema_version": "ts-decision/3",
            "requires_report_ref": ["start_node", "update_workspace", "end_node"],
            "mutation_channel": "ts_workspace",
            "strategy_authority": "root_agent",
        },
    }
    return report


def report_node(root: str | Path, node_id: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    research, claims, evidence, gates = _documents(root_path)
    node_path = root_path / "nodes" / node_id / "node.json"
    if not node_path.is_file():
        raise ValueError(f"unknown node: {node_id}")
    node = read_json(node_path)
    claim_refs = set(node.get("claim_refs", []))
    evidence_refs = set(node.get("evidence_refs", []))
    gate_refs = set(node.get("gate_result_refs", []))
    view = evidence_view(_dict_rows(evidence.get("evidence")), _dict_rows(evidence.get("events")))
    related_evidence = [
        row
        for row in view.active_records
        if row.get("node_id") == node_id or row.get("evidence_id") in evidence_refs
    ]
    operations = operational_snapshot(root_path)
    return {
        "schema_version": "ts-node-report/3",
        "workspace_root": str(root_path),
        "workspace_revision": workspace_revision_from_documents(research, claims, evidence, gates),
        "node": node,
        "lineage": _lineage(research, node_id),
        "claims": [_claim_capsule(row) for row in _dict_rows(claims.get("claims")) if row.get("claim_id") in claim_refs],
        "evidence": [_evidence_capsule(row, view.state_by_id) for row in related_evidence],
        "gate_results": [row for row in _dict_rows(gates.get("gate_results")) if row.get("gate_result_id") in gate_refs],
        "branch_event": next(
            (row for row in _dict_rows(research.get("branch_events")) if row.get("node_id") == node_id),
            None,
        ),
        "agent_runs": [row for row in operations["agent_runs"] if node_id in row.get("node_ids", [])],
        "artifact_paths": dict(node.get("artifacts", {})),
        "operation_refs": list(node.get("operation_refs", [])),
    }


def report_lineage_context(root: str | Path, from_node: str, anchor_node: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    research = read_json(root_path / RESEARCH_STATE_FILE)
    lineage = _lineage(research, from_node)
    if anchor_node not in lineage:
        raise ValueError(f"anchor node {anchor_node} is not an ancestor of {from_node}")
    delta_ids = lineage[lineage.index(anchor_node) + 1 :]
    return {
        "schema_version": "ts-lineage-context/1",
        "workspace_root": str(root_path),
        "from_node": report_node(root_path, from_node),
        "anchor_node": report_node(root_path, anchor_node),
        "path_delta": [report_node(root_path, node_id)["node"] for node_id in delta_ids],
        "decision_authority": "root_agent",
        "kernel_constraint": "parent_node must identify an existing node; tags do not select behavior",
    }


def build_review_snapshot(
    root: str | Path,
    *,
    target_claim_ref: str,
    node_ids: list[str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    research, claims, evidence, gates = _documents(root_path)
    claim_map = {row["claim_id"]: row for row in _dict_rows(claims.get("claims"))}
    target = claim_map.get(target_claim_ref)
    if target is None:
        raise ValueError(f"unknown review target claim: {target_claim_ref}")

    claim_refs = _claim_ancestry(claim_map, target_claim_ref)
    selected_claims = [claim_map[ref] for ref in claim_refs]
    evidence_refs: set[str] = set()
    gate_refs: set[str] = set()
    required_nodes = {str(row.get("created_in_node")) for row in selected_claims}
    for claim in selected_claims:
        evidence_refs.update(str(ref) for ref in claim.get("evidence_refs", []))
        gate_refs.update(str(ref) for ref in claim.get("gate_result_refs", []))
        for event in claim.get("history", []):
            if not isinstance(event, dict):
                continue
            required_nodes.add(str(event.get("node_id")))
            evidence_refs.update(str(ref) for ref in event.get("evidence_refs", []))
            gate_refs.update(str(ref) for ref in event.get("gate_result_refs", []))

    gate_rows = _dict_rows(gates.get("gate_results"))
    selected_gates = [
        row
        for row in gate_rows
        if row.get("gate_result_id") in gate_refs or row.get("target_ref") in claim_refs
    ]
    for result in selected_gates:
        gate_refs.add(str(result.get("gate_result_id")))
        required_nodes.add(str(result.get("node_id")))
        evidence_refs.update(str(ref) for ref in result.get("evidence_refs", []))

    view = evidence_view(_dict_rows(evidence.get("evidence")), _dict_rows(evidence.get("events")))
    selected_evidence = [row for row in view.records if row.get("evidence_id") in evidence_refs]
    required_nodes.update(str(row.get("node_id")) for row in selected_evidence)
    requested_nodes = set(node_ids or [])
    selected_node_ids = {value for value in required_nodes | requested_nodes if value and value != "None"}
    known_nodes = {row["node_id"] for row in _dict_rows(research.get("nodes"))}
    unknown_nodes = sorted(selected_node_ids - known_nodes)
    if unknown_nodes:
        raise ValueError("review snapshot references unknown nodes: " + ", ".join(unknown_nodes))

    revision = workspace_revision_from_documents(research, claims, evidence, gates)
    return {
        "schema_version": "ts-review-snapshot/1",
        "workspace_revision": revision,
        "target_claim_ref": target_claim_ref,
        "claims": selected_claims,
        "gate_results": selected_gates,
        "evidence": [_evidence_capsule(row, view.state_by_id) for row in selected_evidence],
        "nodes": [report_node(root_path, node_id)["node"] for node_id in sorted(selected_node_ids)],
        "dependency_refs": {
            "claim_refs": claim_refs,
            "gate_result_refs": sorted(gate_refs),
            "evidence_refs": sorted(evidence_refs),
            "node_refs": sorted(selected_node_ids),
        },
    }


def snapshot_report(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    report = report_workspace(root_path)
    path = root_path / "reports" / "snapshots" / f"{report['report_id']}.json"
    write_json(path, report)
    return {**report, "snapshot_ref": path.relative_to(root_path).as_posix()}


def _documents(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        read_json(root / RESEARCH_STATE_FILE),
        read_json(root / CLAIMS_FILE),
        read_json(root / EVIDENCE_FILE),
        read_json(root / GATE_RESULTS_FILE),
    )


def _read_or_empty(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _claim_capsule(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "claim_id",
            "parent_claim_id",
            "created_in_node",
            "kind",
            "statement",
            "status",
            "required_gates",
            "evidence_refs",
            "gate_result_refs",
        )
        if key in row
    }


def _evidence_capsule(row: dict[str, Any], states: dict[str, str]) -> dict[str, Any]:
    return {
        "evidence_id": row.get("evidence_id"),
        "node_id": row.get("node_id"),
        "kind": row.get("kind"),
        "evidence_tier": row.get("evidence_tier"),
        "summary": row.get("summary"),
        "facts": row.get("facts"),
        "artifact_refs": row.get("artifact_refs", []),
        "state": states.get(str(row.get("evidence_id")), "unknown"),
        "supersedes_evidence_id": row.get("supersedes_evidence_id"),
    }


def _lineage(research: dict[str, Any], node_id: str) -> list[str]:
    parents = {
        str(row.get("node_id")): row.get("parent_node")
        for row in _dict_rows(research.get("nodes"))
    }
    if node_id not in parents:
        raise ValueError(f"unknown node: {node_id}")
    lineage: list[str] = []
    current: str | None = node_id
    seen: set[str] = set()
    while current is not None:
        if current in seen:
            raise ValueError(f"node parent cycle detected at {current}")
        seen.add(current)
        lineage.append(current)
        parent = parents.get(current)
        current = str(parent) if parent is not None else None
    return list(reversed(lineage))


def _claim_ancestry(claims: dict[str, dict[str, Any]], claim_ref: str) -> list[str]:
    values: list[str] = []
    current: str | None = claim_ref
    seen: set[str] = set()
    while current is not None:
        if current in seen:
            raise ValueError(f"claim parent cycle detected at {current}")
        seen.add(current)
        claim = claims.get(current)
        if claim is None:
            raise ValueError(f"claim parent does not exist: {current}")
        values.append(current)
        parent = claim.get("parent_claim_id")
        current = str(parent) if parent is not None else None
    return list(reversed(values))
