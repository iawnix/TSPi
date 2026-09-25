from __future__ import annotations

import json
import subprocess
import sys

import pytest

from ts_agent.api import CommandError, execute
from tests.support.workspace_helpers import (
    REPO_ROOT,
    bootstrap_workspace_fixture,
    calculation_intent_fixture,
    calculation_prepared_fixture,
    start_research_node,
)

ROOT = REPO_ROOT


def _strategy_request(event_id: str = "strategy-event") -> dict:
    return {
        "schema_version": "research-strategy-request/1",
        "operation": "plan",
        "event_id": event_id,
        "plan": {
            "id": "strategy_1",
            "claim_id": "claim_1",
            "node_id": "node_1",
            "objective": "Compare the two candidate pathways.",
            "rationale": "The current evidence does not distinguish them.",
            "status": "active",
            "created_at": "2026-09-25T00:00:00Z",
        },
    }


def _strategy_review_request(event_id: str = "review-event") -> dict:
    return {
        "schema_version": "research-strategy-request/1",
        "operation": "review",
        "event_id": event_id,
        "rationale": "The initial plan remains the best bounded option.",
        "basis_refs": ["strategy_1"],
        "review": {
            "id": "review_1",
            "claim_id": "claim_1",
            "decision": "continue",
            "rationale": "The first attempt does not justify a strategy switch.",
            "selected_strategy_id": "strategy_1",
            "trigger_refs": ["strategy_1"],
            "attempt_refs": ["calc_1"],
            "created_at": "2026-09-25T00:01:00Z",
        },
    }


def _interpretation_request(event_id: str = "interpretation-event") -> dict:
    return {
        "schema_version": "research-interpretation-request/1",
        "event_id": event_id,
        "rationale": "Bind the operational result to the Claim decision thread.",
        "basis_refs": ["calc_1"],
        "interpretation": {
            "id": "interpretation_1",
            "claim_id": "claim_1",
            "node_id": "node_1",
            "attempt_ref": "calc_1",
            "summary": "The bounded attempt is inconclusive.",
            "outcome": "inconclusive",
            "created_at": "2026-09-25T00:02:00Z",
        },
    }


def _materialize_attempt(root):
    intent = calculation_intent_fixture("node_1", "calc_1")
    attempt_dir = root / "nodes" / "node_1" / "attempts" / "calc_1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "intent.json").write_text(json.dumps(intent), encoding="utf-8")
    prepared = calculation_prepared_fixture(intent)
    (attempt_dir / "prepared.json").write_text(json.dumps(prepared), encoding="utf-8")


def _api_cli(command: str, root, request_file) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_api.py"),
            command,
            "--root",
            str(root),
            "--request-file",
            str(request_file),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_decision_commands_bootstrap_sqlite_and_checkpoint(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)

    strategy = execute("research.strategy", root, {"request": _strategy_request()})
    assert strategy["record"]["id"] == "strategy_1"
    assert execute("research.storage", root)["backend"] == "sqlite"

    checkpoint = execute("research.checkpoint", root, {"request": {
        "schema_version": "research-checkpoint-request/1",
        "checkpoint": {
            "id": "checkpoint_1",
            "turn_id": "turn_1",
            "disposition": "continue_required",
            "reason": "Continue the declared strategy in the next turn.",
            "claim_ids": ["claim_1"],
            "node_ids": ["node_1"],
            "unresolved_refs": ["strategy_1"],
            "created_at": "2026-09-25T00:01:00Z",
        },
    }})
    assert checkpoint["record"]["map_revision"] == checkpoint["commit"]["revision"]
    assert execute("research.decisions", root)["records"]["turn_checkpoints"][0]["id"] == "checkpoint_1"


def test_decision_commands_record_strategy_review_interpretation_and_storage(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    _materialize_attempt(root)

    storage = execute("research.storage", root, {"operation": "bootstrap"})
    assert storage["backend"] == "sqlite"
    assert storage["path"] == str(root / "research.db")
    assert (root / "research.db").is_file()

    plan = execute("research.strategy", root, {"request": _strategy_request()})
    review = execute("research.strategy", root, {"request": _strategy_review_request()})
    interpretation = execute(
        "research.interpretation", root, {"request": _interpretation_request()}
    )

    assert plan["operation"] == "plan"
    assert review["operation"] == "review"
    assert review["record"]["decision"] == "continue"
    assert interpretation["record"]["attempt_ref"] == "calc_1"
    decisions = execute("research.decisions", root, {"claim_id": "claim_1", "limit": 16})
    records = decisions["records"]
    assert [row["id"] for row in records["strategy_plans"]] == ["strategy_1"]
    assert [row["id"] for row in records["strategy_reviews"]] == ["review_1"]
    assert [row["id"] for row in records["attempt_interpretations"]] == ["interpretation_1"]


def test_decision_request_file_cli_uses_canonical_strategy_command(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    request_file = tmp_path / "strategy-request.json"
    request_file.write_text(json.dumps(_strategy_request("cli-event")), encoding="utf-8")

    result = _api_cli("research.strategy", root, request_file)

    assert result["schema_version"] == "research-strategy-result/1"
    assert result["record"]["id"] == "strategy_1"
    assert result["commit"]["created_ids"] == ["strategy_1"]


def test_continue_checkpoint_requires_strategy_plan(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    with pytest.raises(CommandError, match="active StrategyPlan"):
        execute("research.checkpoint", root, {"request": {
            "schema_version": "research-checkpoint-request/1",
            "checkpoint": {
                "id": "checkpoint_1",
                "turn_id": "turn_1",
                "disposition": "continue_required",
                "reason": "Continue.",
                "claim_ids": ["claim_1"],
                "node_ids": ["node_1"],
                "unresolved_refs": [],
                "created_at": "2026-09-25T00:01:00Z",
            },
        }})
