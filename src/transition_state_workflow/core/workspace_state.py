"""Core TS-search workspace state writers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from transition_state_workflow.base.pathway_model import initialize_pathway_model_if_missing, validate_pathway_step_reference
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import relative_path_or_absolute
from transition_state_workflow.core.workspace import (
    BranchReferenceError,
    DEFAULT_PREFLIGHT_NODE_ID,
    append_portable_evidence_record,
    clean_optional_node_ref,
    ensure_workspace_root_has_manifest_and_tree,
    normalize_branch_input_refs,
    utc_timestamp,
    validate_branch_references,
    write_initial_workspace_files,
    write_mechanism_preflight_node,
    write_prepared_branch_state,
    write_text_file_if_allowed,
)


def initialize_ts_hypothesis_workspace_files_from_cli_args(args: argparse.Namespace) -> Path:
    """Create the root v2 files for a chemistry-hypothesis TS workspace."""

    root = initialize_ts_hypothesis_workspace_files(
        root=args.root,
        system=args.system,
        charge=args.charge,
        multiplicity=args.multiplicity,
        reaction_class=args.reaction_class,
        key_atoms=tuple(args.key_atoms or ()),
        bond_changes=tuple(args.bond_change or ()),
        force=bool(args.force),
    )
    if bool(getattr(args, "with_preflight_node", False)):
        write_mechanism_preflight_node(
            root=root,
            node_id=DEFAULT_PREFLIGHT_NODE_ID,
            force=bool(args.force),
        )
    return root


def initialize_ts_hypothesis_workspace_files(
    *,
    root: Path,
    system: str,
    charge: int,
    multiplicity: int,
    reaction_class: str,
    key_atoms: tuple[str, ...],
    bond_changes: tuple[str, ...],
    force: bool,
) -> Path:
    """Create core TS-search workspace files and return the resolved root."""

    source = root.resolve()
    now = utc_timestamp()
    write_initial_workspace_files(
        source,
        system=system,
        charge=charge,
        multiplicity=multiplicity,
        timestamp=now,
        overwrite_existing=force,
    )
    mechanism = {
        "schema": "tssearch-mechanism-model-v1",
        "system": system,
        "charge": charge,
        "multiplicity": multiplicity,
        "reaction_class": reaction_class,
        "reaction_class_confidence": "low" if reaction_class == "unknown" else "provisional",
        "key_atoms": list(key_atoms),
        "expected_bond_changes": [parse_expected_bond_change_spec(item) for item in bond_changes],
        "expected_angle_changes": [],
        "electronic_hypotheses": [],
        "analysis_plan": default_mechanism_analysis_plan(),
        "mechanism_analysis": default_mechanism_analysis(),
        "validated_facts": [],
        "refuted_hypotheses": [],
        "open_questions": [
            "Are reactant and product references true minima at the chosen charge, multiplicity, and level?",
            "Which reaction-center coordinate should define the first candidate-generation branch?",
        ],
        "tool_implications": [],
        "updated_at": now,
    }
    knowledge_base = f"""# TS Search Knowledge Base: {system}

## Current Mechanism Model

- Charge: {charge}
- Multiplicity: {multiplicity}
- Reaction class hypothesis: {reaction_class}

## Validated Facts

- None yet.

## Refuted Hypotheses

- None yet.

## Open Questions

- Are reactant and product references true minima at the chosen charge, multiplicity, and level?
- Which reaction-center coordinate should define the first candidate-generation branch?

## Next Chemical Decision

- Complete mechanism preflight and endpoint optimization before promoting any TS candidate.
"""
    write_json_object(source / "mechanism_model.json", mechanism, overwrite_existing=force)
    initialize_pathway_model_if_missing(source, system=system, timestamp=now, mode="unknown")
    write_text_file_if_allowed(source / "knowledge_base.md", knowledge_base, overwrite_existing=force)
    return source


def write_mechanism_preflight_node_from_cli_args(args: argparse.Namespace) -> str:
    """CLI adapter for creating the canonical mechanism-preflight root node."""

    return write_mechanism_preflight_node(
        root=args.root,
        node_id=args.node_id,
        force=bool(args.force),
    )


def append_ts_workspace_evidence_record_from_cli_args(args: argparse.Namespace) -> None:
    """Append one evidence registry record for a v2 workspace node."""

    append_ts_workspace_evidence_record(
        root=args.root,
        kind=args.kind,
        path=args.path,
        node_id=args.node_id,
        claim=args.claim,
        evidence_state=args.evidence_state,
    )


def append_ts_workspace_evidence_record(
    *,
    root: Path,
    kind: str,
    path: str,
    node_id: str,
    claim: str,
    evidence_state: str,
) -> str:
    """Append one evidence registry record and return its evidence id."""

    return append_portable_evidence_record(
        root=root,
        kind=kind,
        path=path,
        node_id=node_id,
        claim=claim,
        evidence_state=evidence_state,
    )


def create_ts_branch_decision_artifacts_from_cli_args(args: argparse.Namespace) -> None:
    """Create node.json and markdown templates for one planned TS branch."""

    root = args.root.resolve()
    ensure_workspace_root_has_manifest_and_tree(root)
    tree_path = root / "tree.json"
    tree = read_json_object_required(tree_path)
    nodes = dict(tree.get("nodes") or {})
    pathway_id = clean_optional_node_ref(args.pathway_id)
    step_id = clean_optional_node_ref(args.step_id)
    if bool(pathway_id) != bool(step_id):
        raise SystemExit("--pathway-id and --step-id must be provided together")
    if pathway_id:
        validate_pathway_step_reference(root, pathway_id, step_id)
    input_refs = normalize_branch_input_refs(args.input_ref or ())
    try:
        validate_branch_references(
            node_id=args.node_id,
            parent_id=args.parent_id,
            input_refs=input_refs,
            existing_nodes=nodes,
        )
    except BranchReferenceError as exc:
        raise SystemExit(str(exc)) from exc
    now = utc_timestamp()
    branch_write = write_prepared_branch_state(
        root=root,
        node_id=args.node_id,
        parent_id=args.parent_id,
        stage=args.stage,
        operation=args.operation,
        hypothesis=args.hypothesis,
        input_refs=input_refs,
        pathway_id=pathway_id,
        step_id=step_id,
        timestamp=now,
        overwrite_existing=args.force,
    )
    node_dir = branch_write.node_dir
    hypothesis_md = f"""# Hypothesis: {args.node_id}

## Chemical Hypothesis

{args.hypothesis}

## Reaction-Center Expectations

- Track the mapped reaction-center bonds, angles, fragments, spin, and charge
  observables named by this branch before promoting any scientific claim.

## Mechanism Analysis Plan / Required Diagnostics

- Reaction type: compare the branch result with the intended elementary step.
- Reaction center: record mapped forming and breaking bonds plus key angles.
- Electronic / spin / charge: confirm charge and multiplicity remain consistent.
- Orbital / population: record unavailable unless the selected output contains descriptors.
- Energy / barrier expectation: report only energies available at the selected method.

## Evidence That Would Support This Hypothesis

- Parsed output preserves the intended atom mapping and reaction-center identity.
- The result reaches the next evidence layer allowed by the workflow state model.

## Evidence That Would Refute This Hypothesis

- The structure collapses to the wrong endpoint, wrong reaction center, or a
  pose-only change that does not test the stated mechanism.
"""
    decision_card_md = f"""# TS Decision Card: {args.node_id}

## Chemical Hypothesis

{args.hypothesis}

## Why This Tool

Chosen operation/route: {args.operation}

This operation is the planned chemically meaningful test for the branch
hypothesis above; later promotion still requires the workflow evidence gates.

## Input / Dependency Nodes

{format_input_refs_markdown(input_refs)}

## Pathway Step

{format_pathway_step_markdown(pathway_id, step_id)}

## Expected Supporting Evidence

- Reaction-center geometry changes match the hypothesis.
- Electronic state, charge, and spin remain chemically consistent.

## Refutation Criteria

- Candidate collapses to an endpoint or conformer.
- Imaginary mode does not follow the intended reaction coordinate.
- Connectivity check fails against optimized references.

## Cost And Risk

- Compute cost: bounded by the selected operation and node-scoped execution plan.
- Numerical risk: convergence, parser, and engine failures must be closed as
  numerical or administrative outcomes unless they carry chemical evidence.
- Chemical risk: endpoint collapse, wrong-mode motion, or failed connectivity
  must trigger reflection and branch/backtrack planning.

## Next If Supported

- Promote only to the next validation layer allowed by evidence gates.

## Next If Refuted

- Update mechanism_model.json and branch from the closest chemically meaningful ancestor.

## Created

{now}
"""
    reflection_md = """# Reflection

## Computational Outcome

Not run yet.

## Mechanistic Implication

Pending.

## Knowledge Update

- Validated facts:
- Refuted hypotheses:
- Open questions:

## Next Branch

Pending.
"""

    write_text_file_if_allowed(node_dir / "hypothesis.md", hypothesis_md, overwrite_existing=args.force)
    write_text_file_if_allowed(node_dir / "decision_card.md", decision_card_md, overwrite_existing=args.force)
    write_text_file_if_allowed(node_dir / "reflection.md", reflection_md, overwrite_existing=args.force)


def write_suggested_decision_cards_from_plan(args: argparse.Namespace, packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize planner-suggested decision-card nodes when explicitly requested."""

    root = args.root.resolve()
    written: list[dict[str, Any]] = []
    for suggestion in packet.get("suggested_decision_cards", []):
        if not isinstance(suggestion, dict) or suggestion.get("kind") != "decision_card":
            continue
        node_id = str(suggestion.get("node_id") or "").strip()
        if not node_id:
            continue
        node_dir = root / "nodes" / node_id
        if node_dir.exists() and not args.force:
            written.append({"node_id": node_id, "status": "skipped_existing", "path": relative_path_or_absolute(root, node_dir)})
            continue
        create_ts_branch_decision_artifacts_from_cli_args(
            argparse.Namespace(
                root=root,
                node_id=node_id,
                stage=str(suggestion.get("stage") or ""),
                parent_id=suggestion.get("parent_id"),
                input_ref=list(suggestion.get("input_refs") or []),
                pathway_id=str(suggestion.get("pathway_id") or ""),
                step_id=str(suggestion.get("step_id") or ""),
                hypothesis=str(suggestion.get("hypothesis") or ""),
                operation=str(suggestion.get("operation") or ""),
                force=bool(args.force),
            )
        )
        written.append({"node_id": node_id, "status": "written", "path": relative_path_or_absolute(root, node_dir)})
    return written


def format_input_refs_markdown(input_refs: list[str]) -> str:
    """Return decision-card text for multi-input dependency nodes."""

    if not input_refs:
        return "- None recorded."
    return "\n".join(f"- `{ref}`" for ref in input_refs)


def format_pathway_step_markdown(pathway_id: str, step_id: str) -> str:
    """Return decision-card text for optional pathway metadata."""

    if not pathway_id:
        return "- None recorded."
    return f"- Pathway: `{pathway_id}`\n- Elementary step: `{step_id}`"


def parse_expected_bond_change_spec(raw: str) -> dict[str, str]:
    """Parse a role:atomA-atomB bond-change specification."""

    if ":" not in raw:
        raise SystemExit(f"bond change must be role:atomA-atomB, got {raw!r}")
    role, bond = raw.split(":", 1)
    role = role.strip()
    bond = bond.strip()
    if not role or not bond:
        raise SystemExit(f"bond change must be role:atomA-atomB, got {raw!r}")
    return {"bond": bond, "role": role}


def default_mechanism_analysis() -> dict[str, list[dict[str, object]]]:
    """Return empty structured mechanism-analysis buckets."""

    return {
        "reaction_type": [],
        "reaction_center": [],
        "electronic": [],
        "orbital": [],
        "energy": [],
    }

def default_mechanism_analysis_plan() -> dict[str, list[dict[str, object]]]:
    """Return empty hypothesis-stage analysis-plan buckets."""

    return {
        "reaction_type": [],
        "reaction_center": [],
        "electronic": [],
        "orbital": [],
        "energy": [],
    }
