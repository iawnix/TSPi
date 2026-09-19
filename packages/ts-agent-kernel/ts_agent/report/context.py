"""Canonical ResearchMap input for report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ts_agent.analysis.results import analysis_results
from ts_agent.compute.artifacts import list_calculation_artifacts
from ts_agent.io import sha256_json
from ts_agent.research import ResearchKernel, ResearchKernelError
from ts_agent.workspace.operational import runtime_status
from ts_agent.path_safety import lexical_path, path_has_symlink
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
        "validation_findings": validation["findings"],
        "analysis_results": analyses,
        "artifacts": artifact_catalog,
    }
