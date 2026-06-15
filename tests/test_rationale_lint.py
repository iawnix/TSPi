"""Pre-execution rationale linting contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import WORKSPACE_CLI, initialize_workspace, validate_workspace_allow_errors

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


def test_start_node_rejects_incomplete_pre_execution_rationale(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    write_incomplete_decision_card(root, "n010_candidate")

    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "start-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--run-state",
            "running",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "incomplete pre-execution rationale" in result.stderr


def test_validator_warns_for_prepared_draft_and_errors_after_start_state(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    write_incomplete_decision_card(root, "n010_candidate")

    prepared_validation = validate_workspace_allow_errors(root)
    prepared_findings = [
        item for item in prepared_validation["findings"] if item["code"] == "incomplete_pre_execution_rationale"
    ]
    assert prepared_findings
    assert prepared_findings[0]["severity"] == "warning"

    node_path = root / "nodes" / "n010_candidate" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["lifecycle_state"] = "active"
    node["run_state"] = "running"
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
