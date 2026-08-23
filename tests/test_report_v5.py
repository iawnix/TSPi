from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.v5_helpers import accept_research_claim
from ts_compute.artifacts import list_calculation_artifacts
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
                {"op": "create_phase", "local_ref": "phase", "title": "Mechanism search", "objective": "Locate and validate a concerted pathway."},
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": "mechanism",
                    "statement": "A concerted saddle can be located for the pathway.",
                    "assumptions": ["The selected conformer is representative."],
                    "falsifiers": ["Every candidate relaxes to a stepwise intermediate."],
                },
                {
                    "op": "start_node",
                    "local_ref": "node",
                    "phaseRef": "$phase",
                    "title": "Bounded research node",
                    "deliverable": "One bounded research result.",
                    "objective": "Search for a concerted pathway.",
                    "primaryClaimRef": "$claim",
                    "claimRefs": ["$claim"],
                },
                {
                    "op": "create_claim",
                    "local_ref": "discovered",
                    "claimType": "mechanism",
                    "statement": "A stepwise alternative may require investigation.",
                    "createdByNode": "$node",
                },
                {
                    "op": "record_observation",
                    "local_ref": "observation",
                    "nodeRef": "$node",
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
                    "nodeRefs": ["$node"],
                    "basisObservationRefs": ["$observation"],
                },
                {"op": "set_focus", "claimRefs": ["$claim"], "nodeRefs": ["$node"]},
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    return drafted["allocated_refs"]


def test_report_projects_v5_roadmap_and_semantic_validation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)

    context = collect_report_context(root)
    text = build_final_report(root)

    assert context["schema_version"] == "ts-report-context/5"
    assert context["focus"]["claim_refs"] == [refs["claim"]]
    assert "## Research Roadmap" in text
    assert "## Scientific Conclusions" in text
    assert "## ResearchNode Records" in text
    assert refs["phase"] in text
    assert "A concerted saddle can be located for the pathway." in text
    assert "Every candidate relaxes to a stepwise intermediate." in text
    assert "Deterministic activities: 0 total" in text
    assert "Scientific records: 1 Observations, 1 Findings" in text
    assert "## Semantic Observations" in text
    assert "## Frozen Validation" in text
    assert "## Findings" in text
    assert refs["node"] in text
    assert f"`{refs['claim']}, {refs['discovered']}`" in text
    assert "required_gates" not in text
    assert "node_id" not in text


def test_report_package_is_revision_and_manifest_bound(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _seed(root)
    target = root / "reports" / "study-report"

    result = build_report_package(root, target)
    manifest = read_json(Path(result["manifest"]))

    assert manifest["schema_version"] == "ts-report-package/4"
    assert manifest["workspace_revision"] == result["workspace_revision"]
    assert manifest["operational_revision"] == result["operational_revision"]
    refs = {item["ref"] for item in manifest["files"]}
    assert {
        "acceptances.json",
        "activities.json",
        "claim_graph.json",
        "email_summary.md",
        "final_report.md",
        "findings.json",
        "observation_index.json",
        "report_context.json",
        "research_roadmap.json",
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


def test_report_copies_logical_render_artifacts_into_manifested_assets(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)
    source = root / "nodes" / refs["node"] / "outputs" / "render" / "mechanism overview.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PNG report asset")
    artifact = next(
        row
        for row in list_calculation_artifacts(root)["artifacts"]
        if row["path"] == source.relative_to(root).as_posix()
    )

    result = build_report_package(
        root,
        root / "reports" / "with-assets",
        asset_artifact_ids=[artifact["artifact_id"]],
    )

    assert result["asset_artifact_ids"] == [artifact["artifact_id"]]
    assert result["asset_refs"] == ["reports/with-assets/assets/01-mechanism_overview.png"]
    copied = root / result["asset_refs"][0]
    assert copied.read_bytes() == source.read_bytes()
    asset_index = read_json(root / "reports" / "with-assets" / "asset_index.json")
    assert asset_index["assets"][0]["source_ref"] == source.relative_to(root).as_posix()
    manifest = read_json(root / "reports" / "with-assets" / "package_manifest.json")
    assert result["asset_refs"][0].removeprefix("reports/with-assets/") in {
        row["ref"] for row in manifest["files"]
    }


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
                    "nodeRefs": [refs["node"]],
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
