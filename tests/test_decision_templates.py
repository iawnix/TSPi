from __future__ import annotations

import json
import re
from pathlib import Path

from ts_workspace import draft_decision, init_workspace, validate_decision
from ts_workspace.decision import INPUT_OPERATIONS


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "skills" / "transition-state-workflow" / "assets" / "templates" / "decision"
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
EXPECTED_FILES = {
    "README.md",
    "accept_claim.json",
    "complete_act.json",
    "create_claim.json",
    "evaluate_validation.json",
    "freeze_validation_spec.json",
    "record_finding.json",
    "record_observation.json",
    "relate_claims.json",
    "start_act.json",
    "update_claim.json",
}


def test_v4_templates_are_composable_operation_snippets() -> None:
    assert {path.name for path in TEMPLATE_DIR.iterdir() if path.is_file()} == EXPECTED_FILES
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["op"] in INPUT_OPERATIONS
        assert "schema_version" not in value
        assert "decision_id" not in value
        assert "context_ref" not in value
        assert "base_revision" not in value
        assert not any(key.endswith("_id") for key in value if key != "conceptId")


def test_representative_templates_compose_through_v4_draft_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    operations = [
        _render("create_claim.json", CLAIM_TYPE="mechanism", CLAIM_STATEMENT="The pathway is concerted."),
        _render(
            "start_act.json",
            TITLE="Concerted pathway test",
            OBJECTIVE="Test the concerted pathway.",
            DELIVERABLE="A bounded result for the concerted-pathway hypothesis.",
            CLAIM_REF="$claim",
            HYPOTHESIS="A concerted saddle can be located.",
        ),
        _render(
            "record_finding.json",
            FINDING_TYPE="missing_connectivity",
            FINDING_STATEMENT="Connectivity is not yet established.",
            CLAIM_REF="$claim",
            ACT_REF="$act",
        ),
        _render("complete_act.json", ACT_REF="$act", RESULT_SUMMARY="The bounded search completed."),
    ]
    drafted = draft_decision(
        workspace,
        {"rationale": "Compose one atomic research Decision.", "basis_refs": [], "operations": operations},
    )
    decision = validate_decision(drafted["decision"])
    assert decision["schema_version"] == "ts-research-decision/1"
    assert set(drafted["allocated_refs"]) == {"claim", "act", "finding"}
    assert [operation["op"] for operation in decision["operations"]] == [
        "append_claim",
        "append_research_act",
        "append_finding",
        "complete_research_act",
    ]


def test_templates_are_strategy_neutral_and_have_no_legacy_taxonomy() -> None:
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_DIR.glob("*.json"))
    for forbidden in (
        '"phase"',
        '"node_type"',
        '"evidence_role"',
        '"evidence_layer"',
        '"required_gates"',
        '"gate_type"',
        '"branch_context"',
    ):
        assert forbidden not in rendered


def _render(name: str, **values: str) -> dict:
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    required = set(PLACEHOLDER_RE.findall(text))
    assert required == set(values), (name, required, set(values))
    return json.loads(PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], text))
