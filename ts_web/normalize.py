"""Read-only workspace normalization for the web explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.io import read_json
from ts_workspace.validators.workspace import validate_workspace


def normalize_workspace(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    root = Path(source_root).resolve()
    validation = validate_workspace(root)
    tree = _read_json(root / "tree.json")
    manifest = _read_json(root / "manifest.json")
    evidence_registry = _read_json(root / "evidence_registry.json")
    pathway_model = _read_json(root / "pathway_model.json")
    mechanism_model = _read_json(root / "mechanism_model.json")

    nodes = [_normalize_node(root, row) for row in _list(tree.get("nodes"))]
    backtrack_events = _list(tree.get("backtrack_events"))
    return {
        "label": label or root.name,
        "source_root": str(root),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "current_node": tree.get("current_node"),
            "focus_pathway_id": pathway_model.get("focus_pathway_id"),
            "accepted_ts_refs": manifest.get("accepted_ts_refs", []),
        },
        "nodes": nodes,
        "edges": _list(tree.get("edges")),
        "backtrack_edges": [_normalize_backtrack_event(event) for event in backtrack_events],
        "pathways": _list(pathway_model.get("pathways")),
        "evidence": _list(evidence_registry.get("evidence")),
        "mechanism": {
            "accepted_facts": _list(mechanism_model.get("accepted_facts")),
            "refuted_hypotheses": _list(mechanism_model.get("refuted_hypotheses")),
            "open_questions": _list(mechanism_model.get("open_questions")),
        },
    }


def _normalize_node(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    node_id = row.get("node_id")
    detail = _read_json(root / "nodes" / str(node_id) / "node.json") if node_id else {}
    lifecycle = detail.get("lifecycle") or row.get("lifecycle")
    closure = detail.get("closure")
    claim_verdict = row.get("claim_verdict") or (closure or {}).get("claim_verdict")
    program_status = row.get("program_status") or (closure or {}).get("program_status")
    return {
        "node_id": node_id,
        "parent_node": detail.get("parent_node", row.get("parent_node")),
        "phase": detail.get("phase", row.get("phase")),
        "lifecycle": lifecycle,
        "hypothesis": detail.get("hypothesis", row.get("hypothesis")),
        "pathway_ref": detail.get("pathway_ref"),
        "evidence_refs": detail.get("evidence_refs", []),
        "closure": closure,
        "display": {
            "label": _display_label(lifecycle, claim_verdict),
            "tone": _display_tone(lifecycle, claim_verdict, program_status),
            "program_status": program_status,
            "claim_verdict": claim_verdict,
        },
    }


def _normalize_backtrack_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "event_state": event.get("event_state"),
        "from_node": event.get("from_node"),
        "to_node": event.get("to_node"),
        "new_branch_node": event.get("new_branch_node"),
        "changed_variable": event.get("changed_variable"),
        "reason_code": event.get("reason_code"),
        "evidence_refs": event.get("evidence_refs", []),
    }


def _display_label(lifecycle: str | None, claim_verdict: str | None) -> str:
    if lifecycle == "running":
        return "running"
    if lifecycle == "stopped":
        return "stopped"
    return claim_verdict or lifecycle or "unknown"


def _display_tone(lifecycle: str | None, claim_verdict: str | None, program_status: str | None) -> str:
    if lifecycle == "running":
        return "active"
    if program_status in {"failed", "stopped"}:
        return "blocked"
    if claim_verdict == "supported":
        return "supported"
    if claim_verdict == "refuted":
        return "refuted"
    if claim_verdict == "inconclusive":
        return "inconclusive"
    return "neutral"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
