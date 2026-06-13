"""Shared CLI helpers and workspace fixtures for the test suite.

Most tests drive the workflow through its scripts and assert on the resulting
on-disk artifacts. The helpers here keep that black-box style — they invoke the
real subprocess CLIs — so themed test files (test_validator, test_finalize,
test_plan_next, …) share one source of truth for workspace setup.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))


# --- Script paths -------------------------------------------------------

WORKSPACE_CLI = SKILL_ROOT / "scripts" / "ts_hypothesis_workspace.py"
VALIDATOR_CLI = SKILL_ROOT / "scripts" / "ts_validate_workspace.py"
NORMALIZER_CLI = SKILL_ROOT / "scripts" / "ts_normalize_view.py"
REMOTE_GAUSSIAN_CLI = SKILL_ROOT / "scripts" / "run_remote_gaussian.py"
REMOTE_STATUS_CLI = SKILL_ROOT / "scripts" / "ts_remote_status.py"
REMOTE_TAIL_CLI = SKILL_ROOT / "scripts" / "ts_remote_tail.py"
REMOTE_FETCH_CLI = SKILL_ROOT / "scripts" / "ts_remote_fetch.py"
IMAGINARY_MODE_CLI = SKILL_ROOT / "scripts" / "ts_imaginary_mode_follow.py"
NODE_EXEC_CLI = SKILL_ROOT / "scripts" / "ts_node_exec.py"


# --- Subprocess helpers -------------------------------------------------

def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a CLI script with ``check=True`` and capture both streams."""

    return subprocess.run(
        [sys.executable, *args],
        check=True,
        text=True,
        capture_output=True,
    )


def validate_workspace(root: Path, *, strict: bool = False) -> dict[str, object]:
    args = [str(VALIDATOR_CLI), "--source", str(root), "--pretty"]
    if strict:
        args.append("--strict")
    result = run_cli(*args)
    return json.loads(result.stdout)


def validate_workspace_allow_errors(root: Path) -> dict[str, object]:
    """Run the validator with ``check=False`` so non-zero exits don't raise."""

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_CLI), "--source", str(root), "--pretty"],
        check=False,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def normalize_workspace(root: Path) -> dict[str, object]:
    result = run_cli(str(NORMALIZER_CLI), "--source", str(root), "--pretty")
    return json.loads(result.stdout)


def plan_next(root: Path, *extra_args: str) -> dict[str, object]:
    result = run_cli(
        str(WORKSPACE_CLI), "plan-next", "--root", str(root), "--pretty", *extra_args
    )
    return json.loads(result.stdout)


# --- Workspace builders -------------------------------------------------

def initialize_empty_workspace(root: Path) -> None:
    """Initialize a workspace with no decision cards or finalized nodes."""

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


def initialize_workspace(root: Path) -> None:
    """Initialize a workspace with the endpoint gate finalized + n010 prepared."""

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
    assert (root / "reports" / "explorer_launch_checklist.md").exists()
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n005_endpoint_gate",
        "--stage",
        "endpoint_minima_validation",
        "--hypothesis",
        "Reactant and product endpoint references are ready for candidate generation.",
        "--operation",
        "unit-test-endpoint-minima",
    )
    endpoint_summary = root / "nodes" / "n005_endpoint_gate" / "parsed" / "endpoint_summary.json"
    endpoint_summary.write_text(
        '{"reactant_minimum": true, "product_minimum": true, "endpoint_minima_ready": true}\n',
        encoding="utf-8",
    )
    endpoint_evidence = {
        "kind": "endpoint_minima_summary",
        "path": "nodes/n005_endpoint_gate/parsed/endpoint_summary.json",
        "claim": "Unit-test endpoint minima are ready for candidate generation.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n005_endpoint_gate",
        "--claim-status",
        "endpoint_minima_ready",
        "--decision",
        "prepare_candidate_generation",
        "--summary",
        "Endpoint references are ready for candidate generation.",
        "--primary-file",
        "nodes/n005_endpoint_gate/parsed/endpoint_summary.json",
        "--evidence",
        json.dumps(endpoint_evidence),
        "--computational-outcome",
        "Endpoint minima checks passed in the unit-test workspace.",
        "--mechanistic-implication",
        "Endpoint references can support candidate generation.",
        "--knowledge-update",
        "Validated facts: unit-test endpoint minima are ready.",
        "--next-branch",
        "Run candidate generation.",
    )
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
        "A small candidate-generation test branch exists.",
        "--operation",
        "unit-test-candidate-generation",
    )


def initialize_pathway_workspace(root: Path) -> None:
    """Initialize a multi-step pathway workspace (p001: R -> I -> P)."""

    initialize_empty_workspace(root)
    run_cli(
        str(WORKSPACE_CLI),
        "pathway-init",
        "--root",
        str(root),
        "--mode",
        "multi_step",
        "--pathway-id",
        "p001",
        "--label",
        "R to P through I",
        "--step",
        "s1:R->I",
        "--step",
        "s2:I->P",
    )


def create_pathway_endpoint_node(
    root: Path, *, node_id: str, step_id: str, parent_id: str | None = None
) -> None:
    args = [
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--stage",
        "endpoint_minima_validation",
        "--hypothesis",
        f"Endpoint references are ready for pathway step {step_id}.",
        "--operation",
        "unit-test-pathway-endpoint",
        "--pathway-id",
        "p001",
        "--step-id",
        step_id,
    ]
    if parent_id:
        args.extend(["--parent-id", parent_id])
    run_cli(*args)
    summary = root / "nodes" / node_id / "parsed" / "endpoint_summary.json"
    summary.write_text('{"endpoint_minima_ready": true}\n', encoding="utf-8")
    evidence = {
        "kind": "endpoint_minima_summary",
        "path": f"nodes/{node_id}/parsed/endpoint_summary.json",
        "claim": f"Endpoint references are ready for pathway step {step_id}.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--claim-status",
        "endpoint_minima_ready",
        "--decision",
        "prepare_candidate_generation",
        "--summary",
        f"Endpoint references are ready for pathway step {step_id}.",
        "--primary-file",
        f"nodes/{node_id}/parsed/endpoint_summary.json",
        "--pathway-id",
        "p001",
        "--step-id",
        step_id,
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Endpoint minima checks passed in the unit-test pathway workspace.",
        "--mechanistic-implication",
        "Endpoint references can support candidate generation for this pathway step.",
        "--next-branch",
        "Run candidate generation for this pathway step.",
    )


def create_pathway_candidate_node(
    root: Path, *, node_id: str, step_id: str, parent_id: str
) -> None:
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--parent-id",
        parent_id,
        "--stage",
        "candidate_generation",
        "--hypothesis",
        f"A candidate exists for pathway step {step_id}.",
        "--operation",
        "unit-test-pathway-candidate",
        "--pathway-id",
        "p001",
        "--step-id",
        step_id,
    )
    summary = root / "nodes" / node_id / "parsed" / "candidate.json"
    summary.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": f"nodes/{node_id}/parsed/candidate.json",
        "claim": f"Candidate generation supports pathway step {step_id}.",
        "evidence_state": "candidate_found",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--claim-status",
        "candidate_found",
        "--decision",
        "prepare_gaussian_validation",
        "--summary",
        f"Candidate exists for pathway step {step_id}.",
        "--primary-file",
        f"nodes/{node_id}/parsed/candidate.json",
        "--pathway-id",
        "p001",
        "--step-id",
        step_id,
        "--evidence",
        json.dumps(evidence),
        "--computational-outcome",
        "Candidate generation completed in the unit-test pathway workspace.",
        "--mechanistic-implication",
        "The pathway step needs TS/Freq validation.",
        "--next-branch",
        "Run Gaussian TS/Freq validation for this pathway step.",
    )


def finalize_pathway_candidate_as_accepted(root: Path, *, node_id: str, step_id: str) -> None:
    tsfreq = root / "nodes" / node_id / "parsed" / "tsfreq.json"
    connectivity = root / "nodes" / node_id / "parsed" / "connectivity.json"
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
        "path": f"nodes/{node_id}/parsed/tsfreq.json",
        "claim": f"TS/Freq evidence supports accepted TS for pathway step {step_id}.",
        "evidence_state": "supports",
    }
    connectivity_evidence = {
        "kind": "connectivity_check",
        "path": f"nodes/{node_id}/parsed/connectivity.json",
        "claim": f"Connectivity evidence supports accepted TS for pathway step {step_id}.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--claim-status",
        "accepted_ts",
        "--decision",
        "accept_pathway_step_ts",
        "--summary",
        f"Pathway step {step_id} has an accepted TS.",
        "--primary-file",
        f"nodes/{node_id}/parsed/connectivity.json",
        "--pathway-id",
        "p001",
        "--step-id",
        step_id,
        "--evidence",
        json.dumps(tsfreq_evidence),
        "--evidence",
        json.dumps(connectivity_evidence),
        "--computational-outcome",
        "TS/Freq and connectivity evidence passed for this pathway step.",
        "--mechanistic-implication",
        "This elementary step is accepted, but the full pathway may still be incomplete.",
        "--next-branch",
        "Continue to the next incomplete pathway step.",
    )


def create_failed_irc_branch_for_planner(root: Path) -> None:
    """Build a candidate -> tsfreq -> failed_irc chain used by planner/backtrack tests.

    Assumes :func:`initialize_workspace` ran first so ``n010_candidate`` exists.
    """

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
        "n020_tsfreq",
        "--parent-id",
        "n010_candidate",
        "--stage",
        "gaussian_tsfreq_validation",
        "--hypothesis",
        "The unit-test candidate is a frequency-validated TS.",
        "--operation",
        "unit-test-gaussian-tsfreq",
    )
    tsfreq_summary = root / "nodes" / "n020_tsfreq" / "parsed" / "tsfreq.json"
    tsfreq_summary.write_text(
        '{"status": "validated_ts", "imaginary_frequency_count": 1}\n',
        encoding="utf-8",
    )
    tsfreq_evidence = {
        "kind": "gaussian_tsfreq_validation",
        "path": "nodes/n020_tsfreq/parsed/tsfreq.json",
        "claim": "Unit-test TS/Freq validation passed.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n020_tsfreq",
        "--claim-status",
        "tsfreq_validated",
        "--decision",
        "prepare_connectivity_validation",
        "--summary",
        "Unit-test TS/Freq validation passed.",
        "--primary-file",
        "nodes/n020_tsfreq/parsed/tsfreq.json",
        "--evidence",
        json.dumps(tsfreq_evidence),
        "--computational-outcome",
        "TS/Freq validation completed.",
        "--mechanistic-implication",
        "Connectivity still needs validation.",
        "--next-branch",
        "Run connectivity validation.",
    )
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n030_failed_irc",
        "--parent-id",
        "n020_tsfreq",
        "--stage",
        "irc_connectivity_validation",
        "--hypothesis",
        "IRC should connect the intended endpoints.",
        "--operation",
        "unit-test-irc",
    )
    irc_summary = root / "nodes" / "n030_failed_irc" / "parsed" / "irc.json"
    irc_summary.write_text('{"error": "L123 corrector failure"}\n', encoding="utf-8")
    irc_evidence = {
        "kind": "irc_output_summary",
        "path": "nodes/n030_failed_irc/parsed/irc.json",
        "claim": "Unit-test IRC failed before endpoint connectivity could be accepted.",
        "evidence_state": "ambiguous",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "finalize-node",
        "--root",
        str(root),
        "--node-id",
        "n030_failed_irc",
        "--claim-status",
        "ambiguous",
        "--outcome",
        "parser_refused",
        "--outcome-code",
        "irc_l123_failure",
        "--run-state",
        "error",
        "--decision",
        "backtrack_to_endpoint_gate",
        "--summary",
        "Unit-test IRC branch failed and needs replanning from an earlier decision.",
        "--primary-file",
        "nodes/n030_failed_irc/parsed/irc.json",
        "--evidence",
        json.dumps(irc_evidence),
        "--computational-outcome",
        "IRC failed with a unit-test L123 error.",
        "--mechanistic-implication",
        "The IRC branch cannot support irc_connected.",
        "--next-branch",
        "Return to the endpoint gate and generate a chemically distinct candidate.",
    )
