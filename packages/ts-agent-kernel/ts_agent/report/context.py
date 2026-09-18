"""Canonical ResearchMap input for report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ts_agent.analysis.projection import analysis_projection
from ts_agent.compute.artifacts import list_calculation_artifacts
from ts_agent.io import sha256_json
from ts_agent.research import ResearchKernel, ResearchKernelError
from ts_agent.workspace.operational import operational_snapshot
from ts_agent.workspace.path_safety import lexical_path, path_has_symlink
from ts_agent.workspace.validator import validate_workspace


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
    validation = validate_workspace(root_path)
    if not validation["valid"]:
        messages = "; ".join(
            item["message"]
            for item in validation["findings"]
            if item.get("severity") == "error"
        )
        raise ValueError(f"workspace is invalid: {messages or 'unknown validation failure'}")
    try:
        research_map = ResearchKernel(root_path).load()
    except ResearchKernelError as exc:
        raise ValueError(str(exc)) from exc

    map_document = research_map.to_dict()
    workspace_revision = sha256_json(map_document)
    operations = operational_snapshot(root_path, exclude_activity_refs=exclude_activity_refs)
    analyses = analysis_projection(root_path)
    artifact_catalog = list_calculation_artifacts(root_path).get("artifacts", [])

    return {
        "schema_version": "ts-report-context/6",
        "workspace_root": str(root_path),
        "workspace_id": research_map.map_id,
        "map_id": research_map.map_id,
        "title": research_map.title,
        "created_at": research_map.created_at,
        "workspace_revision": workspace_revision,
        "operational_revision": operations["operational_revision"],
        "report_id": "rep_" + workspace_revision.removeprefix("sha256:")[:16],
        "research_map": map_document,
        "focus": {
            "claim_ids": list(research_map.focus_claim_ids),
            "node_ids": list(research_map.focus_node_ids),
        },
        "phases": map_document["phases"],
        "claims": map_document["claims"],
        "claim_relations": map_document["claim_relations"],
        "nodes": map_document["nodes"],
        "findings": map_document["findings"],
        "gates": map_document["gates"],
        "progress": map_document["progress"],
        "deterministic_activities": operations["deterministic_activities"],
        "activity_summaries": operations["activity_summaries"],
        "node_dispatch": operations.get("node_dispatch", []),
        "activity_integrity_findings": operations["activity_integrity_findings"],
        "operational_integrity_findings": operations.get("operational_integrity_findings", []),
        "calculation_attempt_integrity_findings": operations.get(
            "calculation_attempt_integrity_findings", []
        ),
        "excluded_activity_refs": operations["excluded_activity_refs"],
        "operational_summary": operations["operational_summary"],
        "unresolved_controls": operations["unresolved_controls"],
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "validation_findings": validation["findings"],
        "scientific_analyses": analyses,
        "artifacts": artifact_catalog,
    }
