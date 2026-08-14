from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
TEMPLATE = SKILL_ROOT / "assets" / "templates" / "ts_final_report.md"
CONTRACT = SKILL_ROOT / "references" / "report_template.md"


def test_report_template_contains_required_v3_sections() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for phrase in [
        "Executive Status",
        "Scientific Claims",
        "Computational Protocol",
        "Deterministic Gate Results",
        "Connectivity And Endpoints",
        "Research Nodes",
        "Accepted Artifacts",
        "Evidence Appendix",
        "Operational Follow-Up",
    ]:
        assert phrase in text


def test_report_template_contract_keeps_acceptance_gates_explicit() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "accepted-ts/2" in text
    assert "TS/Freq" in text
    assert "connectivity Gate results" in text
    assert "accepted-pathway/1" in text
    assert "Node tag" in text
    assert "advisory Review" in text
