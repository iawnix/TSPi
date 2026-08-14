"""Read-only v3 workspace projection for the web explorer."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ts_workspace.evidence_v3 import EvidenceStateError, evidence_view
from ts_workspace.io import read_json
from ts_workspace.operational import operational_snapshot
from ts_workspace.state_v3 import CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE, RESEARCH_STATE_FILE
from ts_workspace.validator_v3 import validate_workspace


def normalize_workspace(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    """Project canonical v3 state and separate operational state without deriving strategy."""

    root = Path(source_root).resolve()
    validation = validate_workspace(root)
    research = _read_object(root / RESEARCH_STATE_FILE)
    claims_registry = _read_object(root / CLAIMS_FILE)
    evidence_registry = _read_object(root / EVIDENCE_FILE)
    gate_registry = _read_object(root / GATE_RESULTS_FILE)
    evidence_records = _objects(evidence_registry.get("evidence"))
    evidence_states = _evidence_states(evidence_records, _objects(evidence_registry.get("events")))
    operations = operational_snapshot(root)
    agent_runs = operations["agent_runs"]
    nodes = [
        _normalize_node(root, row, agent_runs)
        for row in _objects(research.get("nodes"))
    ]
    branch_events = [
        _normalize_branch_event(event)
        for event in _objects(research.get("branch_events"))
    ]
    claims = _objects(claims_registry.get("claims"))
    gates = _objects(gate_registry.get("gate_results"))
    return {
        "schema_version": "ts-web-workspace/3",
        "label": label or root.name,
        "source_root": str(root),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "open_nodes": _strings(research.get("open_nodes")),
            "focus_claim_refs": _strings(claims_registry.get("focus_claim_refs")),
            "accepted_refs": _strings(research.get("accepted_refs")),
        },
        "nodes": nodes,
        "edges": _objects(research.get("edges")),
        "branch_events": branch_events,
        "branch_edges": branch_events,
        "decision_events": _normalize_decision_events(root / "decision_log.jsonl"),
        "claims": claims,
        "gate_results": gates,
        "evidence": [
            {**record, "state": evidence_states.get(str(record.get("evidence_id")), "unknown")}
            for record in evidence_records
        ],
        "operational_revision": operations["operational_revision"],
        "operational_summary": operations["operational_summary"],
        "pending_controls": operations["pending_controls"],
        "unresolved_controls": operations["unresolved_controls"],
        "agent_runs": agent_runs,
    }


def explorer_job_payload(
    source_root: str | Path,
    *,
    label: str | None = None,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    view = normalize_workspace(root, label=label)
    graph = explorer_graph_payload_from_view(view)
    return {
        "app": "TS Research Explorer",
        "source": str(root),
        "research_state": _read_object(root / RESEARCH_STATE_FILE),
        "research": _research_summary(view),
        "evidence_summary": graph["evidence_summary"],
        "graph": graph,
        "workspace": explorer_workspace_summary(workspace or {}, view=view),
        "read_only": True,
    }


def explorer_workspace_summary(
    row: dict[str, Any],
    *,
    view: dict[str, Any] | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    source_root = str(row.get("source_root") or row.get("source") or "")
    label = str(row.get("label") or row.get("name") or (Path(source_root).name if source_root else ""))
    workspace_id = str(row.get("workspace_id") or row.get("id") or "")
    if view is None and source_root:
        view = normalize_workspace(source_root, label=label)
    focus = view.get("focus", {}) if isinstance(view, dict) else {}
    accepted_refs = _strings(focus.get("accepted_refs"))
    claims = _objects(view.get("claims")) if isinstance(view, dict) else []
    focus_claims = set(_strings(focus.get("focus_claim_refs")))
    focused = [claim for claim in claims if claim.get("claim_id") in focus_claims]
    statuses = sorted({str(claim.get("status")) for claim in focused if claim.get("status")})
    claim_state = "accepted" if accepted_refs else (", ".join(statuses) if statuses else "unfocused")
    return {
        **row,
        "id": workspace_id,
        "workspace_id": workspace_id,
        "name": label or workspace_id,
        "label": label or workspace_id,
        "source": source_root,
        "source_root": source_root,
        "system": Path(source_root).name if source_root else "",
        "claim_state": claim_state,
        "accepted_refs": accepted_refs,
        "focus_claim_refs": sorted(focus_claims),
        "open_nodes": _strings(focus.get("open_nodes")),
    }


def explorer_graph_payload(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    return explorer_graph_payload_from_view(normalize_workspace(source_root, label=label))


def explorer_graph_payload_from_view(view: dict[str, Any]) -> dict[str, Any]:
    nodes = [_explorer_node(row) for row in _objects(view.get("nodes"))]
    edges = _explorer_edges(nodes, _objects(view.get("edges")))
    evidence = _explorer_evidence(_objects(view.get("evidence")))
    claims = _objects(view.get("claims"))
    gates = _objects(view.get("gate_results"))
    focus = view.get("focus", {}) if isinstance(view.get("focus"), dict) else {}
    return {
        "schema": "ts-explorer-graph/3",
        "nodes": nodes,
        "edges": edges,
        "events": [*_objects(view.get("branch_events")), *_objects(view.get("decision_events"))],
        "frontier_nodes": [node["id"] for node in nodes if node.get("frontier")],
        "accepted_refs": _strings(focus.get("accepted_refs")),
        "focus_claim_refs": _strings(focus.get("focus_claim_refs")),
        "claims": claims,
        "gate_results": gates,
        "validation": {
            "valid": bool(view.get("valid")),
            "findings": _list(view.get("validation_findings")),
        },
        "evidence_summary": evidence["summary"],
        "evidence": {"records": evidence["records"]},
        "operational_revision": view.get("operational_revision"),
        "operational_summary": view.get("operational_summary", {}),
        "agent_runs": _objects(view.get("agent_runs")),
        "presentation": _explorer_presentation(),
    }


def explorer_node_payload(source_root: str | Path, node_id: str, *, label: str | None = None) -> dict[str, Any]:
    root = Path(source_root).resolve()
    view = normalize_workspace(root, label=label)
    graph = explorer_graph_payload_from_view(view)
    node = next((item for item in graph["nodes"] if item.get("id") == node_id), None)
    if node is None:
        raise ValueError(f"unknown node id: {node_id}")
    detail = _read_object(root / "nodes" / node_id / "node.json")
    node_dir = root / "nodes" / node_id
    evidence = [
        record
        for record in graph["evidence"]["records"]
        if record.get("node_id") == node_id
    ]
    gate_ids = set(_strings(detail.get("gate_result_refs")))
    gates = [row for row in graph["gate_results"] if row.get("gate_result_id") in gate_ids]
    claim_ids = set(_strings(detail.get("claim_refs")))
    claims = [row for row in graph["claims"] if row.get("claim_id") in claim_ids]
    return {
        "node_id": node_id,
        "node": {**detail, **node, "node_id": node_id},
        "markdown": {
            "decision": _read_text(node_dir / "decision.md"),
            "reflection": _render_result(detail),
            "report": _read_text(node_dir / "report.md"),
        },
        "claims": claims,
        "gate_results": gates,
        "evidence": evidence,
        "files": list_node_files(root, node_id),
    }


def list_node_files(source_root: str | Path, node_id: str) -> dict[str, Any]:
    root = Path(source_root).resolve()
    node_dir = root / "nodes" / node_id
    if not node_dir.is_dir() or node_dir.is_symlink():
        return {"node_id": node_id, "files": []}
    files: list[dict[str, Any]] = []
    for path in sorted(node_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "name": path.name,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            }
        )
    return {"node_id": node_id, "files": files}


def _normalize_node(root: Path, row: dict[str, Any], agent_runs: list[dict[str, Any]]) -> dict[str, Any]:
    node_id = str(row.get("node_id") or "")
    detail = _read_object(root / "nodes" / node_id / "node.json") if node_id else {}
    state = str(detail.get("state") or row.get("state") or "unknown")
    result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
    outcome = result.get("outcome") or row.get("outcome")
    label, tone = _node_display(state, outcome)
    tags = _strings(detail.get("tags", row.get("tags")))
    runs = [run for run in agent_runs if node_id in _strings(run.get("node_ids"))]
    return {
        "node_id": node_id,
        "parent_node": detail.get("parent_node", row.get("parent_node")),
        "objective": detail.get("objective", row.get("objective")),
        "state": state,
        "tags": tags,
        "stage": tags[0] if tags else "research",
        "claim_refs": _strings(detail.get("claim_refs")),
        "operation_refs": _strings(detail.get("operation_refs")),
        "evidence_refs": _strings(detail.get("evidence_refs")),
        "gate_result_refs": _strings(detail.get("gate_result_refs")),
        "result": result or None,
        "calculations": _normalize_calculations(root, node_id),
        "agent_runs": runs,
        "display": {"label": label, "tone": tone, "outcome": outcome},
    }


def _explorer_node(row: dict[str, Any]) -> dict[str, Any]:
    calculations = _objects(row.get("calculations"))
    runs = _objects(row.get("agent_runs"))
    latest_calculation = calculations[-1] if calculations else {}
    latest_run = runs[-1] if runs else {}
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    tags = _strings(row.get("tags"))
    state = str(row.get("state") or "unknown")
    label = str(display.get("label") or state)
    return {
        "id": row.get("node_id"),
        "node_id": row.get("node_id"),
        "parent_id": row.get("parent_node"),
        "objective": row.get("objective"),
        "state": state,
        "tags": tags,
        "stage_label": " / ".join(tags[:2]) if tags else "Research",
        "card_label": label,
        "card_line": label,
        "card_color": _tone_color(str(display.get("tone") or "neutral")),
        "color": _tone_color(str(display.get("tone") or "neutral")),
        "node_state": state,
        "state_label": label,
        "state_line": _result_line(row.get("result")),
        "outcome": display.get("outcome"),
        "claim_refs": _strings(row.get("claim_refs")),
        "operation_refs": _strings(row.get("operation_refs")),
        "evidence_refs": _strings(row.get("evidence_refs")),
        "gate_result_refs": _strings(row.get("gate_result_refs")),
        "evidence_count": len(_strings(row.get("evidence_refs"))),
        "gate_result_count": len(_strings(row.get("gate_result_refs"))),
        "calculations": calculations,
        "calculation_count": len(calculations),
        "calculation_state": latest_calculation.get("state"),
        "calculation_program_status": latest_calculation.get("program_status"),
        "agent_runs": runs,
        "agent_run_count": len(runs),
        "agent_run_status": latest_run.get("status"),
        "agent_run_role": latest_run.get("role"),
        "active": state == "open",
        "frontier": state == "open",
    }


def _normalize_calculations(root: Path, node_id: str) -> list[dict[str, Any]]:
    paths = {
        *root.glob(f"nodes/{node_id}/attempts/*/outputs/calculation_result.json"),
        *root.glob(f"nodes/{node_id}/outputs/calculations/*/calculation_result.json"),
        *root.glob(f"nodes/{node_id}/remote/calculations/*/status.json"),
    }
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            continue
        value = _read_object(path)
        rows.append({**value, "ref": path.relative_to(root).as_posix()})
    return rows


def _explorer_edges(nodes: list[dict[str, Any]], tree_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {str(node.get("id")) for node in nodes}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in tree_edges:
        source = str(edge.get("parent_node") or "")
        target = str(edge.get("child_node") or "")
        key = (source, target)
        if not source or not target or source not in known or target not in known or key in seen:
            continue
        seen.add(key)
        rows.append({"id": f"edge:{source}:{target}", "source": source, "target": target, "kind": "branch"})
    return rows


def _explorer_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    states: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for record in records:
        state = str(record.get("state") or "unknown")
        tier = str(record.get("evidence_tier") or "unknown")
        states[state] = states.get(state, 0) + 1
        tiers[tier] = tiers.get(tier, 0) + 1
    return {"summary": {"total": len(records), "states": states, "tiers": tiers}, "records": records}


def _research_summary(view: dict[str, Any]) -> dict[str, Any]:
    claims = _objects(view.get("claims"))
    gates = _objects(view.get("gate_results"))
    evidence = _objects(view.get("evidence"))
    focus_refs = _strings(view.get("focus", {}).get("focus_claim_refs"))
    focus_set = set(focus_refs)
    open_questions = [
        question
        for node in _objects(view.get("nodes"))
        for question in _strings((node.get("result") or {}).get("open_questions") if isinstance(node.get("result"), dict) else [])
    ]
    return {
        "focus_claim_refs": focus_refs,
        "accepted_refs": _strings(view.get("focus", {}).get("accepted_refs")),
        "claim_counts": _count_by(claims, "status"),
        "gate_counts": _count_by(gates, "verdict"),
        "active_evidence_count": sum(1 for row in evidence if row.get("state") == "active"),
        "focus_claims": [
            f"{claim.get('claim_id')}: {claim.get('status')} - {claim.get('statement')}"
            for claim in claims
            if claim.get("claim_id") in focus_set
        ],
        "gate_lines": [
            f"{gate.get('gate_result_id')}: {gate.get('gate')} = {gate.get('verdict')}"
            for gate in gates
        ],
        "evidence_lines": [
            f"{row.get('evidence_id')}: {row.get('state')} - {row.get('summary')}"
            for row in evidence
        ],
        "open_questions": open_questions,
        "claims": claims,
        "gate_results": gates,
    }


def _evidence_states(records: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, str]:
    try:
        return evidence_view(records, events).state_by_id
    except EvidenceStateError:
        return {str(row.get("evidence_id")): "invalid" for row in records}


def _normalize_branch_event(event: dict[str, Any]) -> dict[str, Any]:
    node_id = str(event.get("node_id") or "")
    parent = event.get("parent_node")
    return {
        "event_id": f"branch:{node_id}",
        "event_role": "node_created",
        "node_id": node_id,
        "new_node": node_id,
        "parent_node": parent,
        "from_node": parent,
        "decision_id": event.get("decision_id"),
        "created_at": event.get("created_at"),
    }


def _normalize_decision_events(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _read_jsonl(path):
        rows.append(
            {
                "event_id": f"decision:{item.get('decision_id')}",
                "event_role": "decision",
                "decision_id": item.get("decision_id"),
                "action": item.get("action"),
                "created_at": item.get("created_at"),
                "result": item.get("result"),
            }
        )
    return rows


def _node_display(state: str, outcome: Any) -> tuple[str, str]:
    if state == "open":
        return "open", "active"
    if state == "stopped":
        return "stopped", "stopped"
    if outcome == "completed":
        return "completed", "supported"
    if outcome == "inconclusive":
        return "inconclusive", "inconclusive"
    if outcome == "blocked":
        return "blocked", "failed"
    return state, "neutral"


def _tone_color(tone: str) -> str:
    return {
        "active": "blue",
        "supported": "green",
        "inconclusive": "amber",
        "failed": "red",
        "stopped": "gray",
    }.get(tone, "gray")


def _result_line(value: Any) -> str:
    if not isinstance(value, dict):
        return "No node result recorded."
    parts = [str(value.get("summary") or "").strip()]
    questions = _strings(value.get("open_questions"))
    if questions:
        parts.append(f"{len(questions)} open question(s)")
    return " | ".join(part for part in parts if part) or str(value.get("outcome") or "closed")


def _render_result(node: dict[str, Any]) -> str:
    result = node.get("result") if isinstance(node.get("result"), dict) else None
    if result is None:
        return ""
    lines = ["# Node Result", "", f"- State: {node.get('state')}", f"- Outcome: {result.get('outcome')}", ""]
    if result.get("summary"):
        lines.extend([str(result["summary"]), ""])
    updates = _objects(result.get("claim_updates"))
    if updates:
        lines.extend(["## Claim Updates", ""])
        for update in updates:
            lines.append(f"- {update.get('claim_ref')}: {update.get('verdict')} - {update.get('summary')}")
        lines.append("")
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else None
    if audit:
        lines.extend(["## Audit", "", f"- {audit.get('policy')}: {audit.get('verdict')}", "", str(audit.get("summary") or ""), ""])
    return "\n".join(lines).rstrip() + "\n"


def _explorer_presentation() -> dict[str, Any]:
    return {
        "edge_kind": {"branch": {"label": "lineage", "color": "gray"}},
        "event_role": {
            "node_created": {"label": "node created", "color": "blue"},
            "decision": {"label": "decision", "color": "gray"},
        },
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else ""
    except OSError:
        return ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _objects(value: Any) -> list[dict[str, Any]]:
    return [item for item in _list(value) if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _list(value) if isinstance(item, str)]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
