"""Validated report projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ts_agent.workspace.acceptance import project_acceptances
from ts_agent.io import read_json
from ts_agent.workspace.operational import operational_snapshot
from ts_agent.workspace.revision import report_id_for_revision, workspace_revision_from_documents
from ts_agent.workspace.trajectory import project_research_trajectory
from ts_agent.workspace.state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    RESEARCH_PHASES_FILE,
    RESEARCH_NODES_FILE,
    RESEARCH_STATE_FILE,
    STATE_FILES,
    VALIDATION_RESULTS_FILE,
    PROOF_SPECS_FILE,
    WORKSPACE_FILE,
)
from ts_agent.workspace.validator import validate_workspace
from ts_agent.workspace.path_safety import has_symlink_component, lexical_path, path_has_symlink


def collect_report_context(
    root: str | Path,
    *,
    exclude_activity_refs: Iterable[str] = (),
) -> dict[str, Any]:
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
    documents = _read_state_documents(root_path)
    revision = workspace_revision_from_documents(documents)
    state = documents[RESEARCH_STATE_FILE]
    acceptance_refs = list(state["acceptance_refs"])
    acceptances = project_acceptances(
        root_path,
        acceptance_refs,
        documents,
        include_snapshots=True,
    )
    current_acceptances = [item for item in acceptances if item["current"]]
    operations = operational_snapshot(root_path, exclude_activity_refs=exclude_activity_refs)
    research_phases = list(documents[RESEARCH_PHASES_FILE]["phases"])
    research_nodes = list(documents[RESEARCH_NODES_FILE]["nodes"])
    return {
        "schema_version": "ts-report-context/5",
        "workspace_root": str(root_path),
        "workspace_id": documents[WORKSPACE_FILE]["workspace_id"],
        "workspace_revision": revision,
        "operational_revision": operations["operational_revision"],
        "report_id": report_id_for_revision(revision),
        "focus": {
            "claim_refs": list(state["focus_claim_refs"]),
            "node_refs": list(state["focus_node_refs"]),
        },
        "acceptance_summary": {
            "record_refs": acceptance_refs,
            "current_refs": [str(item["ref"]) for item in current_acceptances],
            "stale_refs": [str(item["ref"]) for item in acceptances if not item["current"]],
        },
        "claims": list(documents[CLAIMS_FILE]["claims"]),
        "claim_relations": list(documents[CLAIM_RELATIONS_FILE]["relations"]),
        "research_phases": research_phases,
        "research_nodes": research_nodes,
        "research_trajectory": project_research_trajectory(root_path, research_phases, research_nodes),
        "observations": list(documents[OBSERVATIONS_FILE]["observations"]),
        "proof_specs": list(documents[PROOF_SPECS_FILE]["proofs"]),
        "validation_results": list(documents[VALIDATION_RESULTS_FILE]["results"]),
        "findings": list(documents[FINDINGS_FILE]["findings"]),
        "acceptances": acceptances,
        "current_acceptances": current_acceptances,
        "deterministic_activities": operations["deterministic_activities"],
        "activity_summaries": operations["activity_summaries"],
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
    }


def _read_state_documents(root: Path) -> dict[str, dict[str, Any]]:
    """Read the canonical report inputs without following symbolic links.

    ``validate_workspace`` checks the same paths first, but a report build is
    still a separate read boundary.  Re-checking immediately before loading
    the documents prevents a linked canonical file from being silently
    imported if the workspace changes between validation and projection.
    """

    documents: dict[str, dict[str, Any]] = {}
    for name in STATE_FILES:
        path = root / name
        if has_symlink_component(root, path) or path.is_symlink():
            raise ValueError(f"workspace file contains a symbolic link: {name}")
        try:
            value = read_json(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read workspace file {name}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"workspace file is not an object: {name}")
        documents[name] = value
    return documents
