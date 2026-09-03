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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from ts_agent.io import read_json

from .errors import ContractError
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

    return artifact_for_ref(
        workspace,
        path.relative_to(workspace).as_posix(),
        known_nodes=known_nodes,
    )


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
    if not path.is_file() or path.is_symlink():
        raise WorkspaceArtifactError(f"workspace artifact does not exist: {normalized}")
    workspace_real = workspace.resolve(strict=True)
    expected = workspace_real.joinpath(*PurePosixPath(normalized).parts)
    if path.resolve(strict=True) != expected:
        raise WorkspaceArtifactError(f"workspace artifact uses a symlink: {normalized}")
    return normalized, path


def workspace_root(root: str | Path) -> Path:
    """Resolve and minimally verify a current research workspace."""

    workspace = Path(root).expanduser().resolve()
    workspace_doc = workspace / "workspace.json"
    nodes_doc = workspace / "research_nodes.json"
    if not workspace_doc.is_file() or not nodes_doc.is_file() or not (workspace / "nodes").is_dir():
        raise WorkspaceArtifactError(f"not an initialized TS workspace: {workspace}")
    if read_json(workspace_doc).get("schema_version") != "ts-workspace/6":
        raise WorkspaceArtifactError(f"unsupported workspace protocol: {workspace}")
    return workspace


def workspace_node_ids(workspace: Path) -> set[str]:
    """Return validated ResearchNode identifiers from the canonical registry."""

    registry = read_json(workspace / "research_nodes.json")
    if registry.get("schema_version") != "ts-research-node-registry/2":
        raise WorkspaceArtifactError("invalid ResearchNode registry")
    ids = {
        item.get("node_id")
        for item in registry.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
    }
    if any(NODE_ID.fullmatch(value) is None for value in ids):
        raise WorkspaceArtifactError("ResearchNode registry contains an invalid node_id")
    return ids


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
    "workspace_root",
]
