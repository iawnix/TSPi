"""Canonical ResearchMap input for report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ts_agent.analysis.results import analysis_results
from ts_agent.compute.artifacts import list_calculation_artifacts
from ts_agent.io import sha256_json
from ts_agent.research.agent_workspace import AgentWorkspaceError, has_state_files, read_context
from ts_agent.workspace.operational import runtime_status
from ts_agent.path_safety import lexical_path, path_has_symlink


def collect_report_context(
    root: str | Path,
    *,
    exclude_activity_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Load one immutable report input directly from the ResearchKernel.

    The report is a consumer of the same map that TS Web and the public
    research commands return. It does not rebuild state from legacy registries.
    """

    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise ValueError(f"workspace root contains a symbolic link: {root_path}")
    if not has_state_files(root_path):
        raise ValueError(f"workspace is not an initialized research workspace: {root_path}")
    try:
        context = read_context(root_path)
    except AgentWorkspaceError as exc:
        raise ValueError(str(exc)) from exc

    # The filesystem ResearchMap context is authoritative.  Reports consume a
    # stable map-shaped projection so rendering remains independent of storage
    # details while retaining the canonical records and revision.
    map_document = {
        "schema_version": "research-map/1",
        "map_id": f"map_{context['workspace_id']}",
        "title": context.get("title") or "Research workspace",
        "revision": context.get("revision", 0),
        "phases": context.get("phases", []),
        "claims": context.get("claims", []),
        "claim_relations": context.get("claim_relations", []),
        "nodes": context.get("nodes", []),
        "findings": context.get("findings", []),
        "gates": context.get("gates", []),
        "focus_claim_ids": (context.get("focus") or {}).get("claim_ids", []),
        "focus_node_ids": (context.get("focus") or {}).get("node_ids", []),
    }
    workspace_revision = sha256_json(map_document)
    status = runtime_status(root_path, exclude_activity_refs=exclude_activity_refs)
    analyses = analysis_results(root_path)
    artifact_catalog = list_calculation_artifacts(root_path).get("artifacts", [])

    return {
        "schema_version": "ts-report-context/7",
        "workspace_root": str(root_path),
        "workspace_revision": workspace_revision,
        "report_id": "rep_" + workspace_revision.removeprefix("sha256:")[:16],
        "research_map": map_document,
        "runtime_status": status,
        "validation_findings": [],
        "analysis_results": analyses,
        "artifacts": artifact_catalog,
    }
