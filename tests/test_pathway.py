"""Pathway workflow: multi-step planning, step gates, binding, status rollup."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import (
    SKILL_ROOT,
    WORKSPACE_CLI,
    create_pathway_candidate_node,
    create_pathway_endpoint_node,
    finalize_pathway_candidate_as_accepted,
    initialize_pathway_workspace,
    normalize_workspace,
    plan_next,
    run_cli,
    validate_workspace,
    validate_workspace_allow_errors,
)

from transition_state_workflow.base.workspace import ExplorerWorkspaceConfig  # noqa: E402
from transition_state_workflow.tool.explorer_server import summarize_explorer_workspace_config  # noqa: E402
from transition_state_workflow.tool.pathway_model import derive_pathway_status  # noqa: E402


def test_pathway_plan_tags_first_step_suggestion_and_normalized_graph(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)

    packet = plan_next(root)

    assert packet["search_state"]["phase"] == "endpoint_discovery"
    assert packet["search_state"]["pathway_phase"] == "start"
    assert packet["planning_focus"]["mode"] == "pathway_step_planning"
    assert packet["planning_focus"]["pathway_id"] == "p001"
    assert packet["planning_focus"]["step_id"] == "s1"
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["pathway_id"] == "p001"
    assert suggestion["step_id"] == "s1"
    assert "--pathway-id" in suggestion["decision_card_command"]
    assert "--step-id" in suggestion["decision_card_command"]

    written = run_cli(str(WORKSPACE_CLI), "plan-next", "--root", str(root), "--write-decision-cards", "--pretty")
    written_packet = json.loads(written.stdout)
    written_node = written_packet["written_decision_cards"][0]["node_id"]
    node = json.loads((root / "nodes" / written_node / "node.json").read_text(encoding="utf-8"))
    assert node["pathway_id"] == "p001"
    assert node["elementary_step_id"] == "s1"

    graph = normalize_workspace(root)
    assert graph["pathway"]["mode"] == "multi_step"
    graph_node = next(item for item in graph["nodes"] if item["id"] == written_node)
    assert graph_node["pathway_id"] == "p001"
    assert graph_node["elementary_step_id"] == "s1"
def test_pathway_planner_uses_step_local_gates_after_first_step_acceptance(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)
    create_pathway_endpoint_node(root, node_id="n010_s1_endpoint", step_id="s1")
    create_pathway_candidate_node(root, node_id="n020_s1_candidate", step_id="s1", parent_id="n010_s1_endpoint")
    finalize_pathway_candidate_as_accepted(root, node_id="n020_s1_candidate", step_id="s1")

    packet = plan_next(root)
    assert packet["search_state"]["phase"] == "endpoint_discovery"
    assert packet["search_state"]["pathway_phase"] == "continue"
    assert packet["planning_focus"]["step_id"] == "s2"
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["parent_id"] == "n020_s1_candidate"
    assert suggestion["pathway_id"] == "p001"
    assert suggestion["step_id"] == "s2"

    create_pathway_endpoint_node(root, node_id="n030_s2_endpoint", step_id="s2", parent_id="n020_s1_candidate")
    packet = plan_next(root)
    assert packet["search_state"]["phase"] == "candidate_generation"
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["parent_id"] == "n030_s2_endpoint"
    assert suggestion["pathway_id"] == "p001"
    assert suggestion["step_id"] == "s2"

    create_pathway_candidate_node(root, node_id="n040_s2_candidate", step_id="s2", parent_id="n030_s2_endpoint")
    packet = plan_next(root)
    assert packet["search_state"]["phase"] == "gaussian_tsfreq_validation"
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["parent_id"] == "n040_s2_candidate"
    assert suggestion["pathway_id"] == "p001"
    assert suggestion["step_id"] == "s2"

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_pathway_candidate_requires_step_local_endpoint_gate(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)
    create_pathway_endpoint_node(root, node_id="n010_s1_endpoint", step_id="s1")
    create_pathway_candidate_node(root, node_id="n020_s1_candidate", step_id="s1", parent_id="n010_s1_endpoint")
    finalize_pathway_candidate_as_accepted(root, node_id="n020_s1_candidate", step_id="s1")

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n030_s2_candidate_direct",
        "--parent-id",
        "n020_s1_candidate",
        "--stage",
        "candidate_generation",
        "--hypothesis",
        "A bad s2 candidate tries to reuse s1 endpoint evidence.",
        "--operation",
        "unit-test-direct-candidate",
        "--pathway-id",
        "p001",
        "--step-id",
        "s2",
    )
    parsed = root / "nodes" / "n030_s2_candidate_direct" / "parsed" / "candidate.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n030_s2_candidate_direct/parsed/candidate.json",
        "claim": "Candidate exists for s2 without a step-local endpoint gate.",
        "evidence_state": "candidate_found",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "finalize-node",
            "--root",
            str(root),
            "--node-id",
            "n030_s2_candidate_direct",
            "--claim-status",
            "candidate_found",
            "--decision",
            "bad_candidate_without_s2_endpoint",
            "--summary",
            "Candidate finalized without step-local endpoint gate.",
            "--primary-file",
            "nodes/n030_s2_candidate_direct/parsed/candidate.json",
            "--pathway-id",
            "p001",
            "--step-id",
            "s2",
            "--evidence",
            json.dumps(evidence),
            "--computational-outcome",
            "Candidate generation completed.",
            "--mechanistic-implication",
            "This should have required s2 endpoint_minima_ready.",
            "--next-branch",
            "n/a",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "same pathway step" in result.stderr
def test_validator_rejects_pathway_candidate_without_step_local_endpoint_gate(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)
    create_pathway_endpoint_node(root, node_id="n010_s1_endpoint", step_id="s1")
    create_pathway_candidate_node(root, node_id="n020_s1_candidate", step_id="s1", parent_id="n010_s1_endpoint")
    finalize_pathway_candidate_as_accepted(root, node_id="n020_s1_candidate", step_id="s1")

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n030_s2_candidate_direct",
        "--parent-id",
        "n020_s1_candidate",
        "--stage",
        "candidate_generation",
        "--hypothesis",
        "A bad s2 candidate tries to reuse s1 endpoint evidence.",
        "--operation",
        "unit-test-direct-candidate",
        "--pathway-id",
        "p001",
        "--step-id",
        "s2",
    )
    parsed = root / "nodes" / "n030_s2_candidate_direct" / "parsed" / "candidate.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    node_path = root / "nodes" / "n030_s2_candidate_direct" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node.update(
        {
            "lifecycle_state": "closed",
            "run_state": "completed",
            "claim_status": "candidate_found",
            "outcome": "candidate_generated",
            "claim_level": "candidate_only",
        }
    )
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["closed_nodes"] = [*tree.get("closed_nodes", []), "n030_s2_candidate_direct"]
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "pathway_candidate_without_step_endpoint_gate" in codes
def test_explorer_workspace_summary_reports_partial_pathway_not_accepted(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)
    create_pathway_endpoint_node(root, node_id="n010_s1_endpoint", step_id="s1")
    create_pathway_candidate_node(root, node_id="n020_s1_candidate", step_id="s1", parent_id="n010_s1_endpoint")
    finalize_pathway_candidate_as_accepted(root, node_id="n020_s1_candidate", step_id="s1")

    summary = summarize_explorer_workspace_config(
        ExplorerWorkspaceConfig(
            workspace_id="unit",
            display_name="unit",
            source_directory=root,
            explorer_state_directory=tmp_path / "state",
        )
    )

    assert summary["accepted_ts"] == "n020_s1_candidate"
    assert summary["claim_state"] == "pathway_partial"
    assert summary["pathway_status"] == "partial"
    assert summary["pathway"]["next_incomplete_step"]["step_id"] == "s2"
def test_pathway_status_prioritizes_rejected_and_ambiguous_over_partial() -> None:
    assert derive_pathway_status([{"status": "accepted_ts"}, {"status": "rejected"}]) == "ambiguous"
    assert derive_pathway_status([{"status": "candidate"}, {"status": "rejected"}]) == "ambiguous"
    assert derive_pathway_status([{"status": "ambiguous"}, {"status": "missing"}]) == "ambiguous"
    assert derive_pathway_status([{"status": "rejected"}, {"status": "rejected"}]) == "rejected"
    assert derive_pathway_status([{"status": "accepted_ts"}, {"status": "candidate"}]) == "partial"
def test_pathway_step_rejection_stops_forward_pathway_planning(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)
    create_pathway_endpoint_node(root, node_id="n010_s1_endpoint", step_id="s1")
    create_pathway_candidate_node(root, node_id="n020_s1_candidate", step_id="s1", parent_id="n010_s1_endpoint")
    finalize_pathway_candidate_as_accepted(root, node_id="n020_s1_candidate", step_id="s1")
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n030_s2_refuted",
        "--parent-id",
        "n020_s1_candidate",
        "--stage",
        "endpoint_minima_validation",
        "--hypothesis",
        "Step s2 is refuted because the proposed intermediate/product boundary is not stable.",
        "--operation",
        "unit-test-pathway-refutation",
        "--pathway-id",
        "p001",
        "--step-id",
        "s2",
    )
    parsed = root / "nodes" / "n030_s2_refuted" / "parsed" / "refutation.json"
    parsed.write_text('{"step_refuted": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n030_s2_refuted/parsed/refutation.json",
        "claim": "Step s2 boundary is refuted in this unit-test pathway.",
        "evidence_state": "refutes",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n030_s2_refuted",
        "--claim-status",
        "rejected",
        "--outcome",
        "wrong_endpoint",
        "--outcome-code",
        "step_boundary_refuted",
        "--decision",
        "reject_pathway_step",
        "--summary",
        "Step s2 is refuted, so the active multi-step pathway is ambiguous.",
        "--primary-file",
        "nodes/n030_s2_refuted/parsed/refutation.json",
        "--pathway-id",
        "p001",
        "--step-id",
        "s2",
        "--pathway-step-status",
        "rejected",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "The proposed s2 endpoint boundary is not chemically defensible.",
        "--mechanistic-implication",
        "The current two-step pathway needs mechanism reassessment.",
        "--next-branch",
        "Backtrack to the mechanism hypothesis or open an alternative pathway.",
    )

    summary = summarize_explorer_workspace_config(
        ExplorerWorkspaceConfig(
            workspace_id="unit",
            display_name="unit",
            source_directory=root,
            explorer_state_directory=tmp_path / "state",
        )
    )
    assert summary["claim_state"] == "pathway_ambiguous"
    assert summary["pathway_status"] == "ambiguous"
    assert summary["pathway"]["active_pathway"]["steps"][1]["status_node"] == "n030_s2_refuted"

    packet = plan_next(root)
    assert packet["search_state"]["pathway_phase"] == "ambiguous"
    assert packet["search_state"]["phase"] == "pathway_ambiguous"
    assert packet["planning_focus"]["mode"] == "pathway_ambiguous_review"
    assert packet["planning_focus"]["focus_node"] == "n030_s2_refuted"
    assert packet["suggested_decision_cards"] == []
    assert "continue_rejected_or_ambiguous_pathway_without_changed_hypothesis" in packet["forbidden_next_actions"]

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
def test_pathway_binding_rejects_reusing_one_accepted_ts_for_multiple_steps(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_pathway"
    initialize_pathway_workspace(root)
    create_pathway_endpoint_node(root, node_id="n010_s1_endpoint", step_id="s1")
    create_pathway_candidate_node(root, node_id="n020_s1_candidate", step_id="s1", parent_id="n010_s1_endpoint")
    finalize_pathway_candidate_as_accepted(root, node_id="n020_s1_candidate", step_id="s1")

    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "pathway-bind-step",
            "--root",
            str(root),
            "--pathway-id",
            "p001",
            "--step-id",
            "s2",
            "--node-id",
            "n020_s1_candidate",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "already bound to a different pathway step" in result.stderr

    pathway_path = root / "pathway_model.json"
    pathway = json.loads(pathway_path.read_text(encoding="utf-8"))
    pathway["pathways"][0]["steps"][1]["status"] = "accepted_ts"
    pathway["pathways"][0]["steps"][1]["accepted_ts_node"] = "n020_s1_candidate"
    pathway_path.write_text(json.dumps(pathway, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "pathway_step_duplicate_accepted_node" in codes
    assert "pathway_step_node_binding_conflict" in codes
