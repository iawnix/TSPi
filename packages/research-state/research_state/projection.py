"""Canonical read projections for the filesystem Research State.

Transports may wrap these documents, but they must not rebuild a second
ResearchMap shape.  Keeping the projection here makes the CLI, Web provider,
and other Python callers consume the same field names and revision semantics.
"""

from __future__ import annotations

import copy
from typing import Any


def research_map_document(context: dict[str, Any]) -> dict[str, Any]:
    """Project a canonical ``research_map_context_1`` document to ResearchMap."""

    focus = context.get("focus") if isinstance(context.get("focus"), dict) else {}
    map_id = context.get("map_id") or f"map_{context.get('workspace_id', '')}"
    created_at = context.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("research context created_at is required")
    collections = ("phases", "claims", "nodes", "findings", "gates", "lifecycle_actions", "claim_relations")
    if any(not isinstance(context.get(name), list) for name in collections):
        raise ValueError("research context collections are invalid")
    if not isinstance(focus.get("claim_ids"), list) or not isinstance(focus.get("node_ids"), list):
        raise ValueError("research context focus is invalid")
    phases = copy.deepcopy(context["phases"])
    claims = copy.deepcopy(context["claims"])
    nodes = copy.deepcopy(context["nodes"])
    findings = copy.deepcopy(context["findings"])
    gates = copy.deepcopy(context["gates"])
    return {
        "schema_version": "research-map/1",
        "map_id": str(map_id),
        "title": str(context.get("title") or context.get("workspace_id") or map_id),
        "created_at": created_at,
        "revision": context.get("revision", 0),
        "phases": phases,
        "claims": claims,
        "nodes": nodes,
        "findings": findings,
        "gates": gates,
        "lifecycle_actions": copy.deepcopy(context["lifecycle_actions"]),
        "claim_relations": copy.deepcopy(context["claim_relations"]),
        "focus_claim_ids": list(focus["claim_ids"]),
        "focus_node_ids": list(focus["node_ids"]),
        "metadata": copy.deepcopy(context.get("metadata", {})) if isinstance(context.get("metadata"), dict) else {},
        "progress": {
            "phase_count": len(phases),
            "claim_count": len(claims),
            "node_count": len(nodes),
            "finding_count": len(findings),
            "gate_count": len(gates),
            "closed_node_count": sum(item.get("state") == "closed" for item in nodes if isinstance(item, dict)),
            "open_issue_count": sum(item.get("kind") == "issue" and item.get("status") == "open" for item in findings if isinstance(item, dict)),
        },
    }


def research_summary_document(context: dict[str, Any]) -> dict[str, Any]:
    """Project the bounded summary returned by ``research.summary``."""

    phases = copy.deepcopy(context.get("phases", []))
    claims = copy.deepcopy(context.get("claims", []))
    nodes = copy.deepcopy(context.get("nodes", []))
    findings = copy.deepcopy(context.get("findings", []))
    gates = copy.deepcopy(context.get("gates", []))
    return {
        "schema_version": "research-summary/1",
        "mode": "summary",
        "map_id": context.get("map_id") or f"map_{context.get('workspace_id', '')}",
        "workspace_id": context.get("workspace_id"),
        "workspace_mode": context.get("workspace_mode"),
        "revision": context.get("revision", 0),
        "lifecycle_state": context.get("lifecycle_state"),
        "phases": phases,
        "claims": claims,
        "nodes": nodes,
        "findings": findings,
        "gates": gates,
        "focus": copy.deepcopy(context.get("focus", {"claim_ids": [], "node_ids": []})),
        "progress": {
            "phase_count": len(phases),
            "claim_count": len(claims),
            "node_count": len(nodes),
            "finding_count": len(findings),
            "gate_count": len(gates),
            "closed_node_count": sum(item.get("state") == "closed" for item in nodes if isinstance(item, dict)),
            "open_issue_count": sum(item.get("kind") == "issue" and item.get("status") == "open" for item in findings if isinstance(item, dict)),
        },
    }


__all__ = ["research_map_document", "research_summary_document"]
