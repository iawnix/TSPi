from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
TEMPLATE = SKILL_ROOT / "assets" / "templates" / "ts_final_report.md"
CONTRACT = SKILL_ROOT / "references" / "report_template.md"


def test_report_template_contains_required_v4_sections() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for phrase in [
        "Executive Status",
        "Claims And Relations",
        "ResearchAct DAG",
        "Computational Protocol",
        "Semantic Observations",
        "Frozen Validation",
        "Connectivity And Endpoints",
        "Findings And Claim Acceptance",
        "Operational Follow-Up",
    ]:
        assert phrase in text


def test_report_contract_keeps_v4_acceptance_and_provenance_explicit() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for phrase in [
        "acceptance record",
        "GateSpecs",
        "passing ValidationResults",
        "Finding snapshot",
        "stationary-point",
        "reaction-coordinate",
        "connectivity",
        "registered Observation",
        "source artifact",
        "Review opinion",
    ]:
        assert phrase in text
