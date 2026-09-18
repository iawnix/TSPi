"""Workspace entry points backed by the canonical ResearchMap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_agent.io import now_iso, write_json
from ts_agent.research import ResearchKernel, ResearchMap
from ts_agent.research.kernel import MAP_FILE

from .errors import ContractError
from .identity import WorkspaceIdentityError, ensure_workspace_identity
from .path_safety import has_symlink_component, lexical_path, path_has_symlink
from .validator import validate_workspace


WORKSPACE_FILE = "workspace.json"
TRANSACTION_FILE = "transactions.jsonl"
CANONICAL_DIRS = ("nodes", "operations", "scratch", "inputs")
LEGACY_FILES = (
    "research_state.json",
    "phases.json",
    "claims.json",
    "claim_relations.json",
    "research_nodes.json",
    "observations.json",
    "proof_specs.json",
    "validation_results.json",
    "findings.json",
)


def init_workspace(root: str | Path) -> dict[str, Any]:
    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise ContractError("workspace root cannot be a symbolic link")
    canonical = (WORKSPACE_FILE, MAP_FILE, TRANSACTION_FILE)
    for name in canonical:
        path = root_path / name
        if has_symlink_component(root_path, path) or path.is_symlink():
            raise ContractError(f"workspace path contains a symbolic link: {name}")
    existing = [name for name in canonical if (root_path / name).exists()]
    if existing:
        raise ContractError("workspace already contains canonical state: " + ", ".join(sorted(existing)))
    legacy = [name for name in LEGACY_FILES if (root_path / name).exists()]
    if legacy:
        raise ContractError("legacy research files are not supported: " + ", ".join(sorted(legacy)))

    root_path.mkdir(parents=True, exist_ok=True)
    try:
        identity = ensure_workspace_identity(root_path)
    except WorkspaceIdentityError as exc:
        raise ContractError(str(exc)) from exc
    created_at = now_iso()
    for dirname in CANONICAL_DIRS:
        directory = root_path / dirname
        if has_symlink_component(root_path, directory) or directory.is_symlink():
            raise ContractError(f"workspace path contains a symbolic link: {dirname}")
        directory.mkdir(parents=True, exist_ok=True)
    write_json(
        root_path / WORKSPACE_FILE,
        {
            "schema_version": "research-workspace/1",
            "workspace_id": identity["workspace_id"],
            "kernel_protocol": "research-map/1",
            "created_at": created_at,
        },
    )
    ResearchKernel(root_path).save(
        ResearchMap(
            map_id=identity["workspace_id"],
            title=root_path.name or identity["workspace_id"],
            created_at=created_at,
        )
    )
    (root_path / TRANSACTION_FILE).touch(mode=0o600)
    validation = validate_workspace(root_path)
    if not validation["valid"]:
        raise ContractError("fresh workspace failed validation")
    return {
        "schema_version": "research-map-init-result/1",
        "root": str(root_path),
        "workspace_id": identity["workspace_id"],
        "created": True,
        "valid": True,
        "revision": 0,
    }


def load_research_map(root: str | Path) -> ResearchMap:
    return ResearchKernel(root).load()


def change_workspace(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    return ResearchKernel(root).apply(request)
