"""Workspace mode binding used by the public ResearchAgent launcher.

The launcher is a Host boundary, so it may create and admit a workspace, but
it does not implement ResearchMap mutations.  The manifest is deliberately
small and matches the transport-neutral Research Agent workspace contract.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "research_state_workspace_1"
WORKSPACE_MODE = "research"
WORKSPACE_STATES = frozenset({"initializing", "ready", "admission_pending", "failed"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")

_COMMON_DIRECTORIES = ("inputs", "artifacts", "runs", "logs")
RETIRED_WORKSPACE_FILES = (
    "workspace.json", "research_map.json", "research.db", "transactions.jsonl",
    "research_state.json", "phases.json", "claims.json", "claim_relations.json",
    "research_nodes.json", "observations.json", "proof_specs.json",
    "validation_results.json", "findings.json", "gate_specs.json", "gate_results.json",
    "decision_log.jsonl", "transaction_log.jsonl",
)
_RESEARCH_DIRECTORIES = (
        "research_map",
        "memory",
        "lifecycle",
        "checkpoints",
        "nodes",
        "evidence",
        "monitor",
        "environments",
)
RESEARCH_CONTEXT_COLLECTIONS = (
    "phases", "claims", "nodes", "findings", "gates", "claim_relations",
    "attempts", "artifacts", "evidence_links", "lifecycle_actions",
    "strategy_plans", "strategy_reviews", "attempt_interpretations",
)


class WorkspaceModeError(RuntimeError):
    """Raised when a workspace mode cannot be created or attached safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise WorkspaceModeError(f"{field} must be a non-empty identifier")
    return value


def _mode(value: Any) -> str:
    if value != WORKSPACE_MODE:
        raise WorkspaceModeError("workspace_mode must be research")
    return WORKSPACE_MODE


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise WorkspaceModeError(f"workspace_manifest_symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceModeError(f"workspace_manifest_missing: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceModeError(f"workspace_manifest_invalid: {path}") from exc
    if not isinstance(value, dict):
        raise WorkspaceModeError("workspace_manifest_invalid: object required")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _validate(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise WorkspaceModeError("unsupported_workspace_manifest")
    _identifier(manifest.get("workspace_id"), "workspace_id")
    workspace_mode = _mode(manifest.get("workspace_mode"))
    expected_state_scope = "workspace"
    if Path(str(manifest.get("workspace_root", ""))).expanduser().resolve() != root.resolve():
        raise WorkspaceModeError("workspace_root_mismatch")
    if manifest.get("profile_id") != f"{workspace_mode}_workspace_1":
        raise WorkspaceModeError(f"workspace_profile_id_mismatch: expected {workspace_mode}_workspace_1")
    if manifest.get("memory_profile") != "session":
        raise WorkspaceModeError("workspace_memory_profile_mismatch: expected session")
    if manifest.get("memory_scope") != "session":
        raise WorkspaceModeError("workspace_memory_scope_mismatch: expected session")
    if manifest.get("research_state_scope") != expected_state_scope:
        raise WorkspaceModeError(
            f"workspace_research_state_scope_mismatch: expected {expected_state_scope}"
        )
    if manifest.get("execution_profile") != "audited":
        raise WorkspaceModeError("workspace_execution_profile_mismatch")
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"]:
        raise WorkspaceModeError("workspace_created_at_missing")
    if manifest.get("state") not in WORKSPACE_STATES:
        raise WorkspaceModeError("invalid_workspace_state")
    directories = manifest.get("directories")
    expected_directories = [*_COMMON_DIRECTORIES, *_RESEARCH_DIRECTORIES]
    if (not isinstance(directories, list)
            or len(directories) != len(expected_directories)
            or len(set(directories)) != len(expected_directories)
            or any(directory not in directories for directory in expected_directories)):
        raise WorkspaceModeError("workspace_directories_mismatch")
    kernel = manifest.get("research_state")
    if not isinstance(kernel, dict) or kernel.get("initialized") is not True:
        raise WorkspaceModeError("workspace_research_state_mismatch")
    if not isinstance(kernel.get("admission_required"), bool):
        raise WorkspaceModeError("workspace_research_state_mismatch")
    if kernel["admission_required"] != (manifest["state"] != "ready"):
        raise WorkspaceModeError("workspace_research_state_mismatch")
    if (not isinstance(kernel.get("revision"), int)
            or isinstance(kernel.get("revision"), bool)
            or kernel["revision"] < 0):
        raise WorkspaceModeError("workspace_research_state_mismatch")
    return manifest


def _validate_layout(
    manifest: dict[str, Any],
    root: Path,
    *,
    allow_partial_admission: bool = False,
) -> None:
    """Reject manifests whose declared physical layout is incomplete."""

    if root.is_symlink() or not root.is_dir():
        raise WorkspaceModeError("workspace_root_invalid")
    # ``initializing`` and ``failed`` are writer-side transaction states. They
    # are never attachable runtime states; accepting them here would let the
    # Python readers open a workspace that the JS Host rejects.
    if manifest.get("state") not in {"ready", "admission_pending"}:
        raise WorkspaceModeError(f"workspace_not_attachable: {manifest.get('state')}")
    for name in RETIRED_WORKSPACE_FILES:
        path = root / name
        if path.exists() or path.is_symlink():
            raise WorkspaceModeError(f"legacy_workspace_layout: {name}")
    for directory in manifest["directories"]:
        path = root / directory
        if path.is_symlink() or not path.is_dir():
            raise WorkspaceModeError(f"workspace_directory_invalid: {directory}")
    required_files = (
        root / "research_map/context.json",
        root / "lifecycle/liveness.json",
        root / "memory/index.json",
        root / "checkpoints/checkpoint_0.json",
    )
    if any(path.is_symlink() or not path.is_file() for path in required_files):
        raise WorkspaceModeError("research_workspace_documents_missing")
    try:
        context = _read_json(root / "research_map/context.json")
        liveness = _read_json(root / "lifecycle/liveness.json")
        memory = _read_json(root / "memory/index.json")
        checkpoint = _read_json(root / "checkpoints/checkpoint_0.json")
    except WorkspaceModeError as exc:
        raise WorkspaceModeError("research_workspace_documents_invalid") from exc
    if context.get("schema_version") != "research_map_context_1":
        raise WorkspaceModeError("unsupported_research_context_schema")
    if context.get("workspace_id") != manifest["workspace_id"]:
        raise WorkspaceModeError("research_workspace_id_mismatch")
    if context.get("workspace_mode") != "research":
        raise WorkspaceModeError("research_workspace_mode_required")
    if not isinstance(context.get("created_at"), str) or not context["created_at"]:
        raise WorkspaceModeError("research_context_created_at_missing")
    missing = [name for name in RESEARCH_CONTEXT_COLLECTIONS if name not in context]
    if missing:
        raise WorkspaceModeError("research_context_missing_collections: " + ", ".join(missing))
    invalid = [name for name in RESEARCH_CONTEXT_COLLECTIONS if not isinstance(context.get(name), list)]
    if invalid:
        raise WorkspaceModeError("research_context_collections_must_be_arrays: " + ", ".join(invalid))
    if (not isinstance(context.get("focus"), dict)
            or not isinstance(context["focus"].get("claim_ids"), list)
            or not isinstance(context["focus"].get("node_ids"), list)):
        raise WorkspaceModeError("research_context_invalid")
    if (liveness.get("schema_version") != "research_liveness_1"
            or liveness.get("workspace_id") != manifest["workspace_id"]
            or liveness.get("state") not in {"admission_pending", "admitted"}
            or type(liveness.get("revision")) is not int
            or liveness["revision"] < 0):
        raise WorkspaceModeError("research_liveness_invalid")
    revision = context.get("revision")
    if (memory.get("schema_version") != "research_memory_index_1"
            or memory.get("workspace_id") != manifest["workspace_id"]
            or memory.get("scope") != "workspace"
            or memory.get("authority") != "research_memory"
            or memory.get("state_authority") != "research_state"
            or type(memory.get("revision")) is not int
            or memory["revision"] < 0
            or type(memory.get("context_revision")) is not int
            or memory["context_revision"] < 0
            or not isinstance(memory.get("entries"), list)
            or type(revision) is not int
            or isinstance(revision, bool)
            or memory["revision"] > revision
            or memory["context_revision"] > revision):
        raise WorkspaceModeError("research_memory_invalid")
    if (context.get("lifecycle_state") not in {"admission_pending", "admitted"}
            or (context.get("lifecycle_state") != liveness.get("state")
                and not (
                    allow_partial_admission
                    and manifest["state"] == "admission_pending"
                    and {context.get("lifecycle_state"), liveness.get("state")} == {"admission_pending", "admitted"}
                ))
            or type(revision) is not int or revision < 0
            or liveness["revision"] != revision):
        raise WorkspaceModeError("research_revision_mismatch")
    if (checkpoint.get("schema_version") != "research_checkpoint_1"
            or checkpoint.get("workspace_id") != manifest["workspace_id"]):
        raise WorkspaceModeError("research_checkpoint_invalid")
    admitted = context.get("lifecycle_state") == "admitted" and liveness.get("state") == "admitted"
    if manifest["state"] == "ready" and not admitted:
        raise WorkspaceModeError("research_manifest_state_mismatch")
    if manifest["research_state"]["revision"] != revision:
        raise WorkspaceModeError("workspace_revision_mismatch")


def validate_workspace_manifest(
    manifest: dict[str, Any],
    root: str | Path,
    *,
    require_ready: bool = False,
    allow_partial_admission: bool = False,
) -> dict[str, Any]:
    """Validate one canonical manifest and its physical state projections."""

    if not isinstance(manifest, dict):
        raise WorkspaceModeError("workspace_manifest_invalid")
    requested = Path(root).expanduser()
    if requested.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested}")
    path = requested.resolve()
    result = _validate(manifest, path)
    if require_ready and result.get("state") != "ready":
        raise WorkspaceModeError(f"workspace_admission_required: {result.get('state')}")
    _validate_layout(result, path, allow_partial_admission=allow_partial_admission)
    return result


def _research_seed(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    created_at = manifest["created_at"]
    workspace_id = manifest["workspace_id"]
    collections = {name: [] for name in RESEARCH_CONTEXT_COLLECTIONS}
    return {
        "context": {
            "schema_version": "research_map_context_1",
            "workspace_id": workspace_id,
            "map_id": f"map_{workspace_id}",
            "title": workspace_id,
            "created_at": created_at,
            "workspace_mode": "research",
            "memory_scope": manifest["memory_scope"],
            "research_state_scope": manifest["research_state_scope"],
            "revision": 0,
            "lifecycle_state": "admission_pending",
            "lifecycle": "admission_pending",
            "disposition": None,
            "checkpoint_id": "checkpoint_0",
            **collections,
            "focus": {"claim_ids": [], "node_ids": []},
        },
        "liveness": {
            "schema_version": "research_liveness_1",
            "workspace_id": workspace_id,
            "memory_scope": manifest["memory_scope"],
            "research_state_scope": manifest["research_state_scope"],
            "state": "admission_pending",
            "lifecycle": "admission_pending",
            "disposition": None,
            "checkpoint_id": "checkpoint_0",
            "revision": 0,
        },
        "memory": {
            "schema_version": "research_memory_index_1",
            "workspace_id": workspace_id,
            "scope": "workspace",
            "authority": "research_memory",
            "state_authority": "research_state",
            "revision": 0,
            "context_revision": 0,
            "lifecycle": "admission_pending",
            "disposition": None,
            "checkpoint_id": "checkpoint_0",
            "focus": {"claim_ids": [], "node_ids": []},
            "entries": [],
        },
        "checkpoint": {
            "schema_version": "research_checkpoint_1",
            "checkpoint_id": "checkpoint_0",
            "workspace_id": workspace_id,
            "kind": "workspace_genesis",
            "revision": 0,
            "lifecycle_state": "admission_pending",
            "created_at": created_at,
        },
    }


def initialize_workspace(root: str | Path, workspace_id: str, workspace_mode: str) -> dict[str, Any]:
    """Create or attach a mode-bound workspace manifest."""

    requested_path = Path(root).expanduser()
    if requested_path.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested_path}")
    path = requested_path.resolve()
    identifier = _identifier(workspace_id, "workspace_id")
    selected_mode = _mode(workspace_mode)
    manifest_path = path / "workspace_manifest.json"
    # The manifest is the sole workspace identity authority.  Do this check
    # before both the create and attach paths so a previously valid workspace
    # cannot silently re-enter the runtime after an old ResearchMap store is
    # copied into it.  The JavaScript WorkspacePort applies the same closed
    # world rule; keeping it here prevents the Python launcher/CLI from
    # accepting a mixed layout that the Host would later reject.
    for name in RETIRED_WORKSPACE_FILES:
        if (path / name).exists() or (path / name).is_symlink():
            raise WorkspaceModeError(f"legacy_workspace_layout: {name}")
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = _validate(_read_json(manifest_path), path)
        if manifest["workspace_id"] != identifier:
            raise WorkspaceModeError("workspace_id_mismatch")
        if manifest["workspace_mode"] != selected_mode:
            raise WorkspaceModeError("workspace_mode_mismatch")
        if manifest["state"] not in {"ready", "admission_pending"}:
            raise WorkspaceModeError(f"workspace_initialization_incomplete: {manifest['state']}")
        _validate_layout(
            manifest,
            path,
            allow_partial_admission=manifest["state"] == "admission_pending",
        )
        return manifest

    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    created_at = _now()
    initial_state = "admission_pending"
    directories = [*_COMMON_DIRECTORIES, *_RESEARCH_DIRECTORIES]
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "workspace_id": identifier,
        "workspace_mode": selected_mode,
        "profile_id": f"{selected_mode}_workspace_1",
        # The ResearchMap is durable workspace state; conversational memory
        # remains session-scoped.
        "memory_profile": "session",
        "memory_scope": "session",
        "research_state_scope": "workspace",
        "execution_profile": "audited",
        "state": initial_state,
        "workspace_root": str(path),
        "created_at": created_at,
        "directories": directories,
        "research_state": {"initialized": True, "admission_required": True, "revision": 0},
    }
    _write_json(manifest_path, {**manifest, "state": "initializing"})
    try:
        for directory in directories:
            directory_path = path / directory
            directory_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory_path.chmod(0o700)
        seed = _research_seed(manifest)
        _write_json(path / "research_map/context.json", seed["context"])
        _write_json(path / "lifecycle/liveness.json", seed["liveness"])
        # Initial projection is a workspace bootstrap artifact. Subsequent
        # revisions are written only by research-memory's ProjectionWriter.
        _write_json(path / "memory/index.json", seed["memory"])
        _write_json(path / "checkpoints/checkpoint_0.json", seed["checkpoint"])
        _write_json(manifest_path, manifest)
        return manifest
    except BaseException as exc:
        _write_json(manifest_path, {**manifest, "state": "failed", "failure": str(exc)})
        raise


def admit_research_workspace(root: str | Path) -> dict[str, Any]:
    """Perform the Host-only admission transition for a research workspace."""

    requested_path = Path(root).expanduser()
    if requested_path.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested_path}")
    path = requested_path.resolve()
    manifest_path = path / "workspace_manifest.json"
    manifest = _validate(_read_json(manifest_path), path)
    _validate_layout(manifest, path, allow_partial_admission=True)
    if manifest["workspace_mode"] != "research":
        raise WorkspaceModeError("workspace_admission_not_required")
    if manifest["state"] != "admission_pending":
        if manifest["state"] != "ready":
            raise WorkspaceModeError(f"workspace_admission_invalid_state: {manifest['state']}")
    admitted_at = _now()
    context_path = path / "research_map/context.json"
    liveness_path = path / "lifecycle/liveness.json"
    context = _read_json(context_path)
    liveness = _read_json(liveness_path)
    if context.get("schema_version") != "research_map_context_1" or context.get("workspace_mode") != "research":
        raise WorkspaceModeError("unsupported_research_context_schema")
    if liveness.get("schema_version") != "research_liveness_1":
        raise WorkspaceModeError("unsupported_research_liveness_schema")
    if context.get("workspace_id") != manifest["workspace_id"] or liveness.get("workspace_id") != manifest["workspace_id"]:
        raise WorkspaceModeError("research_workspace_identity_mismatch")
    missing = [name for name in RESEARCH_CONTEXT_COLLECTIONS if name not in context]
    invalid = [name for name in RESEARCH_CONTEXT_COLLECTIONS if not isinstance(context.get(name), list)]
    if missing:
        raise WorkspaceModeError("research_context_missing_collections: " + ", ".join(missing))
    if invalid:
        raise WorkspaceModeError("research_context_collections_must_be_arrays: " + ", ".join(invalid))
    focus = context.get("focus")
    if not isinstance(focus, dict) or not isinstance(focus.get("claim_ids"), list) or not isinstance(focus.get("node_ids"), list):
        raise WorkspaceModeError("research_context_focus_invalid")
    if context.get("lifecycle_state") not in {"admission_pending", "admitted"} \
        or liveness.get("state") not in {"admission_pending", "admitted"} \
        or (
            context.get("lifecycle_state") != liveness.get("state")
            and not (
                manifest["state"] == "admission_pending"
                and {context.get("lifecycle_state"), liveness.get("state")} == {"admission_pending", "admitted"}
            )
        ) \
        or context.get("revision") != liveness.get("revision"):
        raise WorkspaceModeError("research_lifecycle_state_mismatch")
    context_admitted = context.get("lifecycle_state") == "admitted"
    liveness_admitted = liveness.get("state") == "admitted"
    # Admission spans context and liveness documents. A process crash between
    # those replacements must be repairable on the next Host open.
    if manifest["state"] == "ready" and context_admitted != liveness_admitted:
        raise WorkspaceModeError("research_lifecycle_state_mismatch")
    if context_admitted != liveness_admitted:
        if context_admitted:
            _write_json(liveness_path, {
                **liveness,
                "state": "admitted",
                "lifecycle": context.get("lifecycle", "idle"),
                "disposition": context.get("disposition"),
                "checkpoint_id": context.get("checkpoint_id", "checkpoint_0"),
                "admitted_at": context.get("admitted_at", admitted_at),
            })
            liveness_admitted = True
        else:
            _write_json(context_path, {
                **context,
                "lifecycle_state": "admitted",
                "lifecycle": liveness.get("lifecycle", "idle"),
                "disposition": liveness.get("disposition"),
                "checkpoint_id": liveness.get("checkpoint_id", "checkpoint_0"),
                "admitted_at": liveness.get("admitted_at", admitted_at),
            })
            context_admitted = True
    if manifest["state"] == "ready":
        # A ready workspace may carry any admitted lifecycle projection
        # (waiting_external, decision_needed, blocked, terminal, ...). Host
        # restart must reopen it so Root can inspect or checkpoint that state;
        # only admission facts must agree here.
        if not context_admitted or not liveness_admitted:
            raise WorkspaceModeError("research_manifest_state_mismatch")
        return manifest
    elif not context_admitted:
        # Research State admission may have completed both projections before the
        # Host crashed while replacing the manifest. Preserve that durable
        # pair on retry; only perform the initial admission write when the
        # projections are still pending. Resetting an already-admitted
        # checkpoint here would silently erase its lifecycle disposition.
        _write_json(context_path, {
            **context, "lifecycle_state": "admitted", "lifecycle": "idle", "disposition": None,
            "checkpoint_id": context.get("checkpoint_id", "checkpoint_0"), "admitted_at": admitted_at,
        })
        _write_json(liveness_path, {
            **liveness, "state": "admitted", "lifecycle": "idle", "disposition": None,
            "checkpoint_id": liveness.get("checkpoint_id", "checkpoint_0"), "admitted_at": admitted_at,
        })
    admitted = {
        **manifest,
        "state": "ready",
        "admitted_at": admitted_at,
        "research_state": {**manifest["research_state"], "admission_required": False, "revision": context.get("revision", 0)},
    }
    _write_json(manifest_path, admitted)
    return admitted


def read_workspace_mode(root: str | Path) -> str:
    """Read the immutable mode from an existing framework workspace."""

    requested_path = Path(root).expanduser()
    if requested_path.is_symlink():
        raise WorkspaceModeError(f"workspace_root_symlink: {requested_path}")
    path = requested_path.resolve()
    manifest = _validate(_read_json(path / "workspace_manifest.json"), path)
    _validate_layout(manifest, path)
    return manifest["workspace_mode"]
