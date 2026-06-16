"""Finalize-node, validator, planner, decision-card, start-node tests.

CLI paths, ``run_cli``, workspace builders, and pathway fixtures live in
``conftest.py`` and are re-used by every other ``test_*.py`` file. This module
keeps the original cross-cutting test set that has not been moved out yet.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import (
    IMAGINARY_MODE_CLI,
    NODE_EXEC_CLI,
    NORMALIZER_CLI,
    REMOTE_FETCH_CLI,
    REMOTE_GAUSSIAN_CLI,
    REMOTE_STATUS_CLI,
    REMOTE_TAIL_CLI,
    SKILL_ROOT,
    VALIDATOR_CLI,
    WORKSPACE_CLI,
    create_failed_irc_branch_for_planner,
    create_pathway_candidate_node,
    create_pathway_endpoint_node,
    finalize_pathway_candidate_as_accepted,
    initialize_empty_workspace,
    initialize_pathway_workspace,
    initialize_workspace,
    normalize_workspace,
    plan_next,
    run_cli,
    validate_workspace,
    validate_workspace_allow_errors,
)

from transition_state_workflow.base.pathway_model import derive_pathway_status  # noqa: E402
from transition_state_workflow.base.workspace import ExplorerWorkspaceConfig  # noqa: E402
from transition_state_workflow.remote import gaussian_monitor as remote_gaussian_monitor  # noqa: E402
from transition_state_workflow.remote import gaussian_runner as remote_gaussian  # noqa: E402
from transition_state_workflow.util import remote_exec  # noqa: E402
from transition_state_workflow.web.server import infer_gaussian_file_notes, summarize_explorer_workspace_config  # noqa: E402


def test_finalize_node_closes_workspace_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")

    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "candidate_found",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--outcome",
        "candidate_generated",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Unit-test candidate was generated and remains candidate-only evidence.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--badge",
        "candidate_found",
        "--metric",
        "barrier_ev=1.25",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "The unit-test candidate-generation step completed.",
        "--mechanistic-implication",
        "The branch remains candidate-only and needs later validation.",
        "--knowledge-update",
        "Validated facts: unit-test candidate summary exists.",
        "--next-branch",
        "Run Gaussian TS/Freq validation in a real workflow.",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "evidence_registry.json").read_text(encoding="utf-8"))
    reflection = (root / "nodes" / "n010_candidate" / "reflection.md").read_text(encoding="utf-8")

    assert node["lifecycle_state"] == "closed"
    assert node["run_state"] == "completed"
    assert node["claim_status"] == "candidate_found"
    assert node["claim_level"] == "candidate_only"
    assert node["display"]["metrics"]["barrier_ev"] == 1.25
    assert tree["active_frontier"] == []
    assert "n010_candidate" in tree["closed_nodes"]
    candidate_records = [record for record in registry["records"] if record["node_id"] == "n010_candidate"]
    assert candidate_records[0]["path"] == "nodes/n010_candidate/parsed/summary.json"
    assert "Not run yet" not in reflection
    assert "Pending" not in reflection

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_finalize_node_appends_structured_mechanism_analysis(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    mechanism = json.loads((root / "mechanism_model.json").read_text(encoding="utf-8"))
    assert set(mechanism["analysis_plan"]) == {
        "reaction_type",
        "reaction_center",
        "electronic",
        "orbital",
        "energy",
    }
    assert set(mechanism["mechanism_analysis"]) == {
        "reaction_type",
        "reaction_center",
        "electronic",
        "orbital",
        "energy",
    }

    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true, "barrier_ev": 1.25}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary includes a finite rough barrier.",
        "evidence_state": "candidate_found",
    }
    analysis = {
        "layer": "energy",
        "status": "supported",
        "summary": "The candidate branch has a finite rough barrier estimate.",
        "metrics": {"barrier_ev": 1.25},
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Candidate generated with a rough energy descriptor.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Candidate generation completed.",
        "--mechanistic-implication",
        "Energy evidence is candidate-level and not an accepted barrier.",
        "--mechanism-analysis",
        json.dumps(analysis),
        "--next-branch",
        "Run Gaussian TS/Freq validation.",
    )

    mechanism = json.loads((root / "mechanism_model.json").read_text(encoding="utf-8"))
    energy_records = mechanism["mechanism_analysis"]["energy"]
    assert len(energy_records) == 1
    assert energy_records[0]["status"] == "supported"
    assert energy_records[0]["summary"] == analysis["summary"]
    assert energy_records[0]["metrics"]["barrier_ev"] == 1.25
    assert energy_records[0]["evidence_refs"]


def test_finalize_node_records_mechanism_analysis_source_without_evidence(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    source = root / "nodes" / "n010_candidate" / "outputs" / "preflight.log"
    source.write_text("No orbital or population section was requested.\n", encoding="utf-8")
    analysis = {
        "layer": "orbital",
        "status": "unavailable",
        "summary": "No orbital or population section was produced by this preflight branch.",
        "source": "nodes/n010_candidate/outputs/preflight.log",
    }

    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "not_evaluated",
        "--decision",
        "record_unavailable_orbital_source",
        "--summary",
        "Orbital analysis is unavailable and source-backed.",
        "--primary-file",
        "nodes/n010_candidate/outputs/preflight.log",
        "--computational-outcome",
        "No electronic-structure descriptor calculation was run.",
        "--mechanistic-implication",
        "No orbital mechanism claim is made.",
        "--mechanism-analysis",
        json.dumps(analysis),
        "--next-branch",
        "Run a population or NBO follow-up only if needed.",
    )

    mechanism = json.loads((root / "mechanism_model.json").read_text(encoding="utf-8"))
    orbital_records = mechanism["mechanism_analysis"]["orbital"]
    assert orbital_records[-1]["source"] == "nodes/n010_candidate/outputs/preflight.log"
    assert orbital_records[-1]["evidence_refs"] == []

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_finalize_node_rejects_mechanism_analysis_without_source_or_evidence(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    analysis = {
        "layer": "electronic",
        "status": "ambiguous",
        "summary": "This statement has no source and no evidence reference.",
    }

    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "finalize-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--claim-status",
            "not_evaluated",
            "--decision",
            "bad_unsourced_mechanism_analysis",
            "--summary",
            "Unsourced mechanism analysis must fail.",
            "--primary-file",
            "nodes/n010_candidate/decision_card.md",
            "--computational-outcome",
            "n/a",
            "--mechanistic-implication",
            "n/a",
            "--mechanism-analysis",
            json.dumps(analysis),
            "--next-branch",
            "n/a",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "missing source for layers: electronic" in result.stderr


def test_validator_rejects_unsourced_mechanism_analysis_record(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    mechanism_path = root / "mechanism_model.json"
    mechanism = json.loads(mechanism_path.read_text(encoding="utf-8"))
    mechanism["mechanism_analysis"]["energy"].append(
        {
            "node_id": "n010_candidate",
            "claim_status": "not_evaluated",
            "status": "hypothesis",
            "summary": "An energy interpretation was written without provenance.",
            "evidence_refs": [],
        }
    )
    mechanism_path.write_text(json.dumps(mechanism, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "mechanism_analysis_source_missing" in codes


def test_finalize_node_allows_not_evaluated_numerical_failure(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "not_evaluated",
        "--outcome",
        "numerical_failure",
        "--outcome-code",
        "xtb_scan_failed",
        "--run-state",
        "error",
        "--decision",
        "retry_with_smaller_step",
        "--summary",
        "The unit-test scan failed numerically before producing a scientific claim.",
        "--primary-file",
        "nodes/n010_candidate/outputs/scan.log",
        "--computational-outcome",
        "The scan stopped with a numerical failure before candidate evidence existed.",
        "--mechanistic-implication",
        "No chemical hypothesis was refuted by this run.",
        "--next-branch",
        "Retry the same hypothesis with a smaller step size.",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    assert node["claim_status"] == "not_evaluated"
    assert node["outcome"] == "numerical_failure"
    assert node["claim_level"] == "none"
    graph = normalize_workspace(root)
    by_id = {item["id"]: item for item in graph["nodes"]}
    assert by_id["n010_candidate"]["node_state"] == "numerical_failure"

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_plan_next_blocks_candidate_until_endpoint_ready(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_empty_workspace(root)

    packet = plan_next(root)

    assert packet["schema"] == "ts-next-action-plan-v1"
    assert packet["search_state"]["phase"] == "endpoint_discovery"
    assert "endpoint_minima_missing" in packet["blocking_gates"]
    assert "xtb_endpoint_preopt" in packet["allowed_next_actions"]
    assert "gaussian_endpoint_validation" in packet["allowed_next_actions"]
    assert "candidate_found_promotion" in packet["forbidden_next_actions"]
    assert "gaussian_neb_from_reference_hypothesis" in packet["forbidden_next_actions"]
    assert packet["suggested_decision_cards"][0]["stage"] == "endpoint_minima_validation"


def test_plan_next_suggests_tsfreq_after_candidate_found(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "candidate_found",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Unit-test candidate exists.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Candidate generation completed.",
        "--mechanistic-implication",
        "The candidate needs TS/Freq validation.",
        "--next-branch",
        "Run Gaussian TS/Freq validation.",
    )

    packet = plan_next(root)

    assert packet["search_state"]["phase"] == "gaussian_tsfreq_validation"
    assert "tsfreq_validation_missing" in packet["blocking_gates"]
    assert "gaussian_tsfreq_validation" in packet["allowed_next_actions"]
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["stage"] == "gaussian_tsfreq_validation"
    assert suggestion["parent_id"] == "n010_candidate"


def test_plan_next_routes_to_connectivity_when_tsfreq_exists_without_candidate_found(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n020_direct_tsfreq",
        "--parent-id",
        "n005_endpoint_gate",
        "--stage",
        "gaussian_tsfreq_validation",
        "--hypothesis",
        "A Gaussian QST branch directly produced TS/Freq validation without a separate candidate node.",
        "--operation",
        "unit-test-direct-gaussian-qst",
    )
    tsfreq_summary = root / "nodes" / "n020_direct_tsfreq" / "parsed" / "tsfreq.json"
    tsfreq_summary.write_text(
        json.dumps(
            {
                "status": "validated_ts",
                "normal_termination": True,
                "stationary_point_found": True,
                "final_convergence_satisfied": True,
                "imaginary_frequency_count": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = {
        "kind": "gaussian_tsfreq_validation",
        "path": "nodes/n020_direct_tsfreq/parsed/tsfreq.json",
        "claim": "Unit-test direct Gaussian branch validated a TS/Freq result.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n020_direct_tsfreq",
        "--claim-status",
        "tsfreq_validated",
        "--decision",
        "prepare_connectivity_validation",
        "--summary",
        "Direct Gaussian branch validated TS/Freq evidence.",
        "--primary-file",
        "nodes/n020_direct_tsfreq/parsed/tsfreq.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Direct Gaussian branch completed TS/Freq validation.",
        "--mechanistic-implication",
        "Connectivity validation is now the next evidence layer.",
        "--next-branch",
        "Run connectivity validation.",
    )

    packet = plan_next(root)

    assert packet["search_state"]["candidate_nodes"] == []
    assert packet["search_state"]["tsfreq_validated_nodes"] == ["n020_direct_tsfreq"]
    assert packet["search_state"]["phase"] == "connectivity_validation"
    assert "connectivity_missing" in packet["blocking_gates"]
    assert "imaginary_mode_endpoint_follow" in packet["allowed_next_actions"]
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["stage"] == "connectivity_validation"
    assert suggestion["parent_id"] == "n020_direct_tsfreq"


def test_plan_next_exposes_reframe_candidate_for_rejected_tsfreq_wrong_mode(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    candidate_evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "candidate_found",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Unit-test candidate exists.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--evidence",
        json.dumps(candidate_evidence),
        "--computational-outcome",
        "Candidate generation completed.",
        "--mechanistic-implication",
        "The candidate needs TS/Freq validation.",
        "--next-branch",
        "Run Gaussian TS/Freq validation.",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n020_rejected_tsfreq",
        "--parent-id",
        "n010_candidate",
        "--stage",
        "gaussian_tsfreq_validation",
        "--hypothesis",
        "A TS/Freq candidate may be the wrong mode for the original one-step hypothesis.",
        "--operation",
        "unit-test-gaussian-tsfreq",
    )
    tsfreq_summary = root / "nodes" / "n020_rejected_tsfreq" / "parsed" / "tsfreq.json"
    tsfreq_summary.write_text(
        json.dumps(
            {
                "status": "validated_ts",
                "normal_termination": True,
                "stationary_point_found": True,
                "final_convergence_satisfied": True,
                "imaginary_frequency_count": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tsfreq_evidence = {
        "kind": "tsfreq_summary",
        "path": "nodes/n020_rejected_tsfreq/parsed/tsfreq.json",
        "claim": "Unit-test rejected branch still has structured TS/Freq evidence.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n020_rejected_tsfreq",
        "--claim-status",
        "rejected",
        "--outcome",
        "wrong_mode",
        "--outcome-code",
        "mode_matches_reframed_second_step",
        "--decision",
        "reframe_as_alternative_step",
        "--summary",
        "TS/Freq is structured but wrong for the original one-step endpoint assignment.",
        "--primary-file",
        "nodes/n020_rejected_tsfreq/parsed/tsfreq.json",
        "--evidence",
        json.dumps(tsfreq_evidence),
        "--computational-outcome",
        "Gaussian TS/Freq completed, but mode/connectivity was wrong for the original hypothesis.",
        "--mechanistic-implication",
        "The candidate may be reusable only under a new intended reaction boundary.",
        "--knowledge-update",
        "Open questions: whether this TS/Freq corresponds to a second step.",
        "--next-branch",
        "Create a new connectivity branch with new endpoint/intermediate references and input_ref to this TS/Freq node.",
    )

    packet = plan_next(root)

    assert packet["planning_focus"]["mode"] == "backtrack_decision_needed"
    assert "reframe_validated_wrong_mode_tsfreq_with_new_endpoint_refs" in packet["allowed_next_actions"]
    assert "promote_rejected_tsfreq_without_new_connectivity_boundary" in packet["forbidden_next_actions"]
    assert packet["reframe_candidates"][0]["node_id"] == "n020_rejected_tsfreq"
    assert packet["reframe_candidates"][0]["tsfreq_evidence"][0]["kind"] == "tsfreq_summary"
    assert packet["suggested_reframe_actions"][0]["source_node"] == "n020_rejected_tsfreq"
    assert "n020_rejected_tsfreq" in packet["suggested_reframe_actions"][0]["decision_card_command_template"]
    assert any(item["kind"] == "reframe_candidate" for item in packet["context_items"])


def test_plan_next_requires_backtrack_before_new_child_under_failed_branch(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    create_failed_irc_branch_for_planner(root)

    packet = plan_next(root)

    assert packet["planning_focus"]["mode"] == "backtrack_decision_needed"
    assert packet["planning_focus"]["focus_node"] == "n030_failed_irc"
    assert packet["suggested_decision_cards"] == []
    action = packet["suggested_backtrack_actions"][0]
    assert action["from_node"] == "n030_failed_irc"
    assert "n005_endpoint_gate" in action["candidate_to_nodes"]
    assert "new_child_under_failed_node_without_backtrack" in packet["forbidden_next_actions"]


def test_plan_next_routes_new_branch_to_active_backtrack_target(tmp_path: Path) -> None:
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

    packet = plan_next(root)

    assert packet["planning_focus"]["mode"] == "backtrack_replan"
    assert packet["planning_focus"]["from_failed_node"] == "n030_failed_irc"
    assert packet["planning_focus"]["parent_for_new_branch"] == "n005_endpoint_gate"
    assert packet["search_state"]["phase"] == "candidate_generation"
    assert packet["search_state"]["global_phase"] == "connectivity_validation"
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["stage"] == "candidate_generation"
    assert suggestion["parent_id"] == "n005_endpoint_gate"
    must_context = [item for item in packet["context_items"] if item["priority"] == "must"]
    assert any(item.get("node_id") == "n030_failed_irc" for item in must_context)
    assert packet["context_policy"]["retrieval_mode"] == "ranked_workspace_artifacts"
    assert packet["context_items"][0]["retrieval_rank"] == 1
    assert packet["context_items"][0]["retrieval_action"] == "read_first"


def test_plan_next_distinguishes_xtb_and_gaussian_candidate_routes(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    packet = plan_next(root)

    assert packet["search_state"]["phase"] == "candidate_generation"
    assert "xtb_neb_candidate_generation" in packet["allowed_next_actions"]
    assert "xtb_relaxed_scan" in packet["allowed_next_actions"]
    assert "gaussian_neb_refinement" in packet["allowed_next_actions"]
    suggestion = packet["suggested_decision_cards"][0]
    assert suggestion["stage"] == "candidate_generation"
    assert "xtb-neb-scan-dimer-gaussian-refinement" in suggestion["operation"]


def test_plan_next_can_write_suggested_decision_card(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_empty_workspace(root)

    packet = plan_next(root, "--write-decision-cards")

    written = packet["written_decision_cards"]
    assert written[0]["status"] == "written"
    node_id = written[0]["node_id"]
    assert (root / "nodes" / node_id / "decision_card.md").exists()
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert node_id in tree["nodes"]


def test_validator_warns_for_closed_node_with_template_reflection(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    run_cli(
        str(WORKSPACE_CLI),
        "add-evidence",
        "--root",
        str(root),
        "--kind",
        "parsed_summary",
        "--path",
        "nodes/n010_candidate/parsed/summary.json",
        "--node-id",
        "n010_candidate",
        "--claim",
        "Unit-test candidate summary exists.",
        "--evidence-state",
        "candidate_found",
    )

    node_path = root / "nodes" / "n010_candidate" / "node.json"
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
    tree["closed_nodes"] = ["n010_candidate"]
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "template_reflection_closed_node" in codes


def test_finalize_accepted_ts_updates_workspace_global_state(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    tsfreq = root / "nodes" / "n010_candidate" / "parsed" / "tsfreq.json"
    connectivity = root / "nodes" / "n010_candidate" / "parsed" / "connectivity.json"
    tsfreq.write_text(
        json.dumps(
            {
                "status": "validated_ts",
                "normal_termination": True,
                "stationary_point_found": True,
                "final_convergence_satisfied": True,
                "imaginary_frequency_count": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    connectivity.write_text(
        json.dumps({"decision": "connected", "connectivity_supported": True}) + "\n",
        encoding="utf-8",
    )

    tsfreq_evidence = {
        "kind": "gaussian_tsfreq_validation",
        "path": "nodes/n010_candidate/parsed/tsfreq.json",
        "claim": "Unit-test Gaussian TS/Freq evidence supports exactly one imaginary frequency.",
        "evidence_state": "supports",
    }
    connectivity_evidence = {
        "kind": "connectivity_check",
        "path": "nodes/n010_candidate/parsed/connectivity.json",
        "claim": "Unit-test TS connects the intended endpoints.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "accepted_ts",
        "--outcome",
        "accepted",
        "--decision",
        "stop_search_accept_ts",
        "--summary",
        "Unit-test transition state is accepted after connectivity evidence.",
        "--primary-file",
        "nodes/n010_candidate/parsed/connectivity.json",
        "--evidence",
        json.dumps(tsfreq_evidence),
        "--evidence",
        json.dumps(connectivity_evidence),
        "--computational-outcome",
        "The unit-test TS/Freq and connectivity layers passed.",
        "--mechanistic-implication",
        "The tested mechanism is accepted for this unit-test workspace.",
        "--knowledge-update",
        "Validated facts: unit-test connectivity evidence supports acceptance.",
        "--next-branch",
        "No further branch is needed in this unit test.",
        "--knowledge-fact",
        "Unit-test connectivity evidence supports accepted_ts.",
        "--mechanism-fact",
        "Unit-test accepted TS is recorded.",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "evidence_registry.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    mechanism = json.loads((root / "mechanism_model.json").read_text(encoding="utf-8"))
    knowledge = (root / "knowledge_base.md").read_text(encoding="utf-8")

    assert node["claim_level"] == "accepted_ts"
    assert manifest["current_accepted_ts"] == "n010_candidate"
    assert "n010_candidate" in tree["accepted_nodes"]
    candidate_records = [record for record in registry["records"] if record["node_id"] == "n010_candidate"]
    assert tree["events"][-1]["evidence_refs"] == [record["evidence_id"] for record in candidate_records]
    assert mechanism["validated_facts"][-1]["fact"] == "Unit-test accepted TS is recorded."
    assert "Unit-test connectivity evidence supports accepted_ts." in knowledge

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_plan_next_requires_explicit_alternative_mechanism_after_accepted_ts(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    tsfreq = root / "nodes" / "n010_candidate" / "parsed" / "tsfreq.json"
    connectivity = root / "nodes" / "n010_candidate" / "parsed" / "connectivity.json"
    tsfreq.write_text(
        json.dumps(
            {
                "normal_termination": True,
                "stationary_point_found": True,
                "final_convergence_satisfied": True,
                "imaginary_frequency_count": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    connectivity.write_text('{"decision": "connected", "connectivity_supported": true}\n', encoding="utf-8")
    tsfreq_evidence = {
        "kind": "gaussian_tsfreq_validation",
        "path": "nodes/n010_candidate/parsed/tsfreq.json",
        "claim": "Unit-test TS/Freq evidence supports exactly one imaginary frequency.",
        "evidence_state": "supports",
    }
    connectivity_evidence = {
        "kind": "connectivity_check",
        "path": "nodes/n010_candidate/parsed/connectivity.json",
        "claim": "Unit-test connectivity evidence supports the intended endpoints.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "accepted_ts",
        "--decision",
        "stop_search_accept_ts",
        "--summary",
        "Unit-test TS is accepted.",
        "--primary-file",
        "nodes/n010_candidate/parsed/connectivity.json",
        "--evidence",
        json.dumps(tsfreq_evidence),
        "--evidence",
        json.dumps(connectivity_evidence),
        "--computational-outcome",
        "TS/Freq and connectivity evidence passed.",
        "--mechanistic-implication",
        "The tested unit mechanism is accepted.",
        "--next-branch",
        "No further branch unless an alternative mechanism is requested.",
    )

    audit_packet = plan_next(root)
    assert audit_packet["planning_focus"]["mode"] == "accepted_audit"
    assert audit_packet["suggested_decision_cards"] == []

    alternative_packet = plan_next(root, "--alternative-mechanism")
    assert alternative_packet["planning_focus"]["mode"] == "alternative_mechanism_planning"
    assert alternative_packet["context_policy"]["mode"] == "alternative_mechanism_context"
    assert "accepted_ts_present_requires_distinct_mechanism" in alternative_packet["blocking_gates"]
    suggestion = alternative_packet["suggested_decision_cards"][0]
    assert suggestion["stage"] == "mechanism_preflight"
    assert suggestion["parent_id"] is None


def test_finalize_accepted_ts_requires_tsfreq_and_connectivity_evidence(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    connectivity = root / "nodes" / "n010_candidate" / "parsed" / "connectivity.json"
    connectivity.write_text('{"decision": "connected", "connectivity_supported": true}\n', encoding="utf-8")
    evidence = {
        "kind": "connectivity_check",
        "path": "nodes/n010_candidate/parsed/connectivity.json",
        "claim": "Unit-test TS connects the intended endpoints.",
        "evidence_state": "supports",
    }

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_cli(
            str(WORKSPACE_CLI),
            "finalize-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--claim-status",
            "accepted_ts",
            "--decision",
            "stop_search_accept_ts",
            "--summary",
            "This should not be accepted with connectivity-only evidence.",
            "--primary-file",
            "nodes/n010_candidate/parsed/connectivity.json",
            "--evidence",
            json.dumps(evidence),
            "--computational-outcome",
            "Connectivity-only evidence is incomplete.",
            "--mechanistic-implication",
            "Accepted TS requires TS/Freq and connectivity evidence.",
            "--next-branch",
            "Add missing TS/Freq validation.",
        )
    assert "missing gates: tsfreq" in exc_info.value.stderr


def test_validator_rejects_manifest_accepted_ts_conflict(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["current_accepted_ts"] = "n010_candidate"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "manifest_accepted_claim_conflict" in codes
    assert "manifest_accepted_index_conflict" in codes


def test_validator_rejects_accepted_ts_missing_evidence_gates(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    connectivity = root / "nodes" / "n010_candidate" / "parsed" / "connectivity.json"
    connectivity.write_text('{"decision": "connected", "connectivity_supported": true}\n', encoding="utf-8")
    node_path = root / "nodes" / "n010_candidate" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node.update(
        {
            "lifecycle_state": "closed",
            "run_state": "completed",
            "claim_status": "accepted_ts",
            "outcome": "accepted",
            "claim_level": "accepted_ts",
        }
    )
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["closed_nodes"] = ["n010_candidate"]
    tree["accepted_nodes"] = ["n010_candidate"]
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["current_accepted_ts"] = "n010_candidate"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    registry_path = root / "evidence_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["records"] = [
        {
            "evidence_id": "ev_connectivity_only",
            "kind": "connectivity_check",
            "path": "nodes/n010_candidate/parsed/connectivity.json",
            "node_id": "n010_candidate",
            "claim": "Connectivity evidence exists, but TS/Freq evidence is missing.",
            "evidence_state": "supports",
            "created_at": "now",
        }
    ]
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "accepted_ts_missing_evidence_gates" in codes


def test_finalize_rejects_accepted_ts_token_only_placeholder_evidence(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    tsfreq = root / "nodes" / "n010_candidate" / "parsed" / "fake_tsfreq.json"
    connectivity = root / "nodes" / "n010_candidate" / "parsed" / "fake_connectivity.json"
    tsfreq.write_text("{}\n", encoding="utf-8")
    connectivity.write_text("{}\n", encoding="utf-8")
    tsfreq_evidence = {
        "kind": "fake_tsfreq_placeholder",
        "path": "nodes/n010_candidate/parsed/fake_tsfreq.json",
        "claim": "Placeholder file name contains tsfreq.",
        "evidence_state": "supports",
    }
    connectivity_evidence = {
        "kind": "fake_connectivity_placeholder",
        "path": "nodes/n010_candidate/parsed/fake_connectivity.json",
        "claim": "Placeholder file name contains connectivity.",
        "evidence_state": "supports",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "finalize-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--claim-status",
            "accepted_ts",
            "--decision",
            "bad_accept",
            "--summary",
            "Token-only placeholder evidence must not pass.",
            "--primary-file",
            "nodes/n010_candidate/parsed/fake_connectivity.json",
            "--evidence",
            json.dumps(tsfreq_evidence),
            "--evidence",
            json.dumps(connectivity_evidence),
            "--computational-outcome",
            "No parsed Gaussian or connectivity metrics supplied.",
            "--mechanistic-implication",
            "No chemical validation supplied.",
            "--next-branch",
            "Add real validation summaries.",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "missing gates" in result.stderr


def test_validator_rejects_candidate_without_endpoint_gate(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--reaction-class",
        "bond_switch",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--stage",
        "candidate_generation",
        "--hypothesis",
        "Candidate branch lacks endpoint readiness.",
        "--operation",
        "unit-test-candidate-generation",
    )
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    run_cli(
        str(WORKSPACE_CLI),
        "add-evidence",
        "--root",
        str(root),
        "--kind",
        "parsed_summary",
        "--path",
        "nodes/n010_candidate/parsed/summary.json",
        "--node-id",
        "n010_candidate",
        "--claim",
        "Candidate exists.",
        "--evidence-state",
        "candidate_found",
    )
    node_path = root / "nodes" / "n010_candidate" / "node.json"
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
    tree["closed_nodes"] = ["n010_candidate"]
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "candidate_without_endpoint_gate" in codes


def test_decision_card_rejects_self_parent(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "decision-card",
            "--root",
            str(root),
            "--node-id",
            "n020_self",
            "--parent-id",
            "n020_self",
            "--stage",
            "candidate_generation",
            "--hypothesis",
            "Self-parent must fail.",
            "--operation",
            "unit-test",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "own parent" in result.stderr


def test_validator_rejects_parent_cycle_and_current_best(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["nodes"]["n005_endpoint_gate"]["parent_id"] = "n010_candidate"
    tree["current_best"] = "n010_candidate:cand_001"
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    node_path = root / "nodes" / "n005_endpoint_gate" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["parent_id"] = "n010_candidate"
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "parent_cycle" in codes
    assert "legacy_tree_top_level_fields" in codes


def test_decision_card_force_uses_unique_prepare_event_ids(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    for _ in range(2):
        run_cli(
            str(WORKSPACE_CLI),
            "decision-card",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--parent-id",
            "n005_endpoint_gate",
            "--stage",
            "candidate_generation",
            "--hypothesis",
            "A forced refresh should not duplicate event ids.",
            "--operation",
            "unit-test-candidate-generation",
            "--force",
        )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    event_ids = [event["event_id"] for event in tree["events"]]
    assert len(event_ids) == len(set(event_ids))
    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_validator_rejects_duplicate_timeline_event_ids(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["events"].append(dict(tree["events"][0]))
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace_allow_errors(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "duplicate_event_id" in codes


def test_start_node_marks_active_frontier(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    run_cli(
        str(WORKSPACE_CLI),
        "start-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--run-state",
        "running",
        "--decision",
        "start_unit_job",
        "--summary",
        "Unit-test job is running.",
        "--primary-file",
        "nodes/n010_candidate/decision_card.md",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))

    assert node["lifecycle_state"] == "active"
    assert node["run_state"] == "running"
    assert node["claim_status"] == "not_evaluated"
    assert tree["active_frontier"] == ["n010_candidate"]
    assert tree["events"][-1]["event_type"] == "start_node"

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_validator_warns_when_tree_parent_index_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    node_path = root / "nodes" / "n010_candidate" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["parent_id"] = "n000_parent"
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["nodes"]["n010_candidate"].pop("parent_id", None)
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n000_parent",
        "--stage",
        "mechanism_preflight",
        "--hypothesis",
        "Unit-test parent branch.",
        "--operation",
        "unit-test-parent",
    )

    validation = validate_workspace(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "tree_parent_missing" in codes


def test_decision_card_records_input_refs_as_dependency_edges(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n020_endpoint_product",
        "--stage",
        "endpoint_optimization",
        "--parent-id",
        "n010_candidate",
        "--hypothesis",
        "Product endpoint is optimized before QST2.",
        "--operation",
        "unit-test-product-endpoint",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n100_qst2",
        "--stage",
        "gaussian_tsfreq_validation",
        "--parent-id",
        "n020_endpoint_product",
        "--input-ref",
        "n010_candidate",
        "--input-ref",
        "n020_endpoint_product",
        "--input-ref",
        "n010_candidate",
        "--hypothesis",
        "QST2 depends on both optimized endpoints.",
        "--operation",
        "gaussian-qst2",
    )

    node = json.loads((root / "nodes" / "n100_qst2" / "node.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert node["input_refs"] == ["n010_candidate", "n020_endpoint_product"]
    assert tree["nodes"]["n100_qst2"]["input_refs"] == ["n010_candidate", "n020_endpoint_product"]

    graph = normalize_workspace(root)
    dependency_edges = {
        (edge["source"], edge["target"])
        for edge in graph["edges"]
        if edge.get("kind") == "dependency"
    }
    assert ("n010_candidate", "n100_qst2") in dependency_edges
    assert ("n020_endpoint_product", "n100_qst2") in dependency_edges

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_decision_card_writes_node_scoped_artifact_policy(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    assert node["artifact_policy"] == {
        "input_dir": "nodes/n010_candidate/inputs",
        "output_dir": "nodes/n010_candidate/outputs",
        "run_cwd": "nodes/n010_candidate/outputs",
        "scratch_dir": "nodes/n010_candidate/scratch",
        "engine_outputs": "write engine logs, checkpoints, restart files, trajectories, and candidates under output_dir or scratch_dir, never workspace root",
    }

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_validator_warns_for_root_engine_artifacts_and_bad_checkpoint_paths(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    (root / "stray.chk").write_text("checkpoint should not be at root\n", encoding="utf-8")
    (root / "candidate.run_metadata.txt").write_text("metadata should not be at root\n", encoding="utf-8")
    (root / "xtbopt.xyz").write_text("3\nbad root xtb artifact\nH 0 0 0\nH 0 0 1\nH 0 1 0\n", encoding="utf-8")
    input_path = root / "nodes" / "n010_candidate" / "inputs" / "candidate.gjf"
    input_path.write_text("%chk=outputs/candidate.chk\n#p opt freq\n\n", encoding="utf-8")
    escaping_input_path = root / "nodes" / "n010_candidate" / "inputs" / "escaping.gjf"
    escaping_input_path.write_text("%chk=../escaped.chk\n#p opt freq\n\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_CLI), "--source", str(root), "--pretty"],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    validation = json.loads(result.stdout)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "engine_artifact_at_workspace_root" in codes
    assert "gaussian_checkpoint_not_run_cwd_relative" in codes
    assert "gaussian_checkpoint_escapes_run_cwd" in codes


def test_validator_rejects_missing_input_ref(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n100_qst2",
        "--stage",
        "gaussian_tsfreq_validation",
        "--parent-id",
        "n010_candidate",
        "--hypothesis",
        "Broken dependency should be rejected by the validator.",
        "--operation",
        "gaussian-qst2",
    )
    node_path = root / "nodes" / "n100_qst2" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["input_refs"] = ["n999_missing_endpoint"]
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["nodes"]["n100_qst2"]["input_refs"] = ["n999_missing_endpoint"]
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_CLI), "--source", str(root), "--pretty"],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    validation = json.loads(result.stdout)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "missing_input_ref" in codes


def test_completed_preflight_has_single_node_state_label(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n000_mechanism_preflight",
        "--stage",
        "mechanism_preflight",
        "--hypothesis",
        "Mechanism preflight records the initial reaction-center hypothesis.",
        "--operation",
        "mechanism-preflight",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n000_mechanism_preflight",
        "--claim-status",
        "not_evaluated",
        "--decision",
        "prepare_endpoint_optimization",
        "--summary",
        "Preflight completed; no TS validation claim exists.",
        "--primary-file",
        "nodes/n000_mechanism_preflight/decision_card.md",
        "--computational-outcome",
        "Mechanism preflight completed.",
        "--mechanistic-implication",
        "Endpoint optimization is the next evidence gate.",
        "--next-branch",
        "Optimize endpoint references.",
    )

    graph = normalize_workspace(root)
    by_id = {node["id"]: node for node in graph["nodes"]}
    node_view = by_id["n000_mechanism_preflight"]
    assert node_view["claim_status"] == "not_evaluated"
    assert node_view["run_state"] == "completed"
    assert node_view["node_state"] == "preflight_complete"
    assert node_view["state_label"] == "preflight complete"
    assert node_view["state_line"] == "preflight complete"
    assert "claim_label" not in node_view
    assert "outcome_label" not in node_view
    assert "run_label" not in node_view


def test_finalize_replaces_running_badge_instead_of_preserving_it(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)

    run_cli(
        str(WORKSPACE_CLI),
        "start-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--run-state",
        "running",
        "--decision",
        "start_unit_job",
        "--summary",
        "Unit-test job is running.",
        "--primary-file",
        "nodes/n010_candidate/decision_card.md",
    )
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "candidate_found",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Candidate generated.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Candidate generation completed.",
        "--mechanistic-implication",
        "Candidate-only evidence.",
        "--next-branch",
        "Gaussian validation.",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    assert node["run_state"] == "completed"
    assert node["display"]["badges"] == []


def test_tsfreq_uses_single_node_state_label(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "tsfreq.json"
    parsed.write_text('{"imaginary_frequencies": 1}\n', encoding="utf-8")
    evidence = {
        "kind": "gaussian_tsfreq_parse",
        "path": "nodes/n010_candidate/parsed/tsfreq.json",
        "claim": "Unit-test Gaussian TS/Freq has exactly one imaginary frequency.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "tsfreq_validated",
        "--decision",
        "prepare_connectivity_validation",
        "--summary",
        "TS/Freq evidence passed, connectivity is not proven.",
        "--primary-file",
        "nodes/n010_candidate/parsed/tsfreq.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "TS/Freq validation completed.",
        "--mechanistic-implication",
        "Connectivity still needs explicit checking.",
        "--next-branch",
        "Run connectivity validation.",
    )

    graph = normalize_workspace(root)
    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id["n010_candidate"]["node_state"] == "freq_ok"
    assert by_id["n010_candidate"]["state_line"] == "freq ok"


def test_gaussian_file_notes_explain_unsynced_checkpoints(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    input_dir = root / "nodes" / "n010_candidate" / "inputs"
    input_dir.mkdir(exist_ok=True)
    (input_dir / "reactant_optfreq.gjf").write_text(
        "%chk=reactant_optfreq.chk\n%oldchk=/remote/run/previous.chk\n#p opt freq\n\n",
        encoding="utf-8",
    )

    notes = infer_gaussian_file_notes(root, "n010_candidate", [])
    checkpoints = {note["checkpoint"] for note in notes}
    assert checkpoints == {"reactant_optfreq.chk", "previous.chk"}
    assert all("local explorer mirrors usually omit .chk files" in note["message"] for note in notes)

    notes = infer_gaussian_file_notes(
        root,
        "n010_candidate",
        [{"name": "reactant_optfreq.chk"}],
    )
    assert [note["checkpoint"] for note in notes] == ["previous.chk"]


def test_explorer_ui_keeps_workspace_switcher_out_of_left_sidebar() -> None:
    html = (SKILL_ROOT / "src" / "transition_state_workflow" / "web" / "static" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "topbar workspace chip is the canonical switcher" in html
    assert "pathwayStatusForWorkspace" in html
    assert "Mechanism Analysis" in html
    assert "flattenMechanismAnalysis" in html
    assert "section.hidden = true" in html
    assert "generated_from_backtrack_event_ids" in html


def test_finalize_derives_outcome_and_claim_level(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")

    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "candidate_found",
    }
    # No --outcome: it must be derived from the successful claim status.
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Candidate generated; outcome and claim level are derived.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Candidate generation completed.",
        "--mechanistic-implication",
        "Candidate-only evidence.",
        "--next-branch",
        "Gaussian validation.",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    assert node["outcome"] == "candidate_generated"
    assert node["claim_level"] == "candidate_only"

    graph = normalize_workspace(root)
    by_id = {n["id"]: n for n in graph["nodes"]}
    node_view = by_id["n010_candidate"]
    # Server-side presentation: one derived node_state label/color, with raw
    # claim/outcome fields retained only as audit data.
    assert node_view["node_state"] == "candidate"
    assert node_view["state_label"] == "candidate"
    assert node_view["color"] == "accent"
    assert node_view["state_line"] == "candidate"
    assert set(graph["presentation"]) == {"node_state", "evidence_state", "workspace_state"}
    # Timeline must be sorted by time ascending regardless of array storage order.
    times = [e["time"] for e in graph["events"] if e.get("time")]
    assert times == sorted(times)


def test_rejected_requires_explicit_outcome(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": false}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test rejection evidence.",
        "evidence_state": "refutes",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "finalize-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--claim-status",
            "rejected",
            "--decision",
            "backtrack",
            "--summary",
            "Rejected without outcome must fail.",
            "--primary-file",
            "nodes/n010_candidate/parsed/summary.json",
            "--evidence",
            json.dumps(evidence),
            "--computational-outcome",
            "n/a",
            "--mechanistic-implication",
            "n/a",
            "--next-branch",
            "n/a",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "--outcome is required" in result.stderr


def test_init_registers_workspace_in_explorer_registry(tmp_path: Path) -> None:
    default_root = tmp_path / "tssearch_default"
    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(default_root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
    )
    default_checklist = (default_root / "reports" / "explorer_launch_checklist.md").read_text(encoding="utf-8")
    assert "registration skipped" in default_checklist

    root = tmp_path / "tssearch_unit"
    registry = tmp_path / "registry" / "workspaces.json"
    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--explorer-registry",
        str(registry),
    )
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert payload["schema"] == "ts-explorer-workspaces-v1"
    assert payload["workspaces"][0]["source"] == str(root.resolve())
    assert payload["workspaces"][0]["id"].startswith("tssearch-unit-")
    checklist = (root / "reports" / "explorer_launch_checklist.md").read_text(encoding="utf-8")
    assert "persistent" in checklist

    # Re-initializing must update in place, not append a duplicate.
    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--explorer-registry",
        str(registry),
        "--force",
    )
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert len(payload["workspaces"]) == 1


def test_finalize_rejects_conflicting_outcome_for_success_claim(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "supports",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "finalize-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--claim-status",
            "candidate_found",
            "--outcome",
            "accepted",
            "--decision",
            "bad_outcome",
            "--summary",
            "Conflicting outcome must fail.",
            "--primary-file",
            "nodes/n010_candidate/parsed/summary.json",
            "--evidence",
            json.dumps(evidence),
            "--computational-outcome",
            "n/a",
            "--mechanistic-implication",
            "n/a",
            "--next-branch",
            "n/a",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "must not override derived outcome" in result.stderr


def test_validator_rejects_claim_outcome_conflict(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    node_path = root / "nodes" / "n010_candidate" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node.update(
        {
            "lifecycle_state": "closed",
            "run_state": "completed",
            "claim_status": "candidate_found",
            "outcome": "accepted",
            "claim_level": "candidate_only",
        }
    )
    node_path.write_text(json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tree_path = root / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["closed_nodes"] = ["n010_candidate"]
    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_CLI), "--source", str(root), "--pretty"],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    validation = json.loads(result.stdout)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "claim_outcome_conflict" in codes


def test_start_node_force_rejects_evaluated_node(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "summary.json"
    parsed.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": "nodes/n010_candidate/parsed/summary.json",
        "claim": "Unit-test candidate summary exists.",
        "evidence_state": "candidate_found",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        "Candidate generated.",
        "--primary-file",
        "nodes/n010_candidate/parsed/summary.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Candidate generation completed.",
        "--mechanistic-implication",
        "Candidate-only evidence.",
        "--next-branch",
        "Gaussian validation.",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "start-node",
            "--root",
            str(root),
            "--node-id",
            "n010_candidate",
            "--force",
            "--decision",
            "restart",
            "--summary",
            "Should fail.",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "refuses to restart an evaluated node" in result.stderr


def test_endpoint_minima_ready_is_valid_non_ts_state(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    initialize_workspace(root)
    parsed = root / "nodes" / "n010_candidate" / "parsed" / "endpoint_summary.json"
    parsed.write_text('{"reactant_minimum": true, "product_minimum": true}\n', encoding="utf-8")

    evidence = {
        "kind": "endpoint_minima_summary",
        "path": "nodes/n010_candidate/parsed/endpoint_summary.json",
        "claim": "Unit-test endpoint minima are ready for candidate generation.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n010_candidate",
        "--claim-status",
        "endpoint_minima_ready",
        "--decision",
        "prepare_candidate_generation",
        "--summary",
        "Endpoint minima are validated; no TS connectivity claim is made.",
        "--primary-file",
        "nodes/n010_candidate/parsed/endpoint_summary.json",
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Endpoint minima checks passed in the unit-test workspace.",
        "--mechanistic-implication",
        "The endpoint references are ready for candidate generation, not accepted TS connectivity.",
        "--knowledge-update",
        "Validated facts: unit-test endpoint minima are ready.",
        "--next-branch",
        "Run candidate generation.",
    )

    node = json.loads((root / "nodes" / "n010_candidate" / "node.json").read_text(encoding="utf-8"))
    assert node["claim_status"] == "endpoint_minima_ready"
    assert node["outcome"] == "endpoint_minima_validated"
    assert node["claim_level"] == "none"

    validation = validate_workspace(root, strict=True)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0
