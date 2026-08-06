from __future__ import annotations

import json
import re
from pathlib import Path

from ts_workspace.validators.decision import validate_decision


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "skills" / "transition-state-workflow" / "assets" / "templates" / "decision"
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
EXPECTED_FILES = {
    "README.md",
    "start_intake.json",
    "end_intake.json",
    "start_mechanism_proposal.json",
    "end_mechanism.json",
    "start_candidate_search.json",
    "start_validation.json",
    "end_program_node.json",
    "start_audit.json",
    "end_audit.json",
    "update_evidence.json",
}
VALUES = {
    "DECISION_ID": "dec_template_001",
    "BASE_REVISION": "revision_001",
    "REPORT_ID": "rep_template_001",
    "WORKSPACE_ROOT": "/tmp/template-workspace",
    "NODE_ID": "n001",
    "PARENT_NODE": "n000",
    "HYPOTHESIS_ID": "hyp_0001",
    "HYPOTHESIS_SUMMARY": "A concerted bond-formation hypothesis.",
    "PREDICTION_ID": "pred_tsfreq_001",
    "EVIDENCE_ID": "ev_template_001",
    "EVIDENCE_SUMMARY": "A node-owned observation.",
}


def _render(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    rendered = PLACEHOLDER_RE.sub(lambda match: VALUES[match.group(1)], text)
    assert not PLACEHOLDER_RE.search(rendered), path.name
    return json.loads(rendered)


def test_v2_template_set_is_small_and_explicit() -> None:
    assert {path.name for path in TEMPLATE_DIR.iterdir() if path.is_file()} == EXPECTED_FILES


def test_all_decision_templates_render_to_current_contract() -> None:
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        decision = _render(path)
        assert validate_decision(decision) is decision
        assert decision["schema_version"] == "ts-decision/2"


def test_templates_contain_no_phase_or_legacy_closure_vocabulary() -> None:
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_DIR.glob("*.json"))
    for forbidden in ('"phase"', '"claim_verdict"', '"program_status"', '"action": "propose_hypothesis"'):
        assert forbidden not in rendered
