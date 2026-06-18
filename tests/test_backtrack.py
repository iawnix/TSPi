"""Backtrack: record/update events, supersede semantics, validator rules."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import (
    WORKSPACE_CLI,
    create_failed_irc_branch_for_planner,
    initialize_workspace,
    normalize_workspace,
    plan_next,
    run_cli,
    validate_workspace,
    validate_workspace_allow_errors,
)


def create_retry_node_for_backtrack(root: Path, node_id: str) -> None:
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--stage",
        "candidate_generation",
        "--parent-id",
        "n010_candidate",
        "--hypothesis",
        f"{node_id} is a retry branch after backtracking.",
        "--operation",
        "unit-test-retry",
    )
def test_record_backtrack_creates_canonical_edge_without_new_branch_badge(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n020_retry",
        "--stage",
        "candidate_generation",
        "--parent-id",
        "n010_candidate",
        "--hypothesis",
        "Retry branch after a numerical failure.",
        "--operation",
        "unit-test-retry",
    )

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "unit_test_backtrack",
        "--reason",
        "Unit-test backtrack edge.",
    )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert tree["backtrack_events"][0]["from_node"] == "n010_candidate"
    assert tree["backtrack_events"][0]["to_node"] == "n020_retry"
    assert tree["backtrack_events"][0]["new_branch_node"] == ""
    assert tree["events"][-1]["event_type"] == "record_backtrack"

    graph = normalize_workspace(root)
    backtrack_edges = [edge for edge in graph["edges"] if edge["kind"] == "backtrack"]
    assert len(backtrack_edges) == 1
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id["n010_candidate"]["backtrack_event_ids"]
    assert by_id["n020_retry"]["backtrack_event_ids"] == []

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_record_backtrack_rejects_second_active_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    create_retry_node_for_backtrack(root, "n030_retry")

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "first_active_backtrack",
        "--reason",
        "First active backtrack.",
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_cli(
            str(WORKSPACE_CLI),
            "record-backtrack",
            "--root",
            str(root),
            "--from-node",
            "n005_endpoint_gate",
            "--to-node",
            "n030_retry",
            "--reason-code",
            "second_active_backtrack",
            "--reason",
            "Second active backtrack should be rejected.",
        )

    assert "active backtrack event already exists" in exc_info.value.stderr
    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_record_backtrack_supersede_active_allows_new_active_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    create_retry_node_for_backtrack(root, "n030_retry")

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "first_active_backtrack",
        "--reason",
        "First active backtrack.",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n005_endpoint_gate",
        "--to-node",
        "n030_retry",
        "--reason-code",
        "second_active_backtrack",
        "--reason",
        "Second active backtrack supersedes the first.",
        "--supersede-active",
    )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert [event["event_state"] for event in tree["backtrack_events"]] == ["superseded", "active"]
    assert any(event["event_type"] == "supersede_backtrack" for event in tree["events"])
    graph = normalize_workspace(root)
    backtrack_edges = [edge for edge in graph["edges"] if edge["kind"] == "backtrack"]
    assert len(backtrack_edges) == 2
    by_state = {edge["event_state"]: edge for edge in backtrack_edges}
    assert by_state["superseded"]["target"] == "n020_retry"
    assert by_state["active"]["target"] == "n030_retry"

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_update_backtrack_resolves_active_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_failed_irc_branch_for_planner(root)
    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n030_failed_irc",
        "--to-node",
        "n005_endpoint_gate",
        "--reason-code",
        "irc_l123_failure",
        "--reason",
        "Return to endpoint readiness and try a chemically distinct candidate-generation route.",
    )
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    backtrack_id = tree["backtrack_events"][0]["id"]

    run_cli(
        str(WORKSPACE_CLI),
        "update-backtrack",
        "--root",
        str(root),
        "--backtrack-id",
        backtrack_id,
        "--event-state",
        "resolved",
        "--reason",
        "The replanning branch has been created, so this active backtrack is closed.",
    )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert tree["backtrack_events"][0]["event_state"] == "resolved"
    assert tree["backtrack_events"][0]["resolved_at"]
    assert tree["events"][-1]["event_type"] == "update_backtrack"
    graph = normalize_workspace(root)
    backtrack_edges = [edge for edge in graph["edges"] if edge["kind"] == "backtrack"]
    assert len(backtrack_edges) == 1
    assert backtrack_edges[0]["event_state"] == "resolved"
    assert backtrack_edges[0]["source"] == "n030_failed_irc"
    assert backtrack_edges[0]["target"] == "n005_endpoint_gate"
    packet = plan_next(root)
    assert packet["planning_focus"]["mode"] != "backtrack_replan"
    assert all(action["from_node"] != "n030_failed_irc" for action in packet["required_backtrack_events"])

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_update_backtrack_rejects_missing_to_node_reference(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "unit_test_backtrack",
        "--reason",
        "Unit-test backtrack edge.",
    )
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    backtrack_id = tree["backtrack_events"][0]["id"]
    tree["backtrack_events"][0]["to_node"] = "n999_missing_target"
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_cli(
            str(WORKSPACE_CLI),
            "update-backtrack",
            "--root",
            str(root),
            "--backtrack-id",
            backtrack_id,
            "--event-state",
            "resolved",
            "--reason",
            "This should not update a malformed backtrack event.",
        )

    assert "backtrack to_node does not exist" in exc_info.value.stderr
def test_update_backtrack_rejects_missing_new_branch_reference(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n010_candidate",
        "--new-branch-node",
        "n020_retry",
        "--reason-code",
        "unit_test_backtrack",
        "--reason",
        "Unit-test backtrack edge with a retry branch.",
    )
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    backtrack_id = tree["backtrack_events"][0]["id"]
    tree["backtrack_events"][0]["new_branch_node"] = "n999_missing_retry"
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_cli(
            str(WORKSPACE_CLI),
            "update-backtrack",
            "--root",
            str(root),
            "--backtrack-id",
            backtrack_id,
            "--event-state",
            "resolved",
            "--reason",
            "This should not update a malformed backtrack event.",
        )

    assert "backtrack new_branch_node does not exist" in exc_info.value.stderr
def test_update_backtrack_requires_supersede_when_activating_over_existing_active(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    create_retry_node_for_backtrack(root, "n030_retry")

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "first_active_backtrack",
        "--reason",
        "First active backtrack.",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n005_endpoint_gate",
        "--to-node",
        "n030_retry",
        "--reason-code",
        "historical_backtrack",
        "--reason",
        "Historical backtrack record.",
        "--event-state",
        "resolved",
    )
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    second_id = tree["backtrack_events"][1]["id"]

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_cli(
            str(WORKSPACE_CLI),
            "update-backtrack",
            "--root",
            str(root),
            "--backtrack-id",
            second_id,
            "--event-state",
            "active",
            "--reason",
            "This should require explicit superseding.",
        )
    assert "another active backtrack event already exists" in exc_info.value.stderr

    run_cli(
        str(WORKSPACE_CLI),
        "update-backtrack",
        "--root",
        str(root),
        "--backtrack-id",
        second_id,
        "--event-state",
        "active",
        "--reason",
        "Reactivate this backtrack and supersede the earlier active event.",
        "--supersede-active",
    )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert [event["event_state"] for event in tree["backtrack_events"]] == ["superseded", "active"]
    assert tree["events"][-1]["event_type"] == "update_backtrack"
    graph = normalize_workspace(root)
    backtrack_edges = [edge for edge in graph["edges"] if edge["kind"] == "backtrack"]
    assert len(backtrack_edges) == 2
    by_state = {edge["event_state"]: edge for edge in backtrack_edges}
    assert by_state["superseded"]["target"] == "n020_retry"
    assert by_state["active"]["target"] == "n030_retry"

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_validator_rejects_multiple_active_backtrack_events(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    create_retry_node_for_backtrack(root, "n030_retry")

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "first_active_backtrack",
        "--reason",
        "First active backtrack.",
    )
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["backtrack_events"].append(
        {
            "id": "bt_second_active_backtrack",
            "from_node": "n005_endpoint_gate",
            "to_node": "n030_retry",
            "new_branch_node": "",
            "reason_code": "second_active_backtrack",
            "reason": "Manually inserted second active backtrack.",
            "evidence_refs": [],
            "event_state": "active",
            "created_at": "2026-06-05T00:00:00+00:00",
        }
    )
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "multiple_active_backtracks" in codes


def test_normalizer_rejects_invalid_backtrack_event_state(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_retry_node_for_backtrack(root, "n020_retry")
    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n020_retry",
        "--reason-code",
        "unit_test_backtrack",
        "--reason",
        "Unit-test backtrack edge.",
    )
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["backtrack_events"][0]["event_state"] = "resolved bad"
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        normalize_workspace(root)

    assert "invalid event_state: resolved bad" in exc_info.value.stderr


def test_plan_next_and_validator_detect_replacement_branch_without_backtrack_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_failed_irc_branch_for_planner(root)
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n040_endpoint_connectivity_retry",
        "--parent-id",
        "n020_tsfreq",
        "--stage",
        "connectivity_validation",
        "--hypothesis",
        "Retry connectivity validation from the same TS/Freq node after the IRC failure.",
        "--operation",
        "unit-test-connectivity-retry",
    )

    packet = plan_next(root)
    action = packet["required_backtrack_events"][0]
    assert action["from_node"] == "n030_failed_irc"
    assert action["default_to_node_from_parent"] == "n020_tsfreq"
    assert action["detected_new_branch_node"] == "n040_endpoint_connectivity_retry"
    assert action["kind"] == "backtrack_event_required"

    validation = validate_workspace_allow_errors(root)
    assert any(
        finding["code"] == "missing_replacement_backtrack_event"
        for finding in validation["findings"]
    )

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n030_failed_irc",
        "--to-node",
        "n020_tsfreq",
        "--new-branch-node",
        "n040_endpoint_connectivity_retry",
        "--reason-code",
        "irc_l123_failure",
        "--reason",
        "Retry connectivity validation from the TS/Freq node with a changed connectivity method.",
    )
    validation = validate_workspace(root, strict=True)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "missing_replacement_backtrack_event" not in codes


def test_decision_card_replaces_node_records_backtrack_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_failed_irc_branch_for_planner(root)

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n040_endpoint_connectivity_retry",
        "--parent-id",
        "n020_tsfreq",
        "--stage",
        "connectivity_validation",
        "--hypothesis",
        "Retry connectivity validation from the same TS/Freq node after the IRC failure.",
        "--operation",
        "unit-test-connectivity-retry",
        "--replaces-node",
        "n030_failed_irc",
        "--backtrack-reason-code",
        "irc_l123_failure",
        "--backtrack-reason",
        "Retry connectivity validation from the TS/Freq node with a changed connectivity method.",
    )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    event = tree["backtrack_events"][0]
    assert event["from_node"] == "n030_failed_irc"
    assert event["to_node"] == "n020_tsfreq"
    assert event["new_branch_node"] == "n040_endpoint_connectivity_retry"
    assert event["reason_code"] == "irc_l123_failure"
    assert event["event_state"] == "active"
    assert tree["events"][-1]["event_type"] == "record_backtrack"

    packet = plan_next(root)
    assert packet["planning_focus"]["mode"] == "backtrack_replan"
    assert packet["planning_focus"]["parent_for_new_branch"] == "n020_tsfreq"
    validation = validate_workspace(root, strict=True)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "missing_replacement_backtrack_event" not in codes


def test_record_backtrack_new_branch_is_metadata_not_badge(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n020_retry",
        "--stage",
        "candidate_generation",
        "--parent-id",
        "n010_candidate",
        "--hypothesis",
        "Retry branch after a numerical failure.",
        "--operation",
        "unit-test-retry",
    )

    run_cli(
        str(WORKSPACE_CLI),
        "record-backtrack",
        "--root",
        str(root),
        "--from-node",
        "n010_candidate",
        "--to-node",
        "n010_candidate",
        "--new-branch-node",
        "n020_retry",
        "--reason-code",
        "unit_test_backtrack",
        "--reason",
        "Unit-test backtrack edge with a retry branch.",
    )

    graph = normalize_workspace(root)
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id["n010_candidate"]["backtrack_event_ids"]
    assert by_id["n020_retry"]["backtrack_event_ids"] == []
    assert by_id["n020_retry"]["generated_from_backtrack_event_ids"]
