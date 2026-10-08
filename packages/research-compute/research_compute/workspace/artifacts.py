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

from tspi_foundation.io import read_json
from research_state.workspace import RETIRED_WORKSPACE_FILES, WorkspaceModeError, validate_workspace_manifest
from .errors import ContractError
from tspi_foundation.path_safety import has_symlink_component, lexical_path, path_has_symlink
from .refs import CALCULATION_ID, NODE_ID


ARTIFACT_ID_SCHEMA_VERSION = "ts-artifact-id/3"
ELIGIBLE_ARTIFACT_SUFFIXES = frozenset(
    {".com", ".gif", ".gjf", ".inp", ".json", ".log", ".out", ".png", ".txt", ".xyz"}
)
RESEARCH_CONTEXT_COLLECTIONS = (
    "phases", "claims", "nodes", "findings", "gates", "claim_relations",
    "attempts", "artifacts", "evidence_links", "lifecycle_actions",
    "strategy_plans", "strategy_reviews", "attempt_interpretations",
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
    registered_id = _registered_artifact_id(workspace, normalized, digest)
    if registered_id is not None:
        bound_id = registered_id
    elif _is_attempt_output_ref(normalized):
        # Calculation outputs are owned by one Attempt. Keep identical bytes
        # from separate Attempts distinct so Research State can bind each
        # output to its own physical location and producer.
        bound_id = _attempt_artifact_id(normalized, digest)
    else:
        bound_id = artifact_id(normalized, digest)
    return {
        "artifact_id": bound_id,
        "path": normalized,
        "owner_node": owner_node,
        "source_intent_id": source_intent_id,
        "size_bytes": path.stat().st_size,
        "sha256": digest,
    }


def artifact_id(path: str, digest: str) -> str:
    """Derive a stable logical ID from both path and content digest."""

    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise WorkspaceArtifactError("artifact digest must be a SHA-256 value")
    digest_hex = digest.removeprefix("sha256:")
    if len(digest_hex) != 64 or any(char not in "0123456789abcdef" for char in digest_hex):
        raise WorkspaceArtifactError("artifact digest must be a SHA-256 value")
    # Artifact identity is content-addressed across capability, kernel, and
    # review transports. The logical path remains provenance, never identity.
    return "art_" + digest_hex


def _attempt_artifact_id(path: str, digest: str) -> str:
    """Derive a stable identity for one Attempt-owned output binding."""

    if not isinstance(path, str) or not path:
        raise WorkspaceArtifactError("artifact path must be a non-empty string")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise WorkspaceArtifactError("artifact digest must be a SHA-256 value")
    return "art_" + hashlib.sha256(f"{path}\0{digest}".encode("utf-8")).hexdigest()


def _is_attempt_output_ref(ref: str) -> bool:
    parts = PurePosixPath(ref).parts
    return (
        len(parts) >= 6
        and parts[0] == "nodes"
        and parts[2] == "attempts"
        and parts[4] == "outputs"
    )


def _registered_artifact_id(workspace: Path, path: str, digest: str) -> str | None:
    """Preserve an existing ID when re-resolving a registered artifact."""

    try:
        context = read_json(workspace / "research_map" / "context.json")
    except (OSError, ValueError):
        return None
    rows = context.get("artifacts", []) if isinstance(context, dict) else []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if (
            isinstance(row, dict)
            and row.get("location") == path
            and row.get("sha256") == digest
            and isinstance(row.get("id"), str)
        ):
            return row["id"]
    return None


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
    """Resolve a current Research workspace.

    Calculation files live inside the canonical Research workspace. The
    ResearchMap is the ownership authority; compute files remain ordinary
    workspace artifacts and never become claims by themselves.
    """

    workspace = lexical_path(root)
    if path_has_symlink(workspace):
        raise WorkspaceArtifactError(f"workspace root cannot contain a symbolic link: {workspace}")
    workspace_doc = workspace / "workspace_manifest.json"
    context_doc = workspace / "research_map" / "context.json"
    if not workspace.is_dir() or workspace.is_symlink():
        raise WorkspaceArtifactError(f"not an initialized TS workspace: {workspace}")
    try:
        identity = read_json(workspace_doc)
        identity = validate_workspace_manifest(identity, workspace)
    except (OSError, ValueError, WorkspaceModeError) as exc:
        # Preserve the compute-facing admission diagnostic when the manifest
        # is present but still in a writer-side state. Other malformed fields
        # remain a generic canonical-workspace error.
        try:
            raw_identity = read_json(workspace_doc)
        except (OSError, ValueError):
            raw_identity = None
        if isinstance(raw_identity, dict) and raw_identity.get("state") not in {"ready", "admission_pending"}:
            raise WorkspaceArtifactError(
                f"workspace is not ready for compute: {raw_identity.get('state', 'unknown')}"
            ) from exc
        raise WorkspaceArtifactError(f"invalid canonical workspace: {workspace}") from exc
    # The manifest is the Host-owned workspace admission boundary.  Compute
    # operations must never run against a partially initialized or failed
    # workspace, even when its canonical directories happen to exist.
    if identity.get("state") != "ready":
        raise WorkspaceArtifactError(
            f"workspace is not ready for compute: {identity.get('state', 'unknown')}"
        )
    if identity.get("workspace_root") and lexical_path(identity["workspace_root"]) != workspace:
        raise WorkspaceArtifactError("workspace identity does not match canonical root")
    if any(
        (workspace / name).exists() or (workspace / name).is_symlink()
        for name in RETIRED_WORKSPACE_FILES
    ):
        raise WorkspaceArtifactError("legacy ResearchMap storage is not supported by the canonical artifact workspace")
    for path in (workspace_doc, context_doc, workspace / "lifecycle" / "liveness.json", workspace / "nodes"):
        if has_symlink_component(workspace, path):
            raise WorkspaceArtifactError(f"workspace canonical path uses a symbolic link: {path.relative_to(workspace)}")
    if (
        not workspace_doc.is_file()
        or workspace_doc.is_symlink()
        or not context_doc.is_file()
        or context_doc.is_symlink()
        or not (workspace / "lifecycle" / "liveness.json").is_file()
        or not (workspace / "nodes").is_dir()
    ):
        raise WorkspaceArtifactError(f"not an initialized TS workspace: {workspace}")
    if identity.get("workspace_mode") != "research":
        raise WorkspaceArtifactError(f"unsupported workspace protocol: {workspace}")
    try:
        context = read_json(context_doc)
        liveness = read_json(workspace / "lifecycle" / "liveness.json")
    except (OSError, ValueError) as exc:
        raise WorkspaceArtifactError(f"cannot read canonical ResearchMap state: {exc}") from exc
    if not isinstance(context, dict) or context.get("schema_version") != "research_map_context_2":
        raise WorkspaceArtifactError("invalid ResearchMap context")
    if not isinstance(liveness, dict) or liveness.get("schema_version") != "research_liveness_2":
        raise WorkspaceArtifactError("invalid ResearchMap liveness")
    if context.get("workspace_id") != identity.get("workspace_id") or liveness.get("workspace_id") != identity.get("workspace_id"):
        raise WorkspaceArtifactError("workspace identity does not match canonical ResearchMap state")
    missing = [name for name in RESEARCH_CONTEXT_COLLECTIONS if name not in context]
    if missing:
        raise WorkspaceArtifactError("ResearchMap context is missing collections: " + ", ".join(missing))
    invalid = [name for name in RESEARCH_CONTEXT_COLLECTIONS if not isinstance(context[name], list)]
    if invalid:
        raise WorkspaceArtifactError("ResearchMap collections must be arrays: " + ", ".join(invalid))
    focus = context.get("focus")
    if not isinstance(focus, dict) or not isinstance(focus.get("claim_ids"), list) or not isinstance(focus.get("node_ids"), list):
        raise WorkspaceArtifactError("ResearchMap focus is invalid")
    if context.get("lifecycle_state") != liveness.get("state"):
        raise WorkspaceArtifactError("ResearchMap lifecycle state is inconsistent")
    if type(context.get("revision")) is not int or context["revision"] < 0 or liveness.get("revision") != context["revision"]:
        raise WorkspaceArtifactError("ResearchMap revision is inconsistent")
    return workspace


def workspace_node_ids(workspace: Path) -> set[str]:
    """Return validated ResearchNode identifiers from the canonical ResearchMap."""

    return {str(item["id"]) for item in workspace_node_records(workspace)}


def workspace_node_records(workspace: Path) -> list[dict[str, Any]]:
    """Return canonical serialized ResearchNode objects from the ResearchMap."""

    workspace = lexical_path(workspace)
    context_path = workspace / "research_map" / "context.json"
    manifest_path = workspace / "workspace_manifest.json"
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        raise WorkspaceArtifactError(f"cannot read workspace identity: {manifest_path}") from exc
    try:
        context = read_json(context_path)
    except (OSError, ValueError) as exc:
        raise WorkspaceArtifactError(f"cannot read ResearchMap context: {exc}") from exc
    values = context.get("nodes", []) if isinstance(context, dict) else []
    if not isinstance(values, list):
        raise WorkspaceArtifactError("ResearchMap context nodes must be an array")
    records = [dict(item) for item in values if isinstance(item, dict)]
    ids: set[str] = set()
    for record in records:
        node_id = record.get("id")
        if not isinstance(node_id, str) or NODE_ID.fullmatch(node_id) is None or node_id in ids:
            raise WorkspaceArtifactError("ResearchMap context contains an invalid node id")
        ids.add(node_id)
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
