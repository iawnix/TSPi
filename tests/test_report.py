from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.workspace_helpers import accept_research_claim
from ts_agent.compute.artifacts import list_calculation_artifacts
from ts_agent.report import build_final_report, build_report_package
from ts_agent.report import builder as report_builder
from ts_agent.report.context import collect_report_context
from tests.kernel_helpers import compile_change
from ts_agent.workspace.engine import init_workspace
from tests.kernel_helpers import apply_compiled_change
from ts_agent.io import read_json


def _seed(root: Path) -> dict[str, str]:
    drafted = compile_change(
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
    apply_compiled_change(root, drafted["decision"])
    return drafted["allocated_refs"]


def test_report_projects_roadmap_and_semantic_validation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)

    context = collect_report_context(root)
    text = build_final_report(root)

    assert context["schema_version"] == "ts-report-context/5"
    assert context["focus"]["claim_refs"] == [refs["claim"]]
    assert context["research_trajectory"]["schema_version"] == "ts-research-trajectory/1"
    assert context["research_trajectory"]["nodes"][0]["opening_decision"]["rationale"] == "Seed a reportable DAG."
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
    assert "Research decision: Seed a reportable DAG." in text
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
    roadmap = read_json(target / "research_roadmap.json")
    assert roadmap["schema_version"] == "ts-research-trajectory/1"
    assert roadmap["nodes"][0]["opening_decision"]["rationale"] == "Seed a reportable DAG."
    with pytest.raises(ValueError, match="already exists"):
        build_report_package(root, target)


def test_report_rejects_non_reports_output_path(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _seed(root)
    with pytest.raises(ValueError, match="reports"):
        build_report_package(root, tmp_path / "outside")


def test_report_does_not_ingest_symlinked_canonical_document(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "claims.json").write_text(
        (root / "claims.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "claims.json").unlink()
    (root / "claims.json").symlink_to(outside / "claims.json")

    with pytest.raises(ValueError, match="symbolic link|required file"):
        collect_report_context(root)
    with pytest.raises(ValueError, match="symbolic link|required file"):
        build_report_package(root, root / "reports" / "linked-input")


def test_report_rejects_symlinked_package_target(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _seed(root)
    external = tmp_path / "external-report"
    external.mkdir()
    target = root / "reports" / "linked-target"
    target.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        build_report_package(root, target)


def test_report_manifest_rejects_injected_symlink_entry(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "final_report.md").write_text("report\n", encoding="utf-8")
    (package / "external.txt").symlink_to(tmp_path / "secret.txt")

    with pytest.raises(ValueError, match="symbolic link"):
        report_builder._package_manifest(package, "sha256:" + "0" * 64, "sha256:" + "1" * 64)


def test_report_surfaces_operational_attempt_integrity_findings(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _seed(root)
    attempts = root / "nodes" / refs["node"] / "attempts"
    outside = tmp_path / "outside-attempts"
    (outside / "calc_1").mkdir(parents=True)
    attempts.mkdir(parents=True)
    attempts.rmdir()
    attempts.symlink_to(outside, target_is_directory=True)

    context = collect_report_context(root)
    text = build_final_report(root)

    assert context["calculation_attempt_integrity_findings"][0]["scope"] == "attempt_parent"
    assert "calculation Attempt integrity error(s) remain" in text


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

    drafted = compile_change(
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
    apply_compiled_change(root, drafted["decision"])

    stale = collect_report_context(root)
    assert stale["current_acceptances"] == []
    assert stale["acceptances"][0]["stale_reasons"] == ["finding_snapshot_changed"]
    text = build_final_report(root)
    assert "No historical acceptance remains current" in text
    assert "All focus Claims have current" not in text
