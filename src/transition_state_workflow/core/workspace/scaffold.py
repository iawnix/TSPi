"""Generic workspace scaffold, report, and reflection writers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import EVIDENCE_REGISTRY_SCHEMA, WORKSPACE_NODE_SCHEMA

from .io import write_json, write_markdown
from .naming import utc_timestamp
from .tree import read_tree, update_tree_node_metadata, upsert_tree_node, write_tree


def ensure_tree_skeleton(
    root: Path,
    *,
    system_slug: str,
    readme_body: str,
    manifest_extra: dict[str, Any] | None = None,
) -> None:
    """Create the standard TS-search workspace skeleton if absent."""

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


def write_reflection_template(
    node_dir: Path,
    *,
    decision: str = "pending",
    force: bool = False,
) -> Path:
    """Write a standard reflection template if one is not already present."""

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
    """Write report/reflection artifacts, then register a node in tree state."""

    write_markdown(node_dir / "report.md", report_body)
    if reflection is not None:
        write_final_reflection(node_dir, **reflection)
    else:
        write_reflection_template(node_dir, decision=reflection_decision)
    upsert_tree_node(root, node_id, parent=parent, stage=stage, status=status)
    update_tree_node_metadata(root, node_id, node)


__all__ = [
    "ensure_tree_skeleton",
    "finalize_node_report_and_tree",
    "write_final_reflection",
    "write_reflection_template",
]
