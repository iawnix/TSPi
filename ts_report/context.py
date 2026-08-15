"""Validated v4 report projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace.acceptance import project_acceptances
from ts_workspace.io import read_json
from ts_workspace.operational import operational_snapshot
from ts_workspace.revision import report_id_for_revision, workspace_revision_from_documents
from ts_workspace.state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    RESEARCH_ACTS_FILE,
    RESEARCH_STATE_FILE,
    STATE_FILES,
    VALIDATION_RESULTS_FILE,
    VALIDATION_SPECS_FILE,
    WORKSPACE_FILE,
)
from ts_workspace.validator import validate_workspace


def collect_report_context(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    validation = validate_workspace(root_path)
    if not validation["valid"]:
        messages = "; ".join(
            item["message"]
            for item in validation["findings"]
            if item.get("severity") == "error"
        )
        raise ValueError(f"workspace is invalid: {messages or 'unknown validation failure'}")
    documents = {name: read_json(root_path / name) for name in STATE_FILES}
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
    operations = operational_snapshot(root_path)
    return {
        "schema_version": "ts-report-context/4",
        "workspace_root": str(root_path),
        "workspace_id": documents[WORKSPACE_FILE]["workspace_id"],
        "workspace_revision": revision,
        "report_id": report_id_for_revision(revision),
        "focus": {
            "claim_refs": list(state["focus_claim_refs"]),
            "act_refs": list(state["focus_act_refs"]),
        },
        "acceptance_summary": {
            "record_refs": acceptance_refs,
            "current_refs": [str(item["ref"]) for item in current_acceptances],
            "stale_refs": [str(item["ref"]) for item in acceptances if not item["current"]],
        },
        "claims": list(documents[CLAIMS_FILE]["claims"]),
        "claim_relations": list(documents[CLAIM_RELATIONS_FILE]["relations"]),
        "research_acts": list(documents[RESEARCH_ACTS_FILE]["acts"]),
        "observations": list(documents[OBSERVATIONS_FILE]["observations"]),
        "validation_specs": list(documents[VALIDATION_SPECS_FILE]["specs"]),
        "validation_results": list(documents[VALIDATION_RESULTS_FILE]["results"]),
        "findings": list(documents[FINDINGS_FILE]["findings"]),
        "acceptances": acceptances,
        "current_acceptances": current_acceptances,
        "operational_summary": operations["operational_summary"],
        "unresolved_controls": operations["unresolved_controls"],
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "validation_findings": validation["findings"],
    }
