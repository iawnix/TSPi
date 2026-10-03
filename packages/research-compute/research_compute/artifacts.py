"""Deterministic discovery and binding of workspace calculation artifacts.

Public callers use logical ``art_*`` identifiers. Physical paths remain an
implementation detail of this module and are frozen with a digest whenever a
calculation intent is created.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from tspi_foundation.io import read_json
from research_compute.workspace.artifacts import (
    WorkspaceArtifactError,
    artifact_for_path as workspace_artifact_for_path,
    artifact_for_ref as workspace_artifact_for_ref,
    artifact_id as workspace_artifact_id,
    list_workspace_artifacts,
    sha256_file as workspace_sha256_file,
    workspace_node_ids,
    workspace_node_records,
    workspace_root,
)
from research_compute.workspace.refs import NODE_ID
from tspi_foundation.path_safety import has_symlink_component
from research_compute.workspace.transactions import workspace_lock
from .provider import ProviderUnavailable, resolve_compute_provider

from .errors import ComputeContractError


CATALOG_SCHEMA_VERSION = "ts-artifact-catalog/3"
IMPORT_REQUEST_SCHEMA_VERSION = "ts-artifact-import-request/2"
IMPORT_RESULT_SCHEMA_VERSION = "ts-artifact-import-result/1"
STRUCTURE_SEED_REQUEST_SCHEMA_VERSION = "ts-structure-seed-request/1"
STRUCTURE_SEED_RESULT_SCHEMA_VERSION = "ts-structure-seed-result/1"
STRUCTURE_COMPARE_REQUEST_SCHEMA_VERSION = "ts-structure-compare-request/1"
STRUCTURE_COMPARE_RESULT_SCHEMA_VERSION = "ts-structure-compare-result/1"
STRUCTURE_COMPARISON_SCHEMA_VERSION = "ts-structure-comparison/1"
REACTION_MAPPING_VALIDATE_REQUEST_SCHEMA_VERSION = "ts-reaction-mapping-validate-request/1"
REACTION_MAPPING_VALIDATE_RESULT_SCHEMA_VERSION = "ts-reaction-mapping-validate-result/1"
REACTION_MAPPING_VALIDATE_ARTIFACT_SCHEMA_VERSION = "ts-reaction-mapping-validation/1"
MAX_IMPORT_BYTES = 128 * 1024
IMPORT_FORMATS = frozenset({"gaussian_input", "xyz_structure", "xtb_control"})
IMPORT_FORMAT_SUFFIXES = {
    "gaussian_input": frozenset({".com", ".gjf"}),
    "xyz_structure": frozenset({".xyz"}),
    "xtb_control": frozenset({".inp"}),
}
IMPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROLE_SUFFIXES = {
    "gjf": frozenset({".gjf", ".com"}),
    "xyz": frozenset({".xyz"}),
    "control": frozenset({".inp"}),
    "config": frozenset({".json"}),
    "reactant": frozenset({".xyz"}),
    "product": frozenset({".xyz"}),
}
def list_calculation_artifacts(
    root: str | Path,
    *,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded catalog of files eligible as calculation inputs."""

    workspace = _workspace_root(root)
    known_nodes = _node_ids(workspace)
    if node_id is not None and node_id not in known_nodes:
        raise ComputeContractError(f"unknown ResearchNode: {node_id}")
    artifacts = [
        item
        for item in _catalog_items(workspace, known_nodes)
        if node_id is None or item["owner_node"] == node_id
    ]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "workspace_root": str(workspace),
        "node_id": node_id,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def resolve_artifact_ids(
    root: str | Path,
    artifact_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Resolve exact logical IDs to current path/digest records."""

    workspace = _workspace_root(root)
    requested = list(artifact_ids)
    if not requested or len(set(requested)) != len(requested):
        raise ComputeContractError("artifact_ids must be a non-empty unique list")
    catalog = {item["artifact_id"]: item for item in _catalog_items(workspace, _node_ids(workspace))}
    missing = [artifact_id for artifact_id in requested if artifact_id not in catalog]
    if missing:
        raise ComputeContractError("unknown artifact_id: " + ", ".join(missing))
    return [catalog[artifact_id] for artifact_id in requested]


def resolve_artifact_ref(root: str | Path, artifact_ref: str) -> dict[str, Any]:
    """Resolve one logical workspace path to its current catalog binding."""

    workspace = _workspace_root(root)
    return _artifact_for_ref(workspace, artifact_ref, _node_ids(workspace))


def import_calculation_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_compute_provider("chemical").structure_operation("import_artifact", Path(root), request)
    except ProviderUnavailable as exc:
        raise ComputeContractError(str(exc)) from exc


def create_structure_seed_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_compute_provider("chemical").structure_operation("structure_seed", Path(root), request)
    except ProviderUnavailable as exc:
        raise ComputeContractError(str(exc)) from exc


def create_structure_comparison_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_compute_provider("chemical").structure_operation("structure_compare", Path(root), request)
    except ProviderUnavailable as exc:
        raise ComputeContractError(str(exc)) from exc


def create_reaction_mapping_validation_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_compute_provider("chemical").structure_operation("mapping_validate", Path(root), request)
    except ProviderUnavailable as exc:
        raise ComputeContractError(str(exc)) from exc


def resolve_input_artifacts(
    workspace: Path,
    supplied: list[dict[str, str]],
    required_roles: set[str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Resolve role/ID pairs into immutable path and digest bindings."""

    by_role: dict[str, str] = {}
    for item in supplied:
        role = str(item["input_role"])
        if role in by_role:
            raise ComputeContractError(f"duplicate calculation input role: {role}")
        by_role[role] = str(item["artifact_id"])
    missing = sorted(required_roles - set(by_role))
    unexpected = sorted(set(by_role) - required_roles)
    if missing or unexpected:
        raise ComputeContractError(
            f"calculation input roles must be exactly {sorted(required_roles)}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    resolved = {
        item["artifact_id"]: item
        for item in resolve_artifact_ids(workspace, by_role.values())
    }
    refs: dict[str, str] = {}
    bindings: list[dict[str, Any]] = []
    for role in sorted(required_roles):
        artifact = resolved[by_role[role]]
        if role not in artifact["input_roles"]:
            raise ComputeContractError(
                f"artifact {artifact['artifact_id']} is not compatible with input role {role}; "
                f"compatible_roles={artifact['input_roles']}"
            )
        path = str(artifact["path"])
        refs[role] = path
        bindings.append(
            {
                "input_role": role,
                "artifact_id": artifact["artifact_id"],
                "path": path,
                "sha256": artifact["sha256"],
                "owner_node": artifact["owner_node"],
                "source_intent_id": artifact["source_intent_id"],
            }
        )
    if len(set(refs.values())) != len(refs):
        raise ComputeContractError("distinct calculation input roles must bind distinct artifacts")
    return refs, bindings


def verify_input_bindings(workspace: Path, intent: dict[str, Any]) -> None:
    """Verify that a frozen input binding still identifies identical bytes."""

    refs = intent.get("input_refs")
    bindings = intent.get("input_bindings")
    if not isinstance(refs, dict) or not isinstance(bindings, list):
        raise ComputeContractError("calculation intent requires input_refs and input_bindings")
    by_role: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ComputeContractError("calculation input binding must be an object")
        role = binding.get("input_role")
        if not isinstance(role, str) or role in by_role:
            raise ComputeContractError(f"duplicate or invalid calculation input binding role: {role}")
        by_role[role] = binding
    if set(by_role) != set(refs):
        raise ComputeContractError("calculation input_bindings roles must match input_refs")
    known_nodes = _node_ids(workspace)
    for role, ref in sorted(refs.items()):
        binding = by_role[role]
        if binding.get("path") != ref:
            raise ComputeContractError(f"calculation input binding path mismatch for role {role}")
        current = _artifact_for_ref(workspace, str(ref), known_nodes)
        for key in ("artifact_id", "sha256", "owner_node", "source_intent_id"):
            if binding.get(key) != current.get(key):
                raise ComputeContractError(
                    f"calculation input binding changed for role {role}: {key} mismatch"
                )


def _catalog_items(workspace: Path, known_nodes: set[str]) -> list[dict[str, Any]]:
    del known_nodes
    return [_with_input_roles(item) for item in list_workspace_artifacts(workspace)]


def _artifact_for_path(workspace: Path, path: Path, known_nodes: set[str]) -> dict[str, Any]:
    try:
        return _with_input_roles(
            workspace_artifact_for_path(workspace, path, known_nodes=known_nodes)
        )
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _artifact_for_ref(workspace: Path, ref: str, known_nodes: set[str]) -> dict[str, Any]:
    try:
        return _with_input_roles(
            workspace_artifact_for_ref(workspace, ref, known_nodes=known_nodes)
        )
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _artifact_id(path: str, digest: str) -> str:
    return workspace_artifact_id(path, digest)


def _with_input_roles(record: dict[str, Any]) -> dict[str, Any]:
    suffix = Path(str(record["path"])).suffix.lower()
    return {
        **record,
        "input_roles": sorted(
            role for role, suffixes in ROLE_SUFFIXES.items() if suffix in suffixes
        ),
    }


def _node_inputs_directory(workspace: Path, node_id: str) -> Path:
    nodes_root = workspace / "nodes"
    if has_symlink_component(workspace, nodes_root) or not nodes_root.is_dir() or nodes_root.is_symlink():
        raise ComputeContractError("workspace nodes root must be a physical directory")
    node_root = nodes_root / node_id
    if has_symlink_component(workspace, node_root):
        raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    if node_root.exists():
        if not node_root.is_dir() or node_root.is_symlink():
            raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    else:
        node_root.mkdir(mode=0o700)
    inputs = node_root / "inputs"
    if has_symlink_component(workspace, inputs):
        raise ComputeContractError(f"ResearchNode input root is unsafe: {node_id}")
    if inputs.exists():
        if not inputs.is_dir() or inputs.is_symlink():
            raise ComputeContractError(f"ResearchNode input root is unsafe: {node_id}")
    else:
        inputs.mkdir(mode=0o700)
    expected = workspace / "nodes" / node_id / "inputs"
    if inputs != expected:
        raise ComputeContractError(f"ResearchNode input root escapes the workspace: {node_id}")
    return inputs


def _node_analysis_directory(workspace: Path, node_id: str) -> Path:
    nodes_root = workspace / "nodes"
    if has_symlink_component(workspace, nodes_root) or not nodes_root.is_dir() or nodes_root.is_symlink():
        raise ComputeContractError("workspace nodes root must be a physical directory")
    node_root = nodes_root / node_id
    if has_symlink_component(workspace, node_root):
        raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    if node_root.exists():
        if not node_root.is_dir() or node_root.is_symlink():
            raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    else:
        node_root.mkdir(mode=0o700)
    outputs = node_root / "outputs"
    analysis = outputs / "analysis"
    if has_symlink_component(workspace, outputs) or has_symlink_component(workspace, analysis):
        raise ComputeContractError(f"ResearchNode output root is unsafe: {node_id}")
    for path, label in ((outputs, "output"), (analysis, "analysis")):
        if path.exists():
            if not path.is_dir() or path.is_symlink():
                raise ComputeContractError(f"ResearchNode {label} root is unsafe: {node_id}")
        else:
            path.mkdir(mode=0o700)
    expected = workspace / "nodes" / node_id / "outputs" / "analysis"
    if analysis != expected:
        raise ComputeContractError(f"ResearchNode analysis root escapes the workspace: {node_id}")
    return analysis


def _write_artifact_payload(path: Path, payload: bytes) -> bool:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ComputeContractError("artifact target is not a regular file")
        if path.read_bytes() != payload:
            raise ComputeContractError("artifact target already contains different content")
        if path.stat().st_mode & 0o077:
            raise ComputeContractError("existing artifact is not private")
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return True


def _comparison_input_binding(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_ref": artifact["path"],
        "sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
        "owner_node": artifact["owner_node"],
        "source_intent_id": artifact["source_intent_id"],
    }


def _node_record(workspace: Path, node_id: str) -> dict[str, Any]:
    try:
        records = workspace_node_records(workspace)
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc
    matches = [item for item in records if item.get("id") == node_id]
    if len(matches) != 1:
        raise ComputeContractError(f"unknown ResearchNode: {node_id}")
    return matches[0]


def _workspace_root(root: str | Path) -> Path:
    try:
        return workspace_root(root)
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _node_ids(workspace: Path) -> set[str]:
    try:
        return workspace_node_ids(workspace)
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _sha256_file(path: Path) -> str:
    return workspace_sha256_file(path)
