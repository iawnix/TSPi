from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.v4_helpers import accept_research_claim
from ts_report import build_final_report, build_report_package
from ts_report.context import collect_report_context
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace
from ts_workspace.io import read_json


def _seed(root: Path) -> dict[str, str]:
    drafted = draft_decision(
        root,
        {
            "rationale": "Seed a reportable DAG.",
            "basis_refs": [],
            "operations": [
                {"op": "create_claim", "local_ref": "claim", "claimType": "mechanism", "statement": "The pathway is concerted."},
                {
                    "op": "start_act",
                    "local_ref": "act",
                    "objective": "Search for a concerted pathway.",
                    "claimRefs": ["$claim"],
                    "hypothesis": {
                        "statement": "A concerted saddle can be located.",
                        "assumptions": ["The selected conformer is representative."],
                        "predictions": ["A single reaction-coordinate mode will be found."],
                        "falsifiers": ["Every candidate relaxes to a stepwise intermediate."],
                    },
                },
                {
                    "op": "record_observation",
                    "local_ref": "observation",
                    "actRef": "$act",
                    "conceptId": "candidate.count",
                    "subjectRef": "search_001",
                    "value": 3,
                    "datatype": "integer",
                    "summary": "Three candidates were retained.",
                    "provenance": {"producer": "test-search", "producerVersion": "1"},
                },
                {
                    "op": "record_finding",
                    "local_ref": "finding",
                    "findingType": "connectivity_missing",
                    "severity": "blocking",
                    "statement": "Connectivity has not been established.",
                    "claimRefs": ["$claim"],
                    "actRefs": ["$act"],
                    "basisObservationRefs": ["$observation"],
                },
                {"op": "set_focus", "claimRefs": ["$claim"], "actRefs": ["$act"]},
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    return drafted["allocated_refs"]


def test_report_projects_v4_dag_and_semantic_validation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)

    context = collect_report_context(root)
    text = build_final_report(root)

    assert context["schema_version"] == "ts-report-context/4"
    assert context["focus"]["claim_refs"] == [refs["claim"]]
    assert "## Claim Graph" in text
    assert "## ResearchAct DAG" in text
    assert "### ResearchAct Review" in text
    assert "A concerted saddle can be located." in text
    assert "Every candidate relaxes to a stepwise intermediate." in text
    assert "Linked records: 0 operations, 1 Observations, 1 Findings" in text
    assert "## Semantic Observations" in text
    assert "## Frozen Validation" in text
    assert "## Findings" in text
    assert refs["act"] in text
    assert "required_gates" not in text
    assert "node_id" not in text


def test_report_package_is_revision_and_manifest_bound(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _seed(root)
    target = root / "reports" / "study-report"

    result = build_report_package(root, target)
    manifest = read_json(Path(result["manifest"]))

    assert manifest["schema_version"] == "ts-report-package/2"
    assert manifest["workspace_revision"] == result["workspace_revision"]
    refs = {item["ref"] for item in manifest["files"]}
    assert {
        "acceptances.json",
        "claim_graph.json",
        "email_summary.md",
        "final_report.md",
        "findings.json",
        "observation_index.json",
        "report_context.json",
        "research_acts.json",
        "validation.json",
    } <= refs
    for item in manifest["files"]:
        path = target / item["ref"]
        assert item["size_bytes"] == path.stat().st_size
        assert item["sha256"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="already exists"):
        build_report_package(root, target)


def test_report_rejects_non_reports_output_path(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _seed(root)
    with pytest.raises(ValueError, match="reports"):
        build_report_package(root, tmp_path / "outside")


def test_report_uses_only_current_acceptance_for_executive_status(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = accept_research_claim(root)

    current = collect_report_context(root)
    assert [item["acceptance_id"] for item in current["current_acceptances"]] == [refs["acceptance"]]
    assert "current, immutable acceptance snapshots" in build_final_report(root)

    drafted = draft_decision(
        root,
        {
            "rationale": "Record a later limitation without erasing acceptance history.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "record_finding",
                    "local_ref": "limitation",
                    "findingType": "later_limitation",
                    "severity": "warning",
                    "statement": "A later limitation requires a new acceptance assessment.",
                    "claimRefs": [refs["claim"]],
                    "actRefs": [refs["act"]],
                }
            ],
        },
    )
    apply_decision(root, drafted["decision"])

    stale = collect_report_context(root)
    assert stale["current_acceptances"] == []
    assert stale["acceptances"][0]["stale_reasons"] == ["finding_snapshot_changed"]
    text = build_final_report(root)
    assert "No historical acceptance remains current" in text
    assert "All focus Claims have current" not in text
