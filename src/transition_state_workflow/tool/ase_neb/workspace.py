"""Workspace persistence: tree state, evidence registry, node records, scaffold.

Owns the on-disk layout for a TS-search workspace seen from the NEB toolkit:
``tree.json``, ``evidence_registry.json``, ``manifest.json``, ``inputs/``,
``nodes/``, and the node-record builder used by the workflow tools. Pure I/O and
v2-schema bookkeeping — no ASE, no driver state.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import (
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
    derive_claim_level,
)
from transition_state_workflow.tool.ase_neb.config import (
    ProjectContext,
    project_context,
    safe_slug,
    utc_timestamp,
)
from transition_state_workflow.tool.ase_neb.constants import VALID_NODE_STATUSES
from transition_state_workflow.tool.ase_neb.errors import ConfigError


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def relative_artifact_path(root: Path, path: Path | str | None) -> str:
    """Return a workspace-relative artifact path when possible."""

    if path is None:
        return ""
    artifact = Path(str(path))
    if not artifact.is_absolute():
        return str(artifact)
    try:
        return str(artifact.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(artifact)


def node_record(
    *,
    node_id: str,
    parent_id: str | None,
    node_type: str,
    hypothesis: str,
    changed_variables: dict[str, Any] | None,
    status: str,
    evidence: dict[str, Any] | None,
    decision: str,
    backtrack_to: str | None = None,
    children: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if status not in VALID_NODE_STATUSES:
        raise ConfigError(f"invalid node status '{status}' for {node_id}")
    stage = str(extra.pop("stage", node_type))
    operation = str(extra.pop("operation", decision or stage))
    failure_type = extra.pop("failure_type", None)
    claim_status = str(extra.pop("claim_status", "not_evaluated"))
    outcome = str(extra.pop("outcome", "none"))
    outcome_code = extra.pop("outcome_code", None)
    failure_type = failure_type or outcome_code
    lifecycle_state = str(extra.pop("lifecycle_state", "prepared"))
    run_state = str(extra.pop("run_state", "not_started"))

    if status == "pending":
        lifecycle_state = "active"
        run_state = "pending"
    elif status == "running":
        lifecycle_state = "active"
        run_state = "running"
    elif status == "succeeded":
        lifecycle_state = "closed"
        run_state = "completed"
        if stage in {"neb", "gaussian_external_neb"}:
            claim_status = "candidate_found"
            outcome = "candidate_generated"
    elif status == "ambiguous":
        lifecycle_state = "closed"
        run_state = "completed"
        if failure_type in {"neb_endpoint_candidate", "neb_no_barrier"}:
            claim_status = "rejected"
            outcome = "chemical_failure"
            outcome_code = outcome_code or failure_type
        elif failure_type:
            claim_status = "not_evaluated"
            outcome = "numerical_failure"
            outcome_code = outcome_code or failure_type
        else:
            claim_status = "ambiguous"
            outcome = "parser_refused"
            outcome_code = outcome_code or "ambiguous_candidate_generation"
    elif status == "failed":
        lifecycle_state = "closed"
        run_state = "error"
        claim_status = "not_evaluated"
        outcome = "numerical_failure"
        outcome_code = outcome_code or failure_type or "execution_failed"
    elif status == "accepted":
        lifecycle_state = "closed"
        run_state = "completed"
        claim_status = "accepted_ts"
        outcome = "accepted"
    elif status == "closed":
        lifecycle_state = "closed"

    claim_level = derive_claim_level(claim_status)
    record = {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": node_id,
        "parent_id": parent_id,
        "stage": stage,
        "operation": operation,
        "lifecycle_state": lifecycle_state,
        "run_state": run_state,
        "claim_status": claim_status,
        "outcome": outcome,
        "outcome_code": outcome_code,
        "claim_level": claim_level,
        "created_at": utc_timestamp(),
        "hypothesis": hypothesis,
        "changed_variables": changed_variables or {},
        "evidence": evidence or {},
        "decision": decision,
        "display": {
            "title": node_id,
            "subtitle": stage,
            "badges": [claim_status],
            "metrics": {},
            "primary_file": "",
            "summary": hypothesis,
        },
    }
    record.update(extra)
    return record


def read_tree(root: Path) -> dict[str, Any]:
    path = root / "tree.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["schema"] = TREE_SCHEMA
            data.setdefault("active_frontier", [])
            data.setdefault("closed_nodes", [])
            data.setdefault("accepted_nodes", [])
            data.setdefault("events", [])
            data.setdefault("backtrack_events", [])
            data.setdefault("nodes", {})
            data.pop("schema_version", None)
            data.pop("root", None)
            data.pop("root_node", None)
            data.pop("current_best", None)
            data.pop("accepted_ts", None)
            data.pop("backtrack_edges", None)
            data.pop("branch_decisions", None)
            return data
    return {
        "schema": TREE_SCHEMA,
        "active_frontier": [],
        "closed_nodes": [],
        "accepted_nodes": [],
        "events": [],
        "backtrack_events": [],
        "nodes": {},
    }


def write_tree(root: Path, tree: dict[str, Any]) -> None:
    (root / "tree.json").write_text(
        json.dumps(tree, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def upsert_tree_node(
    root: Path,
    node_id: str,
    *,
    parent: str | None,
    stage: str,
    status: str,
    current_best: str | None = None,
    accepted_ts: str | None = None,
) -> None:
    # Kept for backward-compatible callers; v2 tree state never stores current_best.
    _ = current_best
    if status not in VALID_NODE_STATUSES:
        raise ConfigError(f"invalid tree node status '{status}' for {node_id}")
    tree = read_tree(root)
    nodes = tree.setdefault("nodes", {})
    entry = nodes.setdefault(node_id, {})
    entry["parent_id"] = parent
    entry["stage"] = stage
    if accepted_ts is not None:
        if accepted_ts not in tree.setdefault("accepted_nodes", []):
            tree["accepted_nodes"].append(accepted_ts)
    frontier = tree.setdefault("active_frontier", [])
    closed = tree.setdefault("closed_nodes", [])
    if status in {"pending", "running"}:
        if node_id not in frontier:
            frontier.append(node_id)
    elif node_id in frontier:
        frontier.remove(node_id)
    if status in {"succeeded", "failed", "ambiguous", "accepted", "closed"}:
        if node_id not in closed:
            closed.append(node_id)
    elif node_id in closed:
        closed.remove(node_id)
    write_tree(root, tree)


def update_tree_node_metadata(root: Path, node_id: str, metadata: dict[str, Any]) -> None:
    """Apply a subset of node metadata (parent/stage/operation/refs) to the tree."""

    tree = read_tree(root)
    nodes = tree.setdefault("nodes", {})
    entry = nodes.setdefault(node_id, {})
    for key in ("parent_id", "stage", "operation", "input_refs", "hypothesis"):
        if key in metadata:
            entry[key] = metadata[key]
    write_tree(root, tree)


def append_evidence_record(
    root: Path,
    *,
    node_id: str,
    kind: str,
    path: Path | str,
    claim: str,
    evidence_state: str,
) -> None:
    """Append or update one v2 evidence-registry record for a migrated tool."""

    registry_path = root / "evidence_registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {
            "schema": EVIDENCE_REGISTRY_SCHEMA,
            "system": root.name,
            "records": [],
            "updated_at": utc_timestamp(),
        }
    records = registry.setdefault("records", [])
    rel_path = relative_artifact_path(root, path)
    evidence_id = f"{node_id}:{kind}:{safe_slug(Path(rel_path).name, kind)}"
    record = {
        "evidence_id": evidence_id,
        "node_id": node_id,
        "kind": kind,
        "path": rel_path,
        "claim": claim,
        "evidence_state": evidence_state,
        "recorded_at": utc_timestamp(),
    }
    for index, old in enumerate(records):
        if isinstance(old, dict) and old.get("evidence_id") == evidence_id:
            records[index] = record
            break
    else:
        records.append(record)
    registry["schema"] = EVIDENCE_REGISTRY_SCHEMA
    registry["updated_at"] = utc_timestamp()
    write_json(registry_path, registry)


def ensure_tree_skeleton(
    root: Path,
    *,
    system_slug: str,
    readme_body: str,
    manifest_extra: dict[str, Any] | None = None,
) -> None:
    """Create the standard workspace skeleton if absent.

    Idempotent: directories (``inputs``/``nodes``/``accepted``/``rejected``),
    ``manifest.json``, ``evidence_registry.json``, ``tree.json``, and
    ``README.md`` are each created only when missing. Callers layer their own
    ``inputs/`` contents and manifest extras on top.
    """

    root.mkdir(parents=True, exist_ok=True)
    for dirname in ("inputs", "nodes", "accepted", "rejected"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.json"
    if not manifest.exists():
        payload = {
            "system": system_slug,
            "system_slug": system_slug,
            "created_at": utc_timestamp(),
            "root": str(root),
            "node_schema": WORKSPACE_NODE_SCHEMA,
            "current_accepted_ts": None,
        }
        if manifest_extra:
            payload.update(manifest_extra)
        write_json(manifest, payload)
    evidence_registry = root / "evidence_registry.json"
    if not evidence_registry.exists():
        write_json(
            evidence_registry,
            {
                "schema": EVIDENCE_REGISTRY_SCHEMA,
                "system": system_slug,
                "records": [],
                "updated_at": utc_timestamp(),
            },
        )
    if not (root / "tree.json").exists():
        write_tree(root, read_tree(root))
    readme = root / "README.md"
    if not readme.exists():
        write_markdown(readme, readme_body)


def ensure_project_scaffold(
    cfg: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> ProjectContext:
    ctx = project_context(cfg)
    system_slug = cfg["project"]["system_slug"]
    ensure_tree_skeleton(
        ctx.root,
        system_slug=system_slug,
        readme_body=f"""# TS Search: {system_slug}

Status: candidate_search

This directory is a structured transition-state search tree. NEB outputs are
candidates only; accepted transition states require Gaussian frequency and
connectivity evidence.
""",
    )
    write_json(ctx.root / "inputs" / "config.normalized.json", cfg)
    if config_path is not None and config_path.exists():
        shutil.copyfile(config_path, ctx.root / "inputs" / "config.original.json")
    for key in ("reactant", "product"):
        source = Path(str(cfg[key]))
        if source.exists():
            shutil.copyfile(source, ctx.root / "inputs" / f"{key}{source.suffix or '.xyz'}")
    return ctx


def next_node_id(root: Path, stage_slug: str, *, start: int = 20) -> str:
    nodes_dir = root / "nodes"
    used: list[int] = []
    if nodes_dir.exists():
        for path in nodes_dir.iterdir():
            match = re.match(r"n(\d{3})_", path.name)
            if match:
                used.append(int(match.group(1)))
    number = start if not used else max(used) + 10
    return f"n{number:03d}_{safe_slug(stage_slug)}"


def write_reflection_template(
    node_dir: Path,
    *,
    decision: str = "pending",
    force: bool = False,
) -> Path:
    path = node_dir / "reflection.md"
    if path.exists() and not force:
        return path
    write_markdown(
        path,
        f"""## Decision
{decision}

## Evidence
-

## Risk
-

## Next
-
""",
    )
    return path


def write_final_reflection(
    node_dir: Path,
    *,
    computational_outcome: str,
    mechanistic_implication: str,
    next_branch: str,
    knowledge_update: str = "No knowledge-base update requested.",
) -> Path:
    """Write a non-template reflection for a closed branch node."""

    path = node_dir / "reflection.md"
    write_markdown(
        path,
        f"""# Reflection

## Computational Outcome

{computational_outcome}

## Mechanistic Implication

{mechanistic_implication}

## Knowledge Update

- {knowledge_update}

## Next Branch

{next_branch}
""",
    )
    return path


def finalize_node_report_and_tree(
    root: Path,
    node_dir: Path,
    node_id: str,
    node: dict[str, Any],
    *,
    parent: str | None,
    stage: str,
    status: str,
    report_body: str,
    reflection: dict[str, str] | None = None,
    reflection_decision: str = "pending",
) -> None:
    """Write the shared tail of every node writer.

    Every node writer ends the same way: a ``report.md``, then either a full
    reflection (when ``reflection`` carries the four reflection texts) or a
    reflection template, then the tree upsert + node-metadata update. The
    node-specific node.json/config.json/evidence writes stay in each caller
    because their fields and evidence kinds differ; this only owns the common
    "render report + reflection + register in tree" sequence.
    """

    write_markdown(node_dir / "report.md", report_body)
    if reflection is not None:
        write_final_reflection(node_dir, **reflection)
    else:
        write_reflection_template(node_dir, decision=reflection_decision)
    upsert_tree_node(root, node_id, parent=parent, stage=stage, status=status)
    update_tree_node_metadata(root, node_id, node)


__all__ = [
    "write_json",
    "write_markdown",
    "relative_artifact_path",
    "finalize_node_report_and_tree",
    "node_record",
    "read_tree",
    "write_tree",
    "upsert_tree_node",
    "update_tree_node_metadata",
    "append_evidence_record",
    "ensure_tree_skeleton",
    "ensure_project_scaffold",
    "next_node_id",
    "write_reflection_template",
    "write_final_reflection",
]
