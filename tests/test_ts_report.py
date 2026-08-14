from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from strict_helpers import CLAIM_ID, make_accepted_workspace
from ts_report import build_final_report, build_report_package
from ts_report.context import collect_report_context
from ts_workspace.io import read_json, write_json


def test_report_projects_claim_gate_evidence_and_node_records(tmp_path: Path) -> None:
    workspace = tmp_path / "report"
    make_accepted_workspace(workspace)

    text = build_final_report(workspace)

    assert "## Scientific Claims" in text
    assert f"`{CLAIM_ID}` (focus)" in text
    assert "`tsfreq` / `tsfreq/2`" in text
    assert "`connectivity` / `connectivity/2`" in text
    assert "## Evidence Facts" in text
    assert "Root Agent owns research strategy" in text
    for legacy in ("node_type", "validation_scope", "hypothesis_ref", "claim_verdict"):
        assert legacy not in text


def test_report_context_uses_active_evidence_and_accepted_claim_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "context"
    make_accepted_workspace(workspace)

    context = collect_report_context(workspace)

    assert context["schema_version"] == "ts-report-context/3"
    assert context["focus_claim_refs"] == [CLAIM_ID]
    claim = next(row for row in context["claims"] if row["claim_id"] == CLAIM_ID)
    assert claim["status"] == "supported"
    assert {row["gate"] for row in context["gate_results"]} == {"tsfreq", "connectivity"}
    assert context["accepted_artifacts"][0]["schema_version"] == "ts-accepted-claim/1"
    assert context["accepted_artifacts"][0]["target_ref"] == CLAIM_ID


def test_report_package_is_manifest_bound_and_immutable_on_collision(tmp_path: Path) -> None:
    workspace = tmp_path / "package"
    make_accepted_workspace(workspace)
    package_dir = workspace / "reports" / "claim-report"

    result = build_report_package(workspace, package_dir)
    manifest = read_json(Path(result["manifest"]))

    assert manifest["schema_version"] == "ts-report-package/1"
    assert manifest["workspace_revision"] == result["workspace_revision"]
    refs = {row["ref"] for row in manifest["files"]}
    assert {
        "claims.json",
        "email_summary.md",
        "evidence_index.json",
        "final_report.md",
        "gate_results.json",
        "report_context.json",
    } <= refs
    for row in manifest["files"]:
        path = package_dir / row["ref"]
        assert row["size_bytes"] == path.stat().st_size
        assert row["sha256"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="already exists"):
        build_report_package(workspace, package_dir)


def test_report_rejects_tampered_deterministic_gate_result(tmp_path: Path) -> None:
    workspace = tmp_path / "tampered"
    make_accepted_workspace(workspace)
    path = workspace / "gate_results.json"
    registry = read_json(path)
    registry["gate_results"][0]["verdict"] = "fail"
    write_json(path, registry)

    with pytest.raises(ValueError, match="workspace is invalid"):
        collect_report_context(workspace)


def test_email_summary_is_a_report_artifact_not_an_external_side_effect(tmp_path: Path) -> None:
    workspace = tmp_path / "email-summary"
    make_accepted_workspace(workspace)
    result = build_report_package(workspace, workspace / "reports" / "pkg")
    summary = Path(result["email_summary"]).read_text(encoding="utf-8")

    assert "Subject: TS research workspace update" in summary
    assert f"{CLAIM_ID}: supported" in summary
    assert "Main report: final_report.md" in summary
