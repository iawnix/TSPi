"""Core TS-search workspace state writers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from transition_state_workflow.base.pathway_model import initialize_pathway_model_if_missing, validate_pathway_step_reference
from transition_state_workflow.core.backtrack import BacktrackRequest, active_backtrack_events, record_backtrack
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import clean_string, relative_path_or_absolute
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
    replaces_node = clean_optional_node_ref(getattr(args, "replaces_node", ""))
    parent_id = clean_optional_node_ref(args.parent_id)
    if replaces_node and not parent_id:
        raise SystemExit("--replaces-node requires --parent-id as the chemically meaningful backtrack target")
    if replaces_node:
        if replaces_node not in nodes:
            raise SystemExit(f"--replaces-node does not exist in tree.json nodes: {replaces_node}")
        active_backtracks = active_backtrack_events(tree)
        if active_backtracks and not bool(getattr(args, "supersede_active_backtrack", False)):
            active_ids = ", ".join(
                clean_string(item.get("id"))
                for item in active_backtracks
                if clean_string(item.get("id"))
            )
            raise SystemExit(
                "active backtrack event already exists"
                + (f": {active_ids}" if active_ids else "")
                + "; mark it resolved/superseded or rerun with --supersede-active-backtrack"
            )
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
    decision_provenance = build_decision_provenance(
        args=args,
        parent_id=parent_id,
        input_refs=input_refs,
        replaces_node=replaces_node,
        pathway_id=pathway_id,
        step_id=step_id,
    )
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
        decision_provenance=decision_provenance,
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

## Decision Provenance

{format_decision_provenance_markdown(decision_provenance)}

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
    if replaces_node:
        reason = clean_string(getattr(args, "backtrack_reason", "")) or (
            f"Branch {args.node_id} replaces failed or ambiguous branch {replaces_node} "
            f"under ancestor {parent_id}."
        )
        record_backtrack(
            BacktrackRequest(
                root=root,
                from_node=replaces_node,
                to_node=parent_id,
                new_branch_node=args.node_id,
                reason_code=clean_string(getattr(args, "backtrack_reason_code", "")) or "replacement_branch",
                reason=reason,
                evidence_refs=tuple(getattr(args, "backtrack_evidence_ref", ()) or ()),
                decision=f"replace_{replaces_node}_with_{args.node_id}",
                supersede_active=bool(getattr(args, "supersede_active_backtrack", False)),
            )
        )


def build_decision_provenance(
    *,
    args: argparse.Namespace,
    parent_id: str,
    input_refs: list[str],
    replaces_node: str,
    pathway_id: str,
    step_id: str,
) -> dict[str, Any]:
    """Build the structured agent-owned decision provenance record."""

    changed_variables = parse_changed_variables(getattr(args, "changed_variable", ()) or ())
    if "operation" not in changed_variables:
        changed_variables["operation"] = clean_string(args.operation)
    if pathway_id and step_id:
        changed_variables.setdefault("pathway_step", f"{pathway_id}:{step_id}")
    evidence_refs = [clean_string(item) for item in getattr(args, "evidence_ref", ()) or () if clean_string(item)]
    trigger_source = clean_string(getattr(args, "trigger_source", "")) or (
        f"replacement_for:{replaces_node}" if replaces_node else "agent_cli_decision_card"
    )
    parent_reason = clean_string(getattr(args, "parent_selection_reason", "")) or default_parent_selection_reason(parent_id)
    method_rationale = clean_string(getattr(args, "method_or_tool_rationale", "")) or (
        f"Agent selected operation `{clean_string(args.operation)}` to test the stated hypothesis under the current evidence gate."
    )
    support_criteria = clean_string_list(getattr(args, "support_criteria", ()) or ()) or [
        "Parsed outputs support the stated reaction-center hypothesis.",
        "The result reaches no higher claim than the declared claim_ceiling.",
    ]
    refutation_criteria = clean_string_list(getattr(args, "refutation_criteria", ()) or ()) or [
        "Parsed outputs contradict the stated reaction-center hypothesis.",
        "The branch fails numerically or chemically before reaching the declared claim_ceiling.",
    ]
    return {
        "trigger_source": trigger_source,
        "parent_selection_reason": parent_reason,
        "context_packet_ref": clean_string(getattr(args, "context_packet_ref", "")) or "not_recorded",
        "evidence_refs": evidence_refs,
        "input_refs": input_refs,
        "failed_or_ambiguous_source_node": replaces_node or "not_applicable",
        "backtrack_event_ref": "created_by_replaces_node" if replaces_node else "not_applicable",
        "changed_variables": changed_variables,
        "method_or_tool_rationale": method_rationale,
        "claim_ceiling": clean_string(getattr(args, "claim_ceiling", "")) or default_claim_ceiling(clean_string(args.stage)),
        "support_criteria": support_criteria,
        "refutation_criteria": refutation_criteria,
        "cost_risk": clean_string(getattr(args, "cost_risk", "")) or "Bounded by the selected operation and node-scoped execution plan.",
        "next_if_supported": clean_string(getattr(args, "next_if_supported", "")) or "Advance only to the next workflow evidence gate.",
        "next_if_refuted": clean_string(getattr(args, "next_if_refuted", "")) or "Reflect and backtrack to the closest chemically meaningful ancestor.",
    }


def parse_changed_variables(raw_values: tuple[str, ...] | list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_value in raw_values:
        text = clean_string(raw_value)
        if not text:
            continue
        if "=" not in text:
            raise SystemExit(f"--changed-variable must use key=value form: {text}")
        key, value = text.split("=", 1)
        key = clean_string(key)
        value = clean_string(value)
        if not key or not value:
            raise SystemExit(f"--changed-variable must use non-empty key=value form: {text}")
        out[key] = value
    return out


def clean_string_list(raw_values: tuple[str, ...] | list[str]) -> list[str]:
    return [clean_string(item) for item in raw_values if clean_string(item)]


def default_parent_selection_reason(parent_id: str) -> str:
    if parent_id:
        return f"Agent selected parent node `{parent_id}` as the closest chemically meaningful ancestor for this branch."
    return "Agent selected a root branch because no parent node is required for this decision."


def default_claim_ceiling(stage: str) -> str:
    if stage == "endpoint_minima_validation" or "endpoint" in stage:
        return "endpoint_minima_ready"
    if stage == "candidate_generation":
        return "candidate_found"
    if stage == "gaussian_tsfreq_validation":
        return "tsfreq_validated"
    if stage == "connectivity_validation":
        return "endpoint_connected_or_irc_connected"
    if stage == "mechanism_preflight":
        return "not_evaluated"
    return "next_workflow_evidence_gate"


def format_decision_provenance_markdown(provenance: dict[str, Any]) -> str:
    evidence_refs = provenance.get("evidence_refs") if isinstance(provenance.get("evidence_refs"), list) else []
    input_refs = provenance.get("input_refs") if isinstance(provenance.get("input_refs"), list) else []
    changed_variables = provenance.get("changed_variables") if isinstance(provenance.get("changed_variables"), dict) else {}
    support = provenance.get("support_criteria") if isinstance(provenance.get("support_criteria"), list) else []
    refute = provenance.get("refutation_criteria") if isinstance(provenance.get("refutation_criteria"), list) else []
    lines = [
        f"- Trigger source: {clean_string(provenance.get('trigger_source'))}",
        f"- Parent selection reason: {clean_string(provenance.get('parent_selection_reason'))}",
        f"- Context packet ref: {clean_string(provenance.get('context_packet_ref'))}",
        f"- Evidence refs: {', '.join(evidence_refs) if evidence_refs else 'none'}",
        f"- Input refs: {', '.join(input_refs) if input_refs else 'none'}",
        f"- Failed or ambiguous source node: {clean_string(provenance.get('failed_or_ambiguous_source_node'))}",
        f"- Backtrack event ref: {clean_string(provenance.get('backtrack_event_ref'))}",
        f"- Changed variables: {', '.join(f'{key}={value}' for key, value in changed_variables.items())}",
        f"- Method/tool rationale: {clean_string(provenance.get('method_or_tool_rationale'))}",
        f"- Claim ceiling: {clean_string(provenance.get('claim_ceiling'))}",
        "- Support criteria:",
        *[f"  - {item}" for item in support],
        "- Refutation criteria:",
        *[f"  - {item}" for item in refute],
        f"- Cost/risk: {clean_string(provenance.get('cost_risk'))}",
        f"- Next if supported: {clean_string(provenance.get('next_if_supported'))}",
        f"- Next if refuted: {clean_string(provenance.get('next_if_refuted'))}",
    ]
    return "\n".join(lines)


def format_input_refs_markdown(input_refs: list[str]) -> str:
    """Return decision card text for multi-input dependency nodes."""

    if not input_refs:
        return "- None recorded."
    return "\n".join(f"- `{ref}`" for ref in input_refs)


def format_pathway_step_markdown(pathway_id: str, step_id: str) -> str:
    """Return decision card text for optional pathway metadata."""

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
