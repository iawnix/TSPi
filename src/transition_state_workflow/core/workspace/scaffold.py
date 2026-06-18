"""Generic workspace scaffold, report, and reflection writers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import EVIDENCE_REGISTRY_SCHEMA, TREE_SCHEMA, WORKSPACE_NODE_SCHEMA
from transition_state_workflow.util.json_io import write_json_object

from .io import write_json, write_markdown
from .naming import utc_timestamp
from .tree import read_tree, update_tree_node_metadata, upsert_tree_node, write_tree


WORKSPACE_ROOT_DIRECTORIES = ("inputs", "nodes", "reports", "accepted", "rejected")


def ensure_workspace_directories(root: Path, directories: tuple[str, ...] = WORKSPACE_ROOT_DIRECTORIES) -> None:
    """Create a TS-search workspace root and requested child directories."""

    root.mkdir(parents=True, exist_ok=True)
    for dirname in directories:
        (root / dirname).mkdir(exist_ok=True)


def initial_workspace_manifest(
    *,
    root: Path,
    system: str,
    charge: int,
    multiplicity: int,
    created_at: str,
) -> dict[str, Any]:
    """Build the initial manifest payload for a TS-search workspace."""

    return {
        "system": system,
        "created_at": created_at,
        "charge": charge,
        "multiplicity": multiplicity,
        "root": str(root),
        "node_schema": WORKSPACE_NODE_SCHEMA,
        "mechanism_preflight_storage": "undeclared",
        "current_accepted_ts": None,
    }


def initial_workspace_tree() -> dict[str, Any]:
    """Build the initial empty hypothesis tree payload."""

    return {
        "schema": TREE_SCHEMA,
        "nodes": {},
        "active_frontier": [],
        "closed_nodes": [],
        "accepted_nodes": [],
        "events": [],
        "backtrack_events": [],
    }


def initial_evidence_registry(*, system: str, updated_at: str) -> dict[str, Any]:
    """Build the initial empty evidence registry payload."""

    return {
        "schema": EVIDENCE_REGISTRY_SCHEMA,
        "system": system,
        "records": [],
        "updated_at": updated_at,
    }


def write_initial_workspace_files(
    root: Path,
    *,
    system: str,
    charge: int,
    multiplicity: int,
    timestamp: str,
    overwrite_existing: bool,
) -> None:
    """Create root directories and initial root JSON files for a TS workspace."""

    ensure_workspace_directories(root)
    write_json_object(
        root / "manifest.json",
        initial_workspace_manifest(
            root=root,
            system=system,
            charge=charge,
            multiplicity=multiplicity,
            created_at=timestamp,
        ),
        overwrite_existing=overwrite_existing,
    )
    write_json_object(root / "tree.json", initial_workspace_tree(), overwrite_existing=overwrite_existing)
    write_json_object(
        root / "evidence_registry.json",
        initial_evidence_registry(system=system, updated_at=timestamp),
        overwrite_existing=overwrite_existing,
    )


def ensure_tree_skeleton(
    root: Path,
    *,
    system_slug: str,
    readme_body: str,
    manifest_extra: dict[str, Any] | None = None,
) -> None:
    """Create the standard TS-search workspace skeleton if absent."""

    ensure_workspace_directories(root)
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


def ensure_workspace_root_has_manifest_and_tree(root: Path) -> None:
    """Abort when root is missing the files required for a TS workspace."""

    missing = [name for name in ("manifest.json", "tree.json") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")


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
    "ensure_workspace_directories",
    "ensure_tree_skeleton",
    "ensure_workspace_root_has_manifest_and_tree",
    "finalize_node_report_and_tree",
    "initial_evidence_registry",
    "initial_workspace_manifest",
    "initial_workspace_tree",
    "WORKSPACE_ROOT_DIRECTORIES",
    "write_final_reflection",
    "write_initial_workspace_files",
    "write_reflection_template",
]
