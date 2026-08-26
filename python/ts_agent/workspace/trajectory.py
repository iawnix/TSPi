"""Read-only Phase and ResearchNode narrative projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ts_agent.io import read_json
from .refs import DECISION_ID, node_sort_key, phase_sort_key


def project_research_trajectory(
    root: str | Path,
    phases: Iterable[dict[str, Any]],
    nodes: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Join Nodes to their opening and completion Decisions without mutating state."""

    root_path = Path(root).expanduser().resolve()
    phase_rows = sorted(
        (dict(row) for row in phases if isinstance(row, dict)),
        key=lambda row: phase_sort_key(str(row.get("phase_id") or "")),
    )
    node_rows = sorted(
        (dict(row) for row in nodes if isinstance(row, dict)),
        key=lambda row: node_sort_key(str(row.get("node_id") or "")),
    )
    decision_refs = {
        ref
        for node in node_rows
        for ref in (
            node.get("created_by_decision"),
            (node.get("result") or {}).get("decision_id")
            if isinstance(node.get("result"), dict)
            else None,
        )
        if isinstance(ref, str)
    }
    decision_refs.update(
        str(phase["created_by_decision"])
        for phase in phase_rows
        if isinstance(phase.get("created_by_decision"), str)
    )
    decisions = {
        decision_ref: summary
        for decision_ref in decision_refs
        if (summary := _decision_summary(root_path, decision_ref)) is not None
    }
    dependents: dict[str, list[str]] = {
        str(node.get("node_id") or ""): []
        for node in node_rows
        if isinstance(node.get("node_id"), str)
    }
    for node in node_rows:
        node_id = str(node.get("node_id") or "")
        for dependency_ref in _strings(node.get("dependency_refs")):
            if dependency_ref in dependents:
                dependents[dependency_ref].append(node_id)

    projected_nodes = [
        {
            "node_id": node.get("node_id"),
            "phase_ref": node.get("phase_ref"),
            "title": node.get("title"),
            "objective": node.get("objective"),
            "deliverable": node.get("deliverable"),
            "status": node.get("status"),
            "dependency_refs": _strings(node.get("dependency_refs")),
            "dependent_refs": sorted(
                dependents.get(str(node.get("node_id") or ""), []),
                key=node_sort_key,
            ),
            "primary_claim_ref": node.get("primary_claim_ref"),
            "claim_refs": _strings(node.get("claim_refs")),
            "opening_decision": decisions.get(str(node.get("created_by_decision") or "")),
            "outcome": dict(node["result"]) if isinstance(node.get("result"), dict) else None,
            "completion_decision": decisions.get(
                str((node.get("result") or {}).get("decision_id") or "")
                if isinstance(node.get("result"), dict)
                else ""
            ),
        }
        for node in node_rows
    ]
    projected_by_phase: dict[str, list[dict[str, Any]]] = {}
    for node in projected_nodes:
        projected_by_phase.setdefault(str(node.get("phase_ref") or ""), []).append(node)
    return {
        "schema_version": "ts-research-trajectory/1",
        "phases": [
            {
                "phase_id": phase.get("phase_id"),
                "title": phase.get("title"),
                "objective": phase.get("objective"),
                "created_at": phase.get("created_at"),
                "opening_decision": decisions.get(str(phase.get("created_by_decision") or "")),
                "node_refs": [
                    str(node["node_id"])
                    for node in projected_by_phase.get(str(phase.get("phase_id") or ""), [])
                    if isinstance(node.get("node_id"), str)
                ],
            }
            for phase in phase_rows
        ],
        "nodes": projected_nodes,
    }


def _decision_summary(root: Path, decision_ref: str) -> dict[str, Any] | None:
    if DECISION_ID.fullmatch(decision_ref) is None:
        return None
    decisions_root = root / "decisions"
    if decisions_root.is_symlink() or not decisions_root.is_dir():
        return None
    path = decisions_root / f"{decision_ref}.json"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        decision = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(decision, dict) or decision.get("decision_id") != decision_ref:
        return None
    rationale = decision.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    return {
        "decision_id": decision_ref,
        "rationale": rationale,
        "basis_refs": _strings(decision.get("basis_refs")),
        "created_at": decision.get("created_at"),
    }


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
