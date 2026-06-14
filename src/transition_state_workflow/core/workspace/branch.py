"""Prepared branch state writers for TS-search workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import WORKSPACE_NODE_SCHEMA
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import relative_path_or_absolute, safe_identifier_token


BRANCH_WORK_DIRS = ("inputs", "outputs", "parsed", "scratch")


@dataclass(frozen=True)
class PreparedBranchWrite:
    """Result of writing one prepared branch state record."""

    node_dir: Path
    node_payload: dict[str, Any]
    event_id: str


def ensure_branch_directories(root: Path, node_id: str) -> Path:
    """Create the node directory and standard branch work directories."""

    node_dir = root / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    for dirname in BRANCH_WORK_DIRS:
        (node_dir / dirname).mkdir(exist_ok=True)
    return node_dir


def prepared_branch_node_payload(
    *,
    root: Path,
    node_dir: Path,
    node_id: str,
    parent_id: str | None,
    stage: str,
    operation: str,
    hypothesis: str,
    input_refs: list[str],
    pathway_id: str,
    step_id: str,
) -> dict[str, Any]:
    """Build the prepared node.json payload for one branch."""

    hypothesis_rel = relative_path_or_absolute(root, node_dir / "hypothesis.md")
    decision_rel = relative_path_or_absolute(root, node_dir / "decision_card.md")
    input_dir_rel = relative_path_or_absolute(root, node_dir / "inputs")
    output_dir_rel = relative_path_or_absolute(root, node_dir / "outputs")
    scratch_dir_rel = relative_path_or_absolute(root, node_dir / "scratch")
    node_payload: dict[str, Any] = {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": node_id,
        "parent_id": parent_id,
        "stage": stage,
        "operation": operation,
        "lifecycle_state": "prepared",
        "run_state": "not_started",
        "claim_status": "not_evaluated",
        "outcome": "none",
        "outcome_code": None,
        "claim_level": "none",
        "hypothesis": hypothesis,
        "changed_variables": {"operation": operation},
        "artifact_policy": {
            "input_dir": input_dir_rel,
            "output_dir": output_dir_rel,
            "run_cwd": output_dir_rel,
            "scratch_dir": scratch_dir_rel,
            "engine_outputs": (
                "write engine logs, checkpoints, restart files, trajectories, and candidates under "
                "output_dir or scratch_dir, never workspace root"
            ),
        },
        "evidence": {
            "hypothesis": hypothesis_rel,
            "decision_card": decision_rel,
        },
        "decision": "prepared_for_execution",
        "display": {
            "title": node_id,
            "subtitle": stage,
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
    return node_payload


def prepared_branch_tree_entry(
    *,
    root: Path,
    node_dir: Path,
    parent_id: str | None,
    stage: str,
    input_refs: list[str],
    pathway_id: str,
    step_id: str,
) -> dict[str, Any]:
    """Build the tree.json node entry for one prepared branch."""

    tree_node_payload: dict[str, Any] = {
        "parent_id": parent_id,
        "stage": stage,
        "node_path": relative_path_or_absolute(root, node_dir / "node.json"),
    }
    if input_refs:
        tree_node_payload["input_refs"] = input_refs
    if pathway_id:
        tree_node_payload["pathway_id"] = pathway_id
        tree_node_payload["elementary_step_id"] = step_id
    return tree_node_payload


def next_branch_event_id(base: str, taken_ids: set[str]) -> str:
    """Return an unused timeline event id based on a stable base token."""

    event_id = safe_identifier_token(base)
    if event_id not in taken_ids:
        return event_id
    index = 2
    while f"{event_id}_{index:02d}" in taken_ids:
        index += 1
    return f"{event_id}_{index:02d}"


def prepared_branch_event(*, node_id: str, hypothesis: str, timestamp: str, taken_ids: set[str]) -> dict[str, Any]:
    """Build the prepare_node event payload for one branch."""

    event_id = next_branch_event_id(f"evt_{safe_identifier_token(node_id)}_prepare", taken_ids)
    return {
        "event_id": event_id,
        "time": timestamp,
        "node_id": node_id,
        "event_type": "prepare_node",
        "decision": "prepared_for_execution",
        "reason": f"Prepared branch to test: {hypothesis}",
        "evidence_refs": [],
    }


def write_prepared_branch_state(
    *,
    root: Path,
    node_id: str,
    parent_id: str | None,
    stage: str,
    operation: str,
    hypothesis: str,
    input_refs: list[str],
    pathway_id: str,
    step_id: str,
    timestamp: str,
    overwrite_existing: bool,
) -> PreparedBranchWrite:
    """Write prepared node state and tree event for one branch."""

    node_dir = ensure_branch_directories(root, node_id)
    node_payload = prepared_branch_node_payload(
        root=root,
        node_dir=node_dir,
        node_id=node_id,
        parent_id=parent_id,
        stage=stage,
        operation=operation,
        hypothesis=hypothesis,
        input_refs=input_refs,
        pathway_id=pathway_id,
        step_id=step_id,
    )
    write_json_object(node_dir / "node.json", node_payload, overwrite_existing=overwrite_existing)

    tree_path = root / "tree.json"
    tree = read_json_object_required(tree_path)
    nodes = dict(tree.get("nodes") or {})
    if node_id not in nodes or overwrite_existing:
        nodes[node_id] = prepared_branch_tree_entry(
            root=root,
            node_dir=node_dir,
            parent_id=parent_id,
            stage=stage,
            input_refs=input_refs,
            pathway_id=pathway_id,
            step_id=step_id,
        )
    tree["nodes"] = nodes

    events = list(tree.get("events") or [])
    event = prepared_branch_event(
        node_id=node_id,
        hypothesis=hypothesis,
        timestamp=timestamp,
        taken_ids={str(item.get("event_id") or "") for item in events if isinstance(item, dict)},
    )
    events.append(event)
    tree["events"] = events
    write_json_object(tree_path, tree, overwrite_existing=True)
    return PreparedBranchWrite(node_dir=node_dir, node_payload=node_payload, event_id=str(event["event_id"]))


__all__ = [
    "BRANCH_WORK_DIRS",
    "PreparedBranchWrite",
    "ensure_branch_directories",
    "next_branch_event_id",
    "prepared_branch_event",
    "prepared_branch_node_payload",
    "prepared_branch_tree_entry",
    "write_prepared_branch_state",
]
