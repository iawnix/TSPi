from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "ts_final_report.md"
CONTRACT = ROOT / "references" / "report_template.md"


def test_report_template_contains_required_evidence_layers() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for phrase in [
        "Executive Verdict",
        "Reaction And Hypothesis Scope",
        "Computational Protocol",
        "Search Tree Summary",
        "Candidate Generation Evidence",
        "TS/Freq Validation",
        "Connectivity / IRC Validation",
        "Accepted-TS Audit",
        "Pathway Audit",
        "Energy Profile",
        "Artifact And Evidence Appendix",
    ]:
        assert phrase in text


def test_report_template_contract_keeps_acceptance_gates_explicit() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "Minimum Acceptance Gates" in text
    assert "tsfreq_gate" in text
    assert "connectivity_gate" in text
    assert "accepted_audit" in text
    assert "pathway_not_accepted" in text
