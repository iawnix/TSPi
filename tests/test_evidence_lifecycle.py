from __future__ import annotations

import pytest

from strict_helpers import HYPOTHESIS_ID, bootstrap_strict_workspace
from ts_workspace import report_workspace, update_workspace, validate_workspace
from ts_workspace.evidence_gates import accepted_gate_evidence
from ts_workspace.evidence_lifecycle import EvidenceLifecycleError, evidence_lifecycle_view
from ts_workspace.io import read_json, write_json


def test_superseded_evidence_ref_resolves_to_active_replacement() -> None:
    records = [
        {
            "evidence_id": "ev_tsfreq_incomplete",
            "kind": "gaussian_tsfreq_validation",
            "role": "tsfreq_gate",
            "quality": {},
        },
        {
            "evidence_id": "ev_tsfreq_complete",
            "kind": "gaussian_tsfreq_validation",
            "role": "tsfreq_gate",
            "quality": {"hypothesis_id": HYPOTHESIS_ID},
            "supersedes_evidence_id": "ev_tsfreq_incomplete",
        },
        {
            "evidence_id": "ev_connectivity",
            "kind": "irc_connectivity_validation",
            "role": "connectivity_gate",
            "quality": {"hypothesis_id": HYPOTHESIS_ID},
        },
    ]

    view = evidence_lifecycle_view(records)
    gates = accepted_gate_evidence(records, ["ev_tsfreq_incomplete", "ev_connectivity"])

    assert view.status_by_id["ev_tsfreq_incomplete"] == "superseded"
    assert view.resolve_ref("ev_tsfreq_incomplete") == "ev_tsfreq_complete"
    assert gates["tsfreq_gate"]["evidence_id"] == "ev_tsfreq_complete"


def test_evidence_lifecycle_rejects_multiple_terminal_events() -> None:
    records = [
        {"evidence_id": "ev_original", "kind": "observation", "role": "candidate"},
        {
            "evidence_id": "ev_withdraw",
            "kind": "evidence_lifecycle",
            "role": "evidence_lifecycle",
            "lifecycle_status": "withdrawn",
            "supersedes_evidence_id": "ev_original",
        },
        {
            "evidence_id": "ev_invalidate",
            "kind": "evidence_lifecycle",
            "role": "evidence_lifecycle",
            "lifecycle_status": "invalidated",
            "supersedes_evidence_id": "ev_original",
        },
    ]

    with pytest.raises(EvidenceLifecycleError, match="must reference active evidence"):
        evidence_lifecycle_view(records)


def test_invalidated_alias_is_preserved_but_removed_from_current_findings(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    report_ref = bootstrap_strict_workspace(workspace)
    before = report_workspace(workspace)
    registry_path = workspace / "evidence_registry.json"
    registry = read_json(registry_path)
    registry["evidence"].append(
        {
            "evidence_id": "ev_bad_alias",
            "kind": "gaussian_tsfreq_validation",
            "role": "tsfreq_gate",
            "evidence_tier": "local_parse",
            "node_id": "n000",
            "summary": "Legacy alias was registered on the wrong node type.",
        }
    )
    write_json(registry_path, registry)
    assert "evidence_role_node_mismatch" in {
        finding["code"] for finding in validate_workspace(workspace)["findings"]
    }

    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision/2",
            "action": "update_workspace",
            "rationale": "Invalidate the incorrectly owned legacy alias without deleting history.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "base_revision": report_workspace(workspace)["workspace_revision"],
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_bad_alias_invalidation",
                    "kind": "evidence_lifecycle",
                    "role": "evidence_lifecycle",
                    "evidence_tier": "manual_observation",
                    "node_id": "n000",
                    "summary": "The legacy alias has invalid ownership and is excluded from the active view.",
                    "lifecycle_status": "invalidated",
                    "supersedes_evidence_id": "ev_bad_alias",
                }
            },
        },
    )

    validation = validate_workspace(workspace)
    report = report_workspace(workspace)
    assert "evidence_role_node_mismatch" not in {finding["code"] for finding in validation["findings"]}
    assert report["evidence_count"] == before["evidence_count"]
    assert report["evidence_history_count"] == before["evidence_history_count"] + 2
    assert report["evidence_lifecycle"]["invalidated"] == 1
    assert report["evidence_lifecycle"]["lifecycle_event"] == 1
