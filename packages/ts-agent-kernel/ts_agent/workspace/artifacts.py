"""Workspace-owned artifact identity and safe filesystem resolution.

Artifacts are content-bound logical references. Domain adapters may add role
metadata, but path safety, ownership, digests, and ``art_*`` identity belong to
the research workspace rather than to any compute backend.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from ts_agent.io import read_json

from .errors import ContractError
from .path_safety import has_symlink_component, lexical_path, path_has_symlink
from .refs import CALCULATION_ID, NODE_ID


ARTIFACT_ID_SCHEMA_VERSION = "ts-artifact-id/2"
ELIGIBLE_ARTIFACT_SUFFIXES = frozenset(
    {".com", ".gif", ".gjf", ".inp", ".json", ".log", ".out", ".png", ".txt", ".xyz"}
)


class WorkspaceArtifactError(ContractError):
    """Raised when a workspace artifact cannot be resolved safely."""


def list_workspace_artifacts(root: str | Path) -> list[dict[str, Any]]:
    """Return current content-bound records for eligible workspace files."""

    workspace = workspace_root(root)
    known_nodes = workspace_node_ids(workspace)
    records = [
        artifact_for_path(workspace, path, known_nodes=known_nodes)
        for path in _eligible_paths(workspace, known_nodes)
    ]
    records.sort(key=lambda item: str(item["path"]))
    return records


def resolve_workspace_artifact_ids(
    root: str | Path,
    artifact_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Resolve unique logical artifact IDs to current path and digest records."""

    requested = list(artifact_ids)
    if not requested or len(set(requested)) != len(requested):
        raise WorkspaceArtifactError("artifact_ids must be a non-empty unique list")
    catalog = {item["artifact_id"]: item for item in list_workspace_artifacts(root)}
    missing = [artifact_id for artifact_id in requested if artifact_id not in catalog]
    if missing:
        raise WorkspaceArtifactError("unknown artifact_id: " + ", ".join(missing))
    return [catalog[artifact_id] for artifact_id in requested]


def resolve_workspace_artifact_ref(root: str | Path, artifact_ref: str) -> dict[str, Any]:
    """Resolve one workspace-relative path to its current content binding."""

    workspace = workspace_root(root)
    return artifact_for_ref(
        workspace,
        artifact_ref,
        known_nodes=workspace_node_ids(workspace),
    )


def artifact_for_path(
    workspace: Path,
    path: Path,
    *,
    known_nodes: set[str] | None = None,
) -> dict[str, Any]:
    """Build an artifact record for one existing path under a workspace."""

    try:
        relative = path.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise WorkspaceArtifactError("artifact path is outside the workspace") from exc
    return artifact_for_ref(workspace, relative, known_nodes=known_nodes)


def artifact_for_ref(
    workspace: Path,
    ref: str,
    *,
    known_nodes: set[str] | None = None,
) -> dict[str, Any]:
    """Build an artifact record after enforcing workspace path ownership."""

    node_ids = workspace_node_ids(workspace) if known_nodes is None else known_nodes
    normalized, path = safe_existing_artifact_path(workspace, ref, known_nodes=node_ids)
    owner_node, source_intent_id = artifact_ownership(normalized)
    digest = sha256_file(path)
    return {
        "artifact_id": artifact_id(normalized, digest),
        "path": normalized,
        "owner_node": owner_node,
        "source_intent_id": source_intent_id,
        "size_bytes": path.stat().st_size,
        "sha256": digest,
    }


def artifact_id(path: str, digest: str) -> str:
    """Derive a stable logical ID from both path and content digest."""

    material = json.dumps(
        {"schema_version": ARTIFACT_ID_SCHEMA_VERSION, "path": path, "sha256": digest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "art_" + hashlib.sha256(material).hexdigest()[:24]


def artifact_ownership(ref: str) -> tuple[str | None, str | None]:
    """Return the owning Node and Attempt encoded by an artifact path."""

    parts = PurePosixPath(ref).parts
    if len(parts) >= 2 and parts[0] == "inputs":
        return None, None
    if len(parts) >= 4 and parts[0] == "nodes" and parts[2] in {"inputs", "outputs"}:
        return parts[1], None
    if len(parts) >= 6 and parts[0] == "nodes" and parts[2] == "attempts" and parts[4] == "outputs":
        return parts[1], parts[3]
    raise WorkspaceArtifactError(
        "workspace artifacts must come from inputs or ResearchNode inputs/outputs"
    )


def safe_existing_artifact_path(
    workspace: Path,
    value: str,
    *,
    known_nodes: set[str] | None = None,
) -> tuple[str, Path]:
    """Resolve one relative, regular, non-symlink workspace artifact path."""

    text = str(value).replace("\\", "/").lstrip("@")
    if PurePosixPath(text).is_absolute():
        raise WorkspaceArtifactError(f"workspace path must be relative: {value}")
    normalized = posixpath.normpath(text)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise WorkspaceArtifactError(f"invalid workspace path: {value}")
    owner_node, _ = artifact_ownership(normalized)
    node_ids = workspace_node_ids(workspace) if known_nodes is None else known_nodes
    if owner_node is not None and owner_node not in node_ids:
        raise WorkspaceArtifactError(
            f"artifact owner ResearchNode does not exist: {owner_node}"
        )
    path = workspace.joinpath(*PurePosixPath(normalized).parts)
    if has_symlink_component(workspace, path):
        raise WorkspaceArtifactError(f"workspace artifact uses a symlink: {normalized}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise WorkspaceArtifactError(f"workspace artifact does not exist: {normalized}") from exc
    except OSError as exc:
        raise WorkspaceArtifactError(f"cannot inspect workspace artifact: {normalized}") from exc
    if not stat.S_ISREG(mode):
        raise WorkspaceArtifactError(f"workspace artifact does not exist: {normalized}")
    # ``has_symlink_component`` above is the ownership check.  Keep a final
    # lexical-relative assertion so a concurrent rename cannot turn an
    # absolute path into an out-of-tree reference between checks.
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise WorkspaceArtifactError(f"workspace artifact escapes the workspace: {normalized}") from exc
    return normalized, path


def workspace_root(root: str | Path) -> Path:
    """Resolve and minimally verify a current research workspace."""

    workspace = lexical_path(root)
    if path_has_symlink(workspace):
        raise WorkspaceArtifactError(f"workspace root cannot contain a symbolic link: {workspace}")
    workspace_doc = workspace / "workspace.json"
    nodes_doc = workspace / "research_nodes.json"
    if not workspace.is_dir() or workspace.is_symlink():
        raise WorkspaceArtifactError(f"not an initialized TS workspace: {workspace}")
    for path in (workspace_doc, nodes_doc, workspace / "nodes"):
        if has_symlink_component(workspace, path):
            raise WorkspaceArtifactError(f"workspace canonical path uses a symbolic link: {path.relative_to(workspace)}")
    if not workspace_doc.is_file() or workspace_doc.is_symlink() or not nodes_doc.is_file() or nodes_doc.is_symlink() or not (workspace / "nodes").is_dir():
        raise WorkspaceArtifactError(f"not an initialized TS workspace: {workspace}")
    try:
        identity = read_json(workspace_doc)
    except (OSError, ValueError) as exc:
        raise WorkspaceArtifactError(
            f"cannot read workspace identity: {workspace_doc}"
        ) from exc
    if not isinstance(identity, dict) or identity.get("schema_version") != "ts-workspace/6":
        raise WorkspaceArtifactError(f"unsupported workspace protocol: {workspace}")
    return workspace


def workspace_node_ids(workspace: Path) -> set[str]:
    """Return validated ResearchNode identifiers from the canonical registry."""

    return {str(item["node_id"]) for item in workspace_node_records(workspace)}


def workspace_node_records(workspace: Path) -> list[dict[str, Any]]:
    """Return validated ResearchNode records from the canonical registry.

    Artifact and Compute callers often need the Node status as well as its ID.
    Keep registry shape/identity checks in one place so malformed or duplicate
    records fail closed consistently instead of surfacing as ``AttributeError``
    or silently collapsing into a set.
    """

    workspace = lexical_path(workspace)
    registry_path = workspace / "research_nodes.json"
    if path_has_symlink(workspace) or has_symlink_component(workspace, registry_path):
        raise WorkspaceArtifactError("ResearchNode registry cannot contain a symbolic link")
    try:
        if not registry_path.is_file() or registry_path.is_symlink():
            raise WorkspaceArtifactError("ResearchNode registry is not a regular file")
        registry = read_json(registry_path)
    except WorkspaceArtifactError:
        raise
    except (OSError, ValueError) as exc:
        raise WorkspaceArtifactError("cannot read ResearchNode registry") from exc
    if not isinstance(registry, dict):
        raise WorkspaceArtifactError("ResearchNode registry must contain an object")
    if registry.get("schema_version") != "ts-research-node-registry/2":
        raise WorkspaceArtifactError("invalid ResearchNode registry")
    raw_nodes = registry.get("nodes")
    if not isinstance(raw_nodes, list):
        raise WorkspaceArtifactError("ResearchNode registry nodes must be an array")
    records: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, dict) or not isinstance(item.get("node_id"), str):
            raise WorkspaceArtifactError("ResearchNode registry contains an invalid node record")
        node_id = item["node_id"]
        if NODE_ID.fullmatch(node_id) is None:
            raise WorkspaceArtifactError("ResearchNode registry contains an invalid node_id")
        if node_id in ids:
            raise WorkspaceArtifactError(f"ResearchNode registry contains duplicate node_id: {node_id}")
        ids.add(node_id)
        records.append(item)
    return records


def sha256_file(path: Path) -> str:
    """Return one streaming SHA-256 digest using the workspace digest format."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _eligible_paths(workspace: Path, known_nodes: set[str]) -> Iterable[Path]:
    roots: list[Path] = []
    inputs = workspace / "inputs"
    if inputs.is_dir() and not inputs.is_symlink():
        roots.append(inputs)
    nodes_root = workspace / "nodes"
    if nodes_root.is_dir() and not nodes_root.is_symlink():
        for node_dir in sorted(nodes_root.iterdir()):
            if not node_dir.is_dir() or node_dir.is_symlink() or node_dir.name not in known_nodes:
                continue
            for name in ("inputs", "outputs"):
                candidate = node_dir / name
                if candidate.is_dir() and not candidate.is_symlink():
                    roots.append(candidate)
            attempts = node_dir / "attempts"
            if attempts.is_dir() and not attempts.is_symlink():
                for attempt in sorted(attempts.iterdir()):
                    output = attempt / "outputs"
                    if (
                        attempt.is_dir()
                        and not attempt.is_symlink()
                        and CALCULATION_ID.fullmatch(attempt.name)
                        and output.is_dir()
                        and not output.is_symlink()
                    ):
                        roots.append(output)
    seen: set[str] = set()
    for artifact_root in roots:
        for current, dirnames, filenames in os.walk(artifact_root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = sorted(
                name for name in dirnames if not (current_path / name).is_symlink()
            )
            for name in sorted(filenames):
                path = current_path / name
                if path.suffix.lower() not in ELIGIBLE_ARTIFACT_SUFFIXES or path.is_symlink():
                    continue
                ref = path.relative_to(workspace).as_posix()
                if ref in seen:
                    continue
                try:
                    safe_existing_artifact_path(workspace, ref, known_nodes=known_nodes)
                except WorkspaceArtifactError:
                    continue
                seen.add(ref)
                yield path


__all__ = [
    "ARTIFACT_ID_SCHEMA_VERSION",
    "ELIGIBLE_ARTIFACT_SUFFIXES",
    "WorkspaceArtifactError",
    "artifact_for_path",
    "artifact_for_ref",
    "artifact_id",
    "artifact_ownership",
    "list_workspace_artifacts",
    "resolve_workspace_artifact_ids",
    "resolve_workspace_artifact_ref",
    "safe_existing_artifact_path",
    "sha256_file",
    "workspace_node_ids",
    "workspace_node_records",
    "workspace_root",
]
