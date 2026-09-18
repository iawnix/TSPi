from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "skills" / "tspi-orchestration" / "assets" / "templates" / "research_map"
EXPECTED_FILES = {
    "README.md",
    "create_claim.json",
    "create_finding.json",
    "create_gate.json",
    "create_node.json",
    "create_phase.json",
    "evaluate_gate.json",
    "relate_claims.json",
    "set_claim_status.json",
    "set_focus.json",
    "set_node_state.json",
}
EXPECTED_TYPES = {
    "create_phase",
    "create_claim",
    "create_node",
    "create_finding",
    "create_gate",
    "evaluate_gate",
    "set_node_state",
    "set_claim_status",
    "relate_claims",
    "set_focus",
}


def test_research_map_templates_are_current_operation_snippets() -> None:
    assert {path.name for path in TEMPLATE_DIR.iterdir() if path.is_file()} == EXPECTED_FILES
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["type"] in EXPECTED_TYPES
        assert "op" not in value
        assert "local_ref" not in value
        assert "decision_id" not in value
        assert "context_ref" not in value


def test_research_map_templates_do_not_reintroduce_removed_protocols() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_DIR.iterdir())
    for forbidden in (
        "Observation",
        "ProofSpec",
        "ValidationResult",
        "accept_claim",
        "freeze_gate",
        "record_observation",
        "start_node",
        "complete_node",
    ):
        assert forbidden not in text
