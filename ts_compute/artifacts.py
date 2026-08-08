"""Deterministic discovery and binding of calculation input artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .contracts import ComputeContractError


CATALOG_SCHEMA_VERSION = "ts-compute-artifact-catalog/1"
ARTIFACT_ID_SCHEMA_VERSION = "ts-compute-artifact-id/1"
ROLE_SUFFIXES = {
    "gjf": frozenset({".gjf", ".com"}),
    "xyz": frozenset({".xyz"}),
    "control": frozenset({".inp"}),
    "config": frozenset({".json"}),
    "reactant": frozenset({".xyz"}),
    "product": frozenset({".xyz"}),
}
ELIGIBLE_SUFFIXES = frozenset(
    suffix for suffixes in ROLE_SUFFIXES.values() for suffix in suffixes
)


def list_calculation_artifacts(
    root: str | Path,
    *,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Build a read-only catalog from eligible workspace calculation files."""

    workspace = _workspace_root(root)
    if node_id is not None:
        node = _node_dir(workspace, node_id)
        if (
            not node.is_dir()
            or node.is_symlink()
            or not (node / "node.json").is_file()
            or (node / "node.json").is_symlink()
        ):
            raise ComputeContractError(f"unknown workspace node: {node_id}")
    artifacts = [
        item
        for item in _catalog_items(workspace)
        if node_id is None or item["owner_node"] == node_id
    ]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "workspace_root": str(workspace),
        "node_id": node_id,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def resolve_input_artifacts(
    workspace: Path,
    supplied: list[dict[str, str]],
    required_roles: set[str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Resolve logical artifact bindings into immutable path/hash snapshots."""

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

    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in _catalog_items(workspace):
        by_id.setdefault(str(item["artifact_id"]), []).append(item)

    refs: dict[str, str] = {}
    bindings: list[dict[str, Any]] = []
    for role in sorted(required_roles):
        artifact_id = by_role[role]
        matches = by_id.get(artifact_id, [])
        if not matches:
            raise ComputeContractError(f"unknown calculation artifact_id: {artifact_id}")
        if len(matches) != 1:
            paths = sorted(str(item["path"]) for item in matches)
            raise ComputeContractError(
                f"calculation artifact_id is ambiguous: {artifact_id}; matches={paths}"
            )
        artifact = matches[0]
        if role not in artifact["input_roles"]:
            raise ComputeContractError(
                f"artifact {artifact_id} is not compatible with input role {role}; "
                f"compatible_roles={artifact['input_roles']}"
            )
        path = str(artifact["path"])
        refs[role] = path
        bindings.append(
            {
                "input_role": role,
                "artifact_id": artifact_id,
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
    """Verify that every frozen intent binding still names the same local bytes."""

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

    for role, ref in sorted(refs.items()):
        binding = by_role[role]
        if binding.get("path") != ref:
            raise ComputeContractError(f"calculation input binding path mismatch for role {role}")
        current = _artifact_for_ref(workspace, str(ref))
        for key in ("artifact_id", "sha256", "owner_node", "source_intent_id"):
            if binding.get(key) != current.get(key):
                raise ComputeContractError(
                    f"calculation input binding changed for role {role}: {key} mismatch"
                )


def _catalog_items(workspace: Path) -> list[dict[str, Any]]:
    artifacts = [
        _artifact_for_path(workspace, path)
        for path in _eligible_paths(workspace)
    ]
    artifacts.sort(key=lambda item: str(item["path"]))
    return artifacts


def _eligible_paths(workspace: Path) -> Iterable[Path]:
    roots: list[Path] = []
    inputs = workspace / "inputs"
    if inputs.is_dir() and not inputs.is_symlink():
        roots.append(inputs)

    nodes = workspace / "nodes"
    if nodes.is_dir() and not nodes.is_symlink():
        for node in sorted(nodes.iterdir()):
            if (
                not node.is_dir()
                or node.is_symlink()
                or not _valid_node_id(node.name)
                or not (node / "node.json").is_file()
                or (node / "node.json").is_symlink()
            ):
                continue
            for name in ("inputs", "outputs"):
                candidate = node / name
                if candidate.is_dir() and not candidate.is_symlink():
                    roots.append(candidate)
            attempts = node / "attempts"
            if not attempts.is_dir() or attempts.is_symlink():
                continue
            for attempt in sorted(attempts.iterdir()):
                output = attempt / "outputs"
                if (
                    attempt.is_dir()
                    and not attempt.is_symlink()
                    and _valid_intent_id(attempt.name)
                    and output.is_dir()
                    and not output.is_symlink()
                ):
                    roots.append(output)

    seen: set[str] = set()
    for root in roots:
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = sorted(
                name for name in dirnames if not (current_path / name).is_symlink()
            )
            for name in sorted(filenames):
                path = current_path / name
                if path.suffix.lower() not in ELIGIBLE_SUFFIXES or path.is_symlink():
                    continue
                ref = path.relative_to(workspace).as_posix()
                if ref in seen:
                    continue
                try:
                    _safe_existing_path(workspace, ref)
                except ComputeContractError:
                    continue
                seen.add(ref)
                yield path


def _artifact_for_path(workspace: Path, path: Path) -> dict[str, Any]:
    return _artifact_for_ref(workspace, path.relative_to(workspace).as_posix())


def _artifact_for_ref(workspace: Path, ref: str) -> dict[str, Any]:
    normalized, path = _safe_existing_path(workspace, ref)
    owner_node, source_intent_id = _ownership(normalized)
    suffix = path.suffix.lower()
    roles = sorted(role for role, suffixes in ROLE_SUFFIXES.items() if suffix in suffixes)
    if not roles:
        raise ComputeContractError(f"unsupported calculation artifact type: {normalized}")
    digest = _sha256_file(path)
    return {
        "artifact_id": _artifact_id(owner_node, digest),
        "path": normalized,
        "owner_node": owner_node,
        "source_intent_id": source_intent_id,
        "size_bytes": path.stat().st_size,
        "sha256": digest,
        "input_roles": roles,
    }


def _artifact_id(owner_node: str | None, digest: str) -> str:
    material = json.dumps(
        {
            "schema_version": ARTIFACT_ID_SCHEMA_VERSION,
            "owner_node": owner_node,
            "sha256": digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "art_" + hashlib.sha256(material).hexdigest()[:24]


def _ownership(ref: str) -> tuple[str | None, str | None]:
    parts = PurePosixPath(ref).parts
    if len(parts) >= 2 and parts[0] == "inputs":
        return None, None
    if len(parts) >= 4 and parts[0] == "nodes" and parts[2] in {"inputs", "outputs"}:
        return parts[1], None
    if (
        len(parts) >= 6
        and parts[0] == "nodes"
        and parts[2] == "attempts"
        and parts[4] == "outputs"
    ):
        return parts[1], parts[3]
    raise ComputeContractError(
        "calculation artifacts must come from workspace inputs or node inputs/outputs"
    )


def _safe_existing_path(workspace: Path, value: str) -> tuple[str, Path]:
    text = str(value).replace("\\", "/").lstrip("@")
    if PurePosixPath(text).is_absolute():
        raise ComputeContractError(f"workspace path must be relative: {value}")
    normalized = posixpath.normpath(text)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ComputeContractError(f"invalid workspace path: {value}")
    owner_node, _ = _ownership(normalized)
    if owner_node is not None:
        node_record = workspace / "nodes" / owner_node / "node.json"
        if not _valid_node_id(owner_node) or not node_record.is_file() or node_record.is_symlink():
            raise ComputeContractError(f"calculation artifact owner node does not exist: {owner_node}")
    path = workspace.joinpath(*PurePosixPath(normalized).parts)
    if not path.is_file() or path.is_symlink():
        raise ComputeContractError(f"workspace calculation artifact does not exist: {normalized}")
    workspace_real = workspace.resolve(strict=True)
    expected = workspace_real.joinpath(*PurePosixPath(normalized).parts)
    if path.resolve(strict=True) != expected:
        raise ComputeContractError(f"workspace calculation artifact uses a symlink: {normalized}")
    return normalized, path


def _workspace_root(root: str | Path) -> Path:
    workspace = Path(root).expanduser().resolve()
    if not (workspace / "research_state.json").is_file() or not (workspace / "nodes").is_dir():
        raise ComputeContractError(f"not a TS workspace: {workspace}")
    return workspace


def _node_dir(workspace: Path, node_id: str) -> Path:
    if not _valid_node_id(node_id):
        raise ComputeContractError("invalid node_id")
    return workspace / "nodes" / node_id


def _valid_node_id(value: str) -> bool:
    alphanumeric = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return bool(value) and value[0] in alphanumeric and all(
        char in alphanumeric or char in "_.-" for char in value
    )


def _valid_intent_id(value: str) -> bool:
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
    return value.startswith("calc_") and len(value) > 5 and all(
        char in allowed for char in value[5:]
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
