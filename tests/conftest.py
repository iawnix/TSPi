"""Shared CLI helpers and workspace fixtures for the test suite.

Most tests drive the workflow through its scripts and assert on the resulting
on-disk artifacts. The helpers here keep that black-box style — they invoke the
real subprocess CLIs — so themed test files (test_validator, test_finalize,
test_workspace_report, …) share one source of truth for workspace setup.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.base.pathway_model import parse_step_spec
from transition_state_workflow.config.state_contract import PATHWAY_MODEL_SCHEMA
from transition_state_workflow.core.workspace.naming import utc_timestamp


# --- Script paths -------------------------------------------------------

WORKSPACE_CLI = SKILL_ROOT / "scripts" / "ts_workspace.py"
NORMALIZER_CLI = SKILL_ROOT / "scripts" / "ts_normalize_view.py"
REMOTE_GAUSSIAN_CLI = SKILL_ROOT / "scripts" / "run_remote_gaussian.py"
REMOTE_STATUS_CLI = SKILL_ROOT / "scripts" / "ts_remote_status.py"
REMOTE_TAIL_CLI = SKILL_ROOT / "scripts" / "ts_remote_tail.py"
REMOTE_FETCH_CLI = SKILL_ROOT / "scripts" / "ts_remote_fetch.py"
REMOTE_JOB_CLI = SKILL_ROOT / "scripts" / "ts_remote_job.py"
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
    args = [str(WORKSPACE_CLI), "validate_workspace", "--root", str(root), "--pretty"]
    if strict:
        args.append("--strict")
    result = run_cli(*args)
    return json.loads(result.stdout)


def validate_workspace_allow_errors(root: Path) -> dict[str, object]:
    """Run the validator with ``check=False`` so non-zero exits don't raise."""

    result = subprocess.run(
        [sys.executable, str(WORKSPACE_CLI), "validate_workspace", "--root", str(root), "--pretty"],
        check=False,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def normalize_workspace(root: Path) -> dict[str, object]:
    result = run_cli(str(NORMALIZER_CLI), "--source", str(root), "--pretty")
    return json.loads(result.stdout)


def report_workspace(root: Path, *extra_args: str) -> dict[str, object]:
    result = run_cli(
        str(WORKSPACE_CLI), "report_workspace", "--root", str(root), "--pretty", *extra_args
    )
    return json.loads(result.stdout)


workspace_report = report_workspace


def start_node(
    root: Path,
    *,
    node_id: str,
    phase: str,
    operation: str,
    hypothesis: str,
    parent_id: str | None = None,
    pathway_id: str = "",
    step_id: str = "",
    input_refs: tuple[str, ...] = (),
    force: bool = False,
) -> None:
    args = [
        str(WORKSPACE_CLI),
        "start_node",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--phase",
        phase,
        "--operation",
        operation,
        "--hypothesis",
        hypothesis,
        "--rationale",
        f"{operation} directly tests the stated {phase} hypothesis.",
        "--expected-evidence",
        f"Parsed evidence should support or refute the {phase} hypothesis.",
        "--refutation-criteria",
        "The parsed result contradicts the expected chemistry or the program fails.",
        "--cost-risk",
        "Unit-test workspace fixture.",
        "--next-if-supported",
        "Continue to the next gated phase.",
        "--next-if-refuted",
        "Close the node and replan from report_workspace context.",
    ]
    if parent_id:
        args.extend(["--parent-id", parent_id])
    if pathway_id:
        args.extend(["--pathway-id", pathway_id])
    if step_id:
        args.extend(["--step-id", step_id])
    for input_ref in input_refs:
        args.extend(["--input-ref", input_ref])
    if force:
        args.append("--force")
    run_cli(*args)


def end_node(
    root: Path,
    *,
    node_id: str,
    phase: str,
    node_disposition: str = "Success",
    decision: str,
    summary: str,
    primary_file: str,
    evidence: dict[str, object] | tuple[dict[str, object], ...],
    pathway_id: str = "",
    step_id: str = "",
    pathway_step_status: str = "",
    next_branch: str = "Report workspace and choose the next node.",
) -> None:
    evidence_items = evidence if isinstance(evidence, tuple) else (evidence,)
    args = [
        str(WORKSPACE_CLI),
        "end_node",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--node-disposition",
        node_disposition,
        "--phase",
        phase,
        "--decision",
        decision,
        "--summary",
        summary,
        "--primary-file",
        primary_file,
        "--program-summary",
        f"{summary} Program-level evidence is recorded in {primary_file}.",
        "--program-fact",
        json.dumps(
            {
                "text": summary,
                "source_path": primary_file,
            }
        ),
        "--mechanism-summary",
        f"{summary} Mechanism implications remain scoped to the {phase} phase.",
        "--mechanism-fact",
        f"The {phase} result is a phase-scoped fact, not a whole-mechanism proof.",
        "--implication",
        next_branch,
        "--next-branch",
        next_branch,
    ]
    for item in evidence_items:
        args.extend(["--evidence", json.dumps(item)])
    if pathway_id:
        args.extend(["--pathway-id", pathway_id])
    if step_id:
        args.extend(["--step-id", step_id])
    if pathway_step_status:
        args.extend(["--pathway-step-status", pathway_step_status])
    run_cli(*args)


# --- Workspace builders -------------------------------------------------

def initialize_empty_workspace(root: Path) -> None:
    """Initialize a workspace with no decision cards or finalized nodes."""

    run_cli(
        str(WORKSPACE_CLI),
        "init_workspace",
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
        "init_workspace",
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
    start_node(
        root,
        node_id="n005_endpoint_gate",
        phase="endpoint",
        hypothesis="Reactant and product endpoint references are ready for candidate generation.",
        operation="unit-test-endpoint-minima",
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
    end_node(
        root,
        node_id="n005_endpoint_gate",
        phase="endpoint",
        decision="prepare_candidate_generation",
        summary="Endpoint references are ready for candidate generation.",
        primary_file="nodes/n005_endpoint_gate/parsed/endpoint_summary.json",
        evidence=endpoint_evidence,
        next_branch="Run candidate generation.",
    )
    start_node(
        root,
        node_id="n010_candidate",
        parent_id="n005_endpoint_gate",
        phase="candidate_generation",
        hypothesis="A small candidate-generation test branch exists.",
        operation="unit-test-candidate-generation",
    )


def initialize_pathway_workspace(root: Path) -> None:
    """Initialize a multi-step pathway workspace (p001: R -> I -> P)."""

    initialize_empty_workspace(root)
    timestamp = utc_timestamp()
    (root / "pathway_model.json").write_text(
        json.dumps(
            {
                "schema": PATHWAY_MODEL_SCHEMA,
                "system": "unit_test_system",
                "mode": "multi_step",
                "active_pathway": "p001",
                "pathways": [
                    {
                        "pathway_id": "p001",
                        "label": "R to P through I",
                        "status": "hypothesis",
                        "steps": [parse_step_spec("s1:R->I"), parse_step_spec("s2:I->P")],
                    }
                ],
                "updated_at": timestamp,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def create_pathway_endpoint_node(
    root: Path, *, node_id: str, step_id: str, parent_id: str | None = None
) -> None:
    start_node(
        root,
        node_id=node_id,
        parent_id=parent_id,
        phase="endpoint",
        hypothesis=f"Endpoint references are ready for pathway step {step_id}.",
        operation="unit-test-pathway-endpoint",
        pathway_id="p001",
        step_id=step_id,
    )
    summary = root / "nodes" / node_id / "parsed" / "endpoint_summary.json"
    summary.write_text('{"endpoint_minima_ready": true}\n', encoding="utf-8")
    evidence = {
        "kind": "endpoint_minima_summary",
        "path": f"nodes/{node_id}/parsed/endpoint_summary.json",
        "claim": f"Endpoint references are ready for pathway step {step_id}.",
        "evidence_state": "supports",
    }
    end_node(
        root,
        node_id=node_id,
        phase="endpoint",
        decision="prepare_candidate_generation",
        summary=f"Endpoint references are ready for pathway step {step_id}.",
        primary_file=f"nodes/{node_id}/parsed/endpoint_summary.json",
        evidence=evidence,
        pathway_id="p001",
        step_id=step_id,
        next_branch="Run candidate generation for this pathway step.",
    )


def create_pathway_candidate_node(
    root: Path, *, node_id: str, step_id: str, parent_id: str
) -> None:
    start_node(
        root,
        node_id=node_id,
        parent_id=parent_id,
        phase="candidate_generation",
        hypothesis=f"A candidate exists for pathway step {step_id}.",
        operation="unit-test-pathway-candidate",
        pathway_id="p001",
        step_id=step_id,
    )
    summary = root / "nodes" / node_id / "parsed" / "candidate.json"
    summary.write_text('{"candidate": true}\n', encoding="utf-8")
    evidence = {
        "kind": "parsed_summary",
        "path": f"nodes/{node_id}/parsed/candidate.json",
        "claim": f"Candidate generation supports pathway step {step_id}.",
        "evidence_state": "candidate_found",
    }
    end_node(
        root,
        node_id=node_id,
        phase="candidate_generation",
        decision="prepare_gaussian_validation",
        summary=f"Candidate exists for pathway step {step_id}.",
        primary_file=f"nodes/{node_id}/parsed/candidate.json",
        evidence=evidence,
        pathway_id="p001",
        step_id=step_id,
        next_branch="Run Gaussian TS/Freq validation for this pathway step.",
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
    end_node(
        root,
        node_id=node_id,
        phase="accepted_audit",
        decision="accept_pathway_step_ts",
        summary=f"Pathway step {step_id} has an accepted TS.",
        primary_file=f"nodes/{node_id}/parsed/connectivity.json",
        evidence=(tsfreq_evidence, connectivity_evidence),
        pathway_id="p001",
        step_id=step_id,
        next_branch="Continue to the next incomplete pathway step.",
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
    end_node(
        root,
        node_id="n010_candidate",
        phase="candidate_generation",
        decision="prepare_gaussian_validation",
        summary="Unit-test candidate exists.",
        primary_file="nodes/n010_candidate/parsed/summary.json",
        evidence=candidate_evidence,
        next_branch="Run Gaussian TS/Freq validation.",
    )
    start_node(
        root,
        node_id="n020_tsfreq",
        parent_id="n010_candidate",
        phase="tsfreq_validation",
        hypothesis="The unit-test candidate is a frequency-validated TS.",
        operation="unit-test-gaussian-tsfreq",
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
    end_node(
        root,
        node_id="n020_tsfreq",
        phase="tsfreq_validation",
        decision="prepare_connectivity_validation",
        summary="Unit-test TS/Freq validation passed.",
        primary_file="nodes/n020_tsfreq/parsed/tsfreq.json",
        evidence=tsfreq_evidence,
        next_branch="Run connectivity validation.",
    )
    start_node(
        root,
        node_id="n030_failed_irc",
        parent_id="n020_tsfreq",
        phase="connectivity_validation",
        hypothesis="IRC should connect the intended endpoints.",
        operation="unit-test-irc",
    )
    irc_summary = root / "nodes" / "n030_failed_irc" / "parsed" / "irc.json"
    irc_summary.write_text('{"error": "L123 corrector failure"}\n', encoding="utf-8")
    irc_evidence = {
        "kind": "irc_output_summary",
        "path": "nodes/n030_failed_irc/parsed/irc.json",
        "claim": "Unit-test IRC failed before endpoint connectivity could be accepted.",
        "evidence_state": "ambiguous",
    }
    end_node(
        root,
        node_id="n030_failed_irc",
        phase="connectivity_validation",
        node_disposition="Error",
        decision="backtrack_to_endpoint_gate",
        summary="Unit-test IRC branch failed and needs replanning from an earlier decision.",
        primary_file="nodes/n030_failed_irc/parsed/irc.json",
        evidence=irc_evidence,
        next_branch="Return to the endpoint gate and generate a chemically distinct candidate.",
    )
