"""Deterministic discovery and binding of workspace calculation artifacts.

Public callers use logical ``art_*`` identifiers. Physical paths remain an
implementation detail of this module and are frozen with a digest whenever a
calculation intent is created.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from ts_workspace.io import read_json
from ts_workspace.refs import ACT_ID

from .contracts import ComputeContractError


CATALOG_SCHEMA_VERSION = "ts-artifact-catalog/2"
ARTIFACT_ID_SCHEMA_VERSION = "ts-artifact-id/2"
INTENT_ID = re.compile(r"^calc_[A-Za-z0-9_.-]+$")
ROLE_SUFFIXES = {
    "gjf": frozenset({".gjf", ".com"}),
    "xyz": frozenset({".xyz"}),
    "control": frozenset({".inp"}),
    "config": frozenset({".json"}),
    "reactant": frozenset({".xyz"}),
    "product": frozenset({".xyz"}),
}
ELIGIBLE_SUFFIXES = frozenset({
    ".com", ".gif", ".gjf", ".inp", ".json", ".log", ".out", ".png", ".txt", ".xyz",
})


def list_calculation_artifacts(
    root: str | Path,
    *,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded catalog of files eligible as calculation inputs."""

    workspace = _workspace_root(root)
    known_acts = _act_ids(workspace)
    if act_id is not None and act_id not in known_acts:
        raise ComputeContractError(f"unknown ResearchAct: {act_id}")
    artifacts = [
        item
        for item in _catalog_items(workspace, known_acts)
        if act_id is None or item["owner_act"] == act_id
    ]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "workspace_root": str(workspace),
        "act_id": act_id,
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
    catalog = {item["artifact_id"]: item for item in _catalog_items(workspace, _act_ids(workspace))}
    missing = [artifact_id for artifact_id in requested if artifact_id not in catalog]
    if missing:
        raise ComputeContractError("unknown artifact_id: " + ", ".join(missing))
    return [catalog[artifact_id] for artifact_id in requested]


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
                "owner_act": artifact["owner_act"],
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
    known_acts = _act_ids(workspace)
    for role, ref in sorted(refs.items()):
        binding = by_role[role]
        if binding.get("path") != ref:
            raise ComputeContractError(f"calculation input binding path mismatch for role {role}")
        current = _artifact_for_ref(workspace, str(ref), known_acts)
        for key in ("artifact_id", "sha256", "owner_act", "source_intent_id"):
            if binding.get(key) != current.get(key):
                raise ComputeContractError(
                    f"calculation input binding changed for role {role}: {key} mismatch"
                )


def _catalog_items(workspace: Path, known_acts: set[str]) -> list[dict[str, Any]]:
    artifacts = [
        _artifact_for_path(workspace, path, known_acts)
        for path in _eligible_paths(workspace, known_acts)
    ]
    artifacts.sort(key=lambda item: str(item["path"]))
    return artifacts


def _eligible_paths(workspace: Path, known_acts: set[str]) -> Iterable[Path]:
    roots: list[Path] = []
    inputs = workspace / "inputs"
    if inputs.is_dir() and not inputs.is_symlink():
        roots.append(inputs)
    acts_root = workspace / "acts"
    if acts_root.is_dir() and not acts_root.is_symlink():
        for act_dir in sorted(acts_root.iterdir()):
            if not act_dir.is_dir() or act_dir.is_symlink() or act_dir.name not in known_acts:
                continue
            for name in ("inputs", "outputs"):
                candidate = act_dir / name
                if candidate.is_dir() and not candidate.is_symlink():
                    roots.append(candidate)
            attempts = act_dir / "attempts"
            if attempts.is_dir() and not attempts.is_symlink():
                for attempt in sorted(attempts.iterdir()):
                    output = attempt / "outputs"
                    if (
                        attempt.is_dir()
                        and not attempt.is_symlink()
                        and INTENT_ID.fullmatch(attempt.name)
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
                    _safe_existing_path(workspace, ref, known_acts)
                except ComputeContractError:
                    continue
                seen.add(ref)
                yield path


def _artifact_for_path(workspace: Path, path: Path, known_acts: set[str]) -> dict[str, Any]:
    return _artifact_for_ref(workspace, path.relative_to(workspace).as_posix(), known_acts)


def _artifact_for_ref(workspace: Path, ref: str, known_acts: set[str]) -> dict[str, Any]:
    normalized, path = _safe_existing_path(workspace, ref, known_acts)
    owner_act, source_intent_id = _ownership(normalized)
    roles = sorted(
        role for role, suffixes in ROLE_SUFFIXES.items() if path.suffix.lower() in suffixes
    )
    digest = _sha256_file(path)
    return {
        "artifact_id": _artifact_id(normalized, digest),
        "path": normalized,
        "owner_act": owner_act,
        "source_intent_id": source_intent_id,
        "size_bytes": path.stat().st_size,
        "sha256": digest,
        "input_roles": roles,
    }


def _artifact_id(path: str, digest: str) -> str:
    material = json.dumps(
        {"schema_version": ARTIFACT_ID_SCHEMA_VERSION, "path": path, "sha256": digest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "art_" + hashlib.sha256(material).hexdigest()[:24]


def _ownership(ref: str) -> tuple[str | None, str | None]:
    parts = PurePosixPath(ref).parts
    if len(parts) >= 2 and parts[0] == "inputs":
        return None, None
    if len(parts) >= 4 and parts[0] == "acts" and parts[2] in {"inputs", "outputs"}:
        return parts[1], None
    if len(parts) >= 6 and parts[0] == "acts" and parts[2] == "attempts" and parts[4] == "outputs":
        return parts[1], parts[3]
    raise ComputeContractError(
        "calculation artifacts must come from workspace inputs or ResearchAct inputs/outputs"
    )


def _safe_existing_path(
    workspace: Path,
    value: str,
    known_acts: set[str],
) -> tuple[str, Path]:
    text = str(value).replace("\\", "/").lstrip("@")
    if PurePosixPath(text).is_absolute():
        raise ComputeContractError(f"workspace path must be relative: {value}")
    normalized = posixpath.normpath(text)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ComputeContractError(f"invalid workspace path: {value}")
    owner_act, _ = _ownership(normalized)
    if owner_act is not None and owner_act not in known_acts:
        raise ComputeContractError(f"calculation artifact owner ResearchAct does not exist: {owner_act}")
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
    workspace_doc = workspace / "workspace.json"
    acts_doc = workspace / "research_acts.json"
    if not workspace_doc.is_file() or not acts_doc.is_file() or not (workspace / "acts").is_dir():
        raise ComputeContractError(f"not an initialized v4 TS workspace: {workspace}")
    if read_json(workspace_doc).get("schema_version") != "ts-workspace/4":
        raise ComputeContractError(f"unsupported workspace protocol: {workspace}")
    return workspace


def _act_ids(workspace: Path) -> set[str]:
    registry = read_json(workspace / "research_acts.json")
    if registry.get("schema_version") != "ts-research-act-registry/2":
        raise ComputeContractError("invalid ResearchAct registry")
    ids = {
        item.get("act_id")
        for item in registry.get("acts", [])
        if isinstance(item, dict) and isinstance(item.get("act_id"), str)
    }
    if any(ACT_ID.fullmatch(value) is None for value in ids):
        raise ComputeContractError("ResearchAct registry contains an invalid act_id")
    return ids


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
