from __future__ import annotations

from pathlib import Path

from ts_agent.io import read_json
from ts_agent.report import build_final_report, build_report_package
from ts_agent.report.context import collect_report_context
from ts_agent.workspace.engine import change_workspace, init_workspace


def _seed(root: Path) -> None:
    change_workspace(root, {
        "expected_revision": 0,
        "operations": [
            {"type": "create_phase", "id": "phase_1", "title": "Mechanism", "objective": "Locate a pathway."},
            {"type": "create_claim", "id": "claim_1", "statement": "A concerted saddle exists.", "falsifiers": ["All candidates relax stepwise."]},
            {"type": "create_node", "id": "node_1", "title": "Bounded search", "objective": "Search candidate saddles.", "phase_id": "phase_1", "claim_ids": ["claim_1"]},
            {"type": "create_finding", "id": "fnd_1", "node_id": "node_1", "claim_ids": ["claim_1"], "statement": "Three candidates were retained.", "kind": "fact", "value": 3, "datatype": "integer"},
            {"type": "create_gate", "id": "gate_1", "scope": "node", "target_id": "node_1", "criteria": [{"kind": "candidate_count"}]},
            {"type": "evaluate_gate", "gate_id": "gate_1", "verdict": "pass", "evidence_refs": ["fnd_1"]},
            {"type": "set_focus", "claim_ids": ["claim_1"], "node_ids": ["node_1"]},
        ],
    })


def test_report_reads_the_canonical_research_map(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
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


def test_report_package_contains_only_canonical_scientific_records(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
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
