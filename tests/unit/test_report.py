from __future__ import annotations

from pathlib import Path

from tspi_runtime.io import read_json
from report_lib import build_final_report, build_report_package
from report_lib.context import collect_report_context
from tests.support.workspace_helpers import (
    apply_filesystem_change,
    bootstrap_workspace_fixture,
    start_research_node,
)


def _seed(root: Path) -> None:
    refs = start_research_node(root, title="Bounded search", objective="Search candidate saddles.")
    apply_filesystem_change(root, {"operations": [{
        "type": "create_strategy_plan", "id": "strategy_1", "claim_id": refs["claim_id"],
        "node_id": refs["node_id"], "objective": "Collect report evidence.",
        "rationale": "The report needs a declared evidence plan.", "status": "active",
    }]})
    candidate = root / "reports" / "candidates.json"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("{\"count\": 3}\n", encoding="utf-8")
    apply_filesystem_change(root, {"operations": [
        {"type": "register_artifact", "id": "art_" + "0" * 64, "kind": "analysis", "format": "json", "location": "reports/candidates.json", "sha256": "sha256:" + "0" * 64, "size_bytes": candidate.stat().st_size},
        {"type": "create_finding", "id": "fnd_1", "node_id": refs["node_id"], "claim_ids": [refs["claim_id"]], "statement": "Three candidates were retained.", "kind": "fact", "value": 3, "datatype": "integer"},
        {"type": "create_gate", "id": "gate_1", "scope": "node", "target_id": refs["node_id"], "criteria": [{"kind": "candidate_count"}]},
        {"type": "evaluate_gate", "gate_id": "gate_1", "verdict": "pass", "evidence_refs": ["art_" + "0" * 64]},
    ]})


def test_report_reads_the_canonical_research_map(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    bootstrap_workspace_fixture(root)
    _seed(root)

    context = collect_report_context(root)
    text = build_final_report(root)

    assert context["schema_version"] == "ts-report-context/7"
    assert context["research_map"]["schema_version"] == "research-map/1"
    assert context["research_map"]["focus_claim_ids"] == ["claim_1"]
    assert context["research_map"]["focus_node_ids"] == ["node_1"]
    assert "## Findings" in text
    assert "## Gates" in text
    assert "Three candidates were retained." in text
    assert "Semantic Observations" not in text
    assert "ProofSpec" not in text


def test_report_renders_a_node_without_a_phase(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    bootstrap_workspace_fixture(root)
    apply_filesystem_change(root, {"operations": [
        {"type": "create_claim", "id": "claim_1", "statement": "A saddle exists."},
        {"type": "create_node", "id": "node_1", "title": "Validate candidate", "objective": "Test the candidate without a navigation group.", "claim_ids": ["claim_1"]},
    ]})

    text = build_final_report(root)

    assert "### Unassigned Nodes" in text
    assert "`node_1`" in text


def test_report_package_contains_only_canonical_scientific_records(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    bootstrap_workspace_fixture(root)
    _seed(root)
    target = root / "reports" / "study"

    result = build_report_package(root, target)
    manifest = read_json(Path(result["manifest"]))
    refs = {item["ref"] for item in manifest["files"]}

    assert manifest["schema_version"] == "ts-report-package/5"
    assert {"research_map.json", "findings.json", "gates.json", "report_context.json", "final_report.md"} <= refs
    assert "observation_index.json" not in refs
    assert "validation.json" not in refs
    assert "acceptances.json" not in refs
