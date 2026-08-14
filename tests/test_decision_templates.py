from __future__ import annotations

import json
import re
from pathlib import Path

from ts_workspace import validate_decision


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "skills" / "transition-state-workflow" / "assets" / "templates" / "decision"
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
EXPECTED_FILES = {
    "README.md",
    "append_claim.json",
    "append_evidence.json",
    "end_audit.json",
    "end_node.json",
    "evaluate_gate.json",
    "link_operation.json",
    "start_node.json",
}
VALUES = {
    "ARTIFACT_REF": "nodes/n001/outputs/parsed.json",
    "AUDIT_SUMMARY": "Required deterministic Gates passed.",
    "BASE_REVISION": "sha256:" + "0" * 64,
    "BASIS_REF": "claim_reaction_001",
    "CLAIM_ID": "claim_reaction_001",
    "CLAIM_KIND": "reaction_path/1",
    "CLAIM_STATEMENT": "The proposed path connects the declared endpoints.",
    "CLAIM_UPDATE_SUMMARY": "The selected evidence supports this claim.",
    "DECISION_ID": "dec_template_001",
    "EVIDENCE_ID": "ev_template_001",
    "EVIDENCE_KIND": "gaussian.validation/1",
    "EVIDENCE_SUMMARY": "Parsed deterministic facts.",
    "GATE_RESULT_ID": "gr_template_tsfreq",
    "GATE_TYPE": "tsfreq",
    "NODE_ID": "n001",
    "OBJECTIVE": "Test one explicit scientific question.",
    "OPERATION_REF": "nodes/n001/attempts/calc_n001_test_0001/intent.json",
    "PARENT_NODE": "n000",
    "PRODUCER": "test-parser",
    "REPORT_ID": "rep_template_001",
    "RESULT_SUMMARY": "The bounded research act is complete.",
    "SECOND_GATE_RESULT_ID": "gr_template_connectivity",
    "TAG": "validation",
    "WORKSPACE_ROOT": "/tmp/template-workspace",
}


def _render(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    rendered = PLACEHOLDER_RE.sub(lambda match: VALUES[match.group(1)], text)
    assert not PLACEHOLDER_RE.search(rendered), path.name
    return json.loads(rendered)


def test_v3_template_set_is_small_and_strategy_neutral() -> None:
    assert {path.name for path in TEMPLATE_DIR.iterdir() if path.is_file()} == EXPECTED_FILES


def test_all_decision_templates_render_to_current_contract() -> None:
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        decision = _render(path)
        assert validate_decision(decision) is decision
        assert decision["schema_version"] == "ts-decision/3"


def test_templates_do_not_select_research_behavior_from_taxonomy_fields() -> None:
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_DIR.glob("*.json"))
    for forbidden in (
        '"phase"',
        '"node_type"',
        '"validation_scope"',
        '"audit_scope"',
        '"candidate_plan"',
        '"hypothesis_ref"',
        '"branch_context"',
    ):
        assert forbidden not in rendered
