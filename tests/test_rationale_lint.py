"""Pre-execution rationale linting contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import initialize_workspace, validate_workspace_allow_errors

from transition_state_workflow.base.rationale import lint_node_rationale  # noqa: E402
from transition_state_workflow.web.server import load_node_payload  # noqa: E402


def write_incomplete_decision_card(root: Path, node_id: str) -> None:
    """Replace the decision card with old-style draft placeholder text."""

    path = root / "nodes" / node_id / "decision_card.md"
    path.write_text(
        """# TS Decision Card: n010_candidate

## Why This Tool

Explain why this is the lowest-cost chemically meaningful test now.

## Cost And Risk

- Compute cost:
- Numerical risk:
- Chemical risk:
""",
        encoding="utf-8",
    )


def test_rationale_lint_flags_old_decision_card_placeholders(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    write_incomplete_decision_card(root, "n010_candidate")

    lint = lint_node_rationale(root, "n010_candidate").to_dict()

    assert lint["status"] == "draft"
    assert lint["ok_to_start"] is False
    decision = lint["files"]["decision_card"]
    assert "Explain why this is the lowest-cost chemically meaningful test now." in decision["placeholder_hits"]
    assert "- Compute cost:" in decision["empty_field_hits"]
    assert "Input / Dependency Nodes" in decision["missing_sections"]


def test_decision_card_writes_structured_provenance_contract(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    provenance = node["decision_provenance"]
    assert provenance["trigger_source"] == "agent_cli_decision_card"
    assert provenance["parent_selection_reason"]
    assert provenance["changed_variables"]["operation"] == "unit-test-candidate-generation"
    assert provenance["claim_ceiling"] == "candidate_found"

    lint = lint_node_rationale(root, "n010_candidate", node).to_dict()
    assert lint["status"] == "complete"
    assert lint["decision_provenance"]["complete"] is True


def test_validator_errors_for_running_node_with_draft_rationale(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    write_incomplete_decision_card(root, "n010_candidate")

    active_validation = validate_workspace_allow_errors(root)
    active_findings = [
        item for item in active_validation["findings"] if item["code"] == "incomplete_pre_execution_rationale"
    ]
    assert active_findings
    assert active_findings[0]["severity"] == "error"


def test_node_payload_includes_shared_rationale_lint(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    write_incomplete_decision_card(root, "n010_candidate")

    payload = load_node_payload(root, "n010_candidate")

    assert payload["rationale_lint"]["status"] == "draft"
    assert payload["rationale_lint"]["ok_to_start"] is False
