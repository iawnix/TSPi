"""Core TS-search workspace state writers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.base.pathway_model import validate_pathway_step_reference
from transition_state_workflow.config.state_contract import WORKSPACE_NODE_SCHEMA
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import portable_record_path, relative_path_or_absolute, safe_identifier_token


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

    source = root.resolve()
    ensure_workspace_root_has_manifest_and_tree(source)
    registry_path = source / "evidence_registry.json"
    registry = read_json_object_required(registry_path)
    records = list(registry.get("records") or [])
    evidence_id = f"ev_{safe_identifier_token(node_id)}_{len(records) + 1:04d}"
    path_payload = portable_record_path(source, path)
    now = utc_timestamp()
    records.append(
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "path": path_payload["path"],
            "node_id": node_id,
            "claim": claim,
            "evidence_state": evidence_state,
            "external_path": path_payload["external_path"],
            "external_unavailable": path_payload["external_unavailable"],
            "created_at": now,
        }
    )
    registry["records"] = records
    registry["updated_at"] = utc_timestamp()
    write_json_object(registry_path, registry, overwrite_existing=True)
    return evidence_id


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
    input_refs = normalize_input_refs(args.input_ref or ())
    validate_branch_references(
        node_id=args.node_id,
        parent_id=args.parent_id,
        input_refs=input_refs,
        existing_nodes=nodes,
    )
    node_dir = root / "nodes" / args.node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "inputs").mkdir(exist_ok=True)
    (node_dir / "outputs").mkdir(exist_ok=True)
    (node_dir / "parsed").mkdir(exist_ok=True)
    (node_dir / "scratch").mkdir(exist_ok=True)
    now = utc_timestamp()

    hypothesis_rel = relative_path_or_absolute(root, node_dir / "hypothesis.md")
    decision_rel = relative_path_or_absolute(root, node_dir / "decision_card.md")
    input_dir_rel = relative_path_or_absolute(root, node_dir / "inputs")
    output_dir_rel = relative_path_or_absolute(root, node_dir / "outputs")
    scratch_dir_rel = relative_path_or_absolute(root, node_dir / "scratch")
    node_payload = {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": args.node_id,
        "parent_id": args.parent_id,
        "stage": args.stage,
        "operation": args.operation,
        "lifecycle_state": "prepared",
        "run_state": "not_started",
        "claim_status": "not_evaluated",
        "outcome": "none",
        "outcome_code": None,
        "claim_level": "none",
        "hypothesis": args.hypothesis,
        "changed_variables": {"operation": args.operation},
        "artifact_policy": {
            "input_dir": input_dir_rel,
            "output_dir": output_dir_rel,
            "run_cwd": output_dir_rel,
            "scratch_dir": scratch_dir_rel,
            "engine_outputs": "write engine logs, checkpoints, restart files, trajectories, and candidates under output_dir or scratch_dir, never workspace root",
        },
        "evidence": {
            "hypothesis": hypothesis_rel,
            "decision_card": decision_rel,
        },
        "decision": "prepared_for_execution",
        "display": {
            "title": args.node_id,
            "subtitle": args.stage,
            "badges": ["prepared"],
            "metrics": {},
            "primary_file": decision_rel,
            "summary": "Prepared branch; no job has run and no TS claim exists.",
        },
    }
    if input_refs:
        node_payload["input_refs"] = input_refs
    if pathway_id:
        node_payload["pathway_id"] = pathway_id
        node_payload["elementary_step_id"] = step_id
    hypothesis_md = f"""# Hypothesis: {args.node_id}

## Chemical Hypothesis

{args.hypothesis}

## Reaction-Center Expectations

- Fill in expected bond, angle, fragment, spin, or charge changes before execution.

## Mechanism Analysis Plan / Required Diagnostics

- Reaction type:
- Reaction center:
- Electronic / spin / charge:
- Orbital / population:
- Energy / barrier expectation:

## Evidence That Would Support This Hypothesis

- Fill in measurable criteria.

## Evidence That Would Refute This Hypothesis

- Fill in closure or backtracking criteria.
"""
    decision_card_md = f"""# TS Decision Card: {args.node_id}

## Chemical Hypothesis

{args.hypothesis}

## Why This Tool

Chosen operation/route: {args.operation}

Explain why this is the lowest-cost chemically meaningful test now.

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

- Compute cost:
- Numerical risk:
- Chemical risk:

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

    write_json_object(node_dir / "node.json", node_payload, overwrite_existing=args.force)
    write_text_file_if_allowed(node_dir / "hypothesis.md", hypothesis_md, overwrite_existing=args.force)
    write_text_file_if_allowed(node_dir / "decision_card.md", decision_card_md, overwrite_existing=args.force)
    write_text_file_if_allowed(node_dir / "reflection.md", reflection_md, overwrite_existing=args.force)

    if args.node_id not in nodes or args.force:
        tree_node_payload = {
            "parent_id": args.parent_id,
            "stage": args.stage,
            "node_path": relative_path_or_absolute(root, node_dir / "node.json"),
        }
        if input_refs:
            tree_node_payload["input_refs"] = input_refs
        if pathway_id:
            tree_node_payload["pathway_id"] = pathway_id
            tree_node_payload["elementary_step_id"] = step_id
        nodes[args.node_id] = tree_node_payload
    tree["nodes"] = nodes
    events = list(tree.get("events") or [])
    event_id = next_event_id(
        f"evt_{safe_identifier_token(args.node_id)}_prepare",
        {str(item.get("event_id") or "") for item in events if isinstance(item, dict)},
    )
    events.append(
        {
            "event_id": event_id,
            "time": now,
            "node_id": args.node_id,
            "event_type": "prepare_node",
            "decision": "prepared_for_execution",
            "reason": f"Prepared branch to test: {args.hypothesis}",
            "evidence_refs": [],
        }
    )
    tree["events"] = events
    write_json_object(tree_path, tree, overwrite_existing=True)


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


def validate_branch_references(
    *,
    node_id: str,
    parent_id: str | None,
    input_refs: list[str],
    existing_nodes: dict[str, Any],
) -> None:
    """Reject branch references that would break the hypothesis tree."""

    parent_id = clean_optional_node_ref(parent_id)
    if parent_id == node_id:
        raise SystemExit(f"node cannot be its own parent: {node_id}")
    if parent_id and parent_id not in existing_nodes:
        raise SystemExit(f"parent node does not exist in tree.json: {parent_id}")
    for input_ref in input_refs:
        if input_ref == node_id:
            raise SystemExit(f"node cannot depend on itself through --input-ref: {node_id}")
        if input_ref not in existing_nodes:
            raise SystemExit(f"input reference node does not exist in tree.json: {input_ref}")
    if parent_graph_would_cycle(node_id=node_id, parent_id=parent_id, existing_nodes=existing_nodes):
        raise SystemExit(f"parent link would create a cycle for node: {node_id}")


def parent_graph_would_cycle(*, node_id: str, parent_id: str, existing_nodes: dict[str, Any]) -> bool:
    """Return true if setting node_id -> parent_id would create a parent cycle."""

    seen = {node_id}
    current = parent_id
    while current:
        if current in seen:
            return True
        seen.add(current)
        payload = existing_nodes.get(current)
        if not isinstance(payload, dict):
            return False
        current = clean_optional_node_ref(payload.get("parent_id"))
    return False


def clean_optional_node_ref(value: object) -> str:
    """Normalize optional node references from CLI or tree JSON."""

    return str(value or "").strip()


def normalize_input_refs(raw_refs: tuple[str, ...] | list[str]) -> list[str]:
    """Return stable, de-duplicated dependency node ids from CLI input."""

    refs: list[str] = []
    for raw in raw_refs:
        ref = str(raw or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs


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


def next_event_id(base: str, taken_ids: set[str]) -> str:
    """Return an unused timeline event id based on a stable base token."""

    event_id = safe_identifier_token(base)
    if event_id not in taken_ids:
        return event_id
    index = 2
    while f"{event_id}_{index:02d}" in taken_ids:
        index += 1
    return f"{event_id}_{index:02d}"


def write_text_file_if_allowed(file_path: Path, text: str, *, overwrite_existing: bool) -> bool:
    """Write text when overwrite rules allow it."""

    if file_path.exists() and not overwrite_existing:
        return False
    file_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return True


def ensure_workspace_root_has_manifest_and_tree(root: Path) -> None:
    """Abort when root is missing the files required for a TS workspace."""

    missing = [name for name in ("manifest.json", "tree.json") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for workspace records."""

    return datetime.now(timezone.utc).isoformat()
