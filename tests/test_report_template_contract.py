from __future__ import annotations

from pathlib import Path

from tests.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.report import build_final_report


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "tspi-report"
CONTRACT = SKILL_ROOT / "references" / "report_template.md"


def test_report_builder_contains_required_sections(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    text = build_final_report(workspace)
    for phrase in [
        "Executive Status",
        "Research Roadmap",
        "Scientific Conclusions",
        "ResearchNode Records",
        "Semantic Observations",
        "Frozen Validation",
        "Findings",
        "Claim Acceptance",
        "Operational Follow-up",
    ]:
        assert phrase in text


def test_report_contract_keeps_acceptance_and_provenance_explicit() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for phrase in [
        "acceptance record",
        "ProofSpecs",
        "passing ValidationResults",
        "Finding snapshot",
        "stationary-point",
        "reaction-coordinate",
        "connectivity",
        "registered Observation",
        "source artifact",
    ]:
        assert phrase in text
