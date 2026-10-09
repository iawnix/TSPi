"""Host-owned workspace identity and research memory initialization."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from research_agent.foundation.protocol import WORKSPACE_ID_PATTERN
from research_agent.foundation.path_safety import lexical_path, path_has_symlink
from research_agent.foundation.transactions import TransactionCoordinator, read_json, write_json, workspace_transaction

MANIFEST_SCHEMA = "research_workspace/2"
WORKSPACE_MODE = "research"
WORKSPACE_STATES = frozenset({"ready", "admission_pending"})
DIRECTORIES = ("inputs", "artifacts", "runs", "logs", "research", "operations", "environments", "reports")

class WorkspaceModeError(RuntimeError):
    pass

def _now():
    return datetime.now(timezone.utc).isoformat()

def validate_workspace_manifest(manifest, root, *, require_ready=False, validate_documents=True):
    root = lexical_path(root)
    if path_has_symlink(root):
        raise WorkspaceModeError("workspace_root_symlink")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise WorkspaceModeError("unsupported_workspace_manifest: create a new research workspace")
    if not isinstance(manifest.get("workspace_id"), str) or not WORKSPACE_ID_PATTERN.fullmatch(manifest["workspace_id"]):
        raise WorkspaceModeError("workspace_id_invalid")
    if manifest.get("workspace_root") != str(root) or manifest.get("workspace_mode") != "research":
        raise WorkspaceModeError("workspace_identity_mismatch")
    for field, value in {"profile_id": "research_workspace_3", "memory_profile": "session", "memory_scope": "session", "research_memory_scope": "workspace", "execution_profile": "audited"}.items():
        if manifest.get(field) != value:
            raise WorkspaceModeError("workspace_" + field + "_mismatch")
    if manifest.get("state") not in WORKSPACE_STATES or require_ready and manifest["state"] != "ready":
        raise WorkspaceModeError("workspace_admission_required")
    if manifest.get("directories") != list(DIRECTORIES):
        raise WorkspaceModeError("workspace_directories_mismatch")
    if manifest.get("research_memory") != {"initialized": True, "admission_required": manifest["state"] != "ready"}:
        raise WorkspaceModeError("workspace_research_memory_mismatch")
    if not validate_documents:
        return manifest
    for name in DIRECTORIES:
        path = root / name
        if path.is_symlink() or not path.is_dir():
            raise WorkspaceModeError("workspace_directory_invalid: " + name)
    for name, schema in (("journal", "research-journal/2"), ("map", "research-map/1")):
        path = root / "research" / (name + ".json")
        if path.is_symlink() or not path.is_file():
            raise WorkspaceModeError("research_document_missing: " + name)
        value = read_json(path)
        if value.get("schema_version") != schema:
            raise WorkspaceModeError("research_document_invalid: " + name)
        if name == "journal" and (type(value.get("sequence")) is not int or value["sequence"] < 0 or not isinstance(value.get("records"), list)):
            raise WorkspaceModeError("research_journal_invalid")
        if name == "map" and any(not isinstance(value.get(k), dict) for k in ("nodes", "results", "relations")):
            raise WorkspaceModeError("research_map_invalid")
    return manifest

@workspace_transaction("workspace.initialize")
def _initialize(root, request):
    root = Path(root)
    manifest = request["manifest"]
    write_json(root / "research/journal.json", {"schema_version": "research-journal/2", "sequence": 0, "records": []})
    write_json(root / "research/map.json", {"schema_version": "research-map/1", "nodes": {}, "results": {}, "relations": {}})
    write_json(root / "workspace_manifest.json", manifest)
    return manifest

def initialize_workspace(root, workspace_id, workspace_mode):
    root = lexical_path(root)
    if path_has_symlink(root):
        raise WorkspaceModeError("workspace_root_symlink")
    if workspace_mode != "research" or not isinstance(workspace_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise WorkspaceModeError("workspace_identity_invalid")
    _reject_nested_workspace(root, root / "workspace_manifest.json")
    if not (root / "workspace_manifest.json").exists():
        for marker in ("research/journal.json", "research/progress.json", "research_map", "research_map.json", "workspace.json"):
            if (root / marker).exists() or (root / marker).is_symlink():
                raise WorkspaceModeError("workspace_records_without_manifest: create a new workspace")
    existing_manifest = root / "workspace_manifest.json"
    if existing_manifest.exists():
        validate_workspace_manifest(read_json(existing_manifest), root, validate_documents=False)
    with TransactionCoordinator(root).locked():
        path = root / "workspace_manifest.json"
        if path.exists():
            manifest = validate_workspace_manifest(read_json(path), root)
            if manifest["workspace_id"] != workspace_id:
                raise WorkspaceModeError("workspace_id_mismatch")
            return manifest
        for name in DIRECTORIES:
            target = root / name
            if path_has_symlink(target):
                raise WorkspaceModeError("workspace_directory_symlink")
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
        manifest = {"schema_version": MANIFEST_SCHEMA, "workspace_id": workspace_id,
            "workspace_mode": "research", "profile_id": "research_workspace_3", "memory_profile": "session",
            "memory_scope": "session", "research_memory_scope": "workspace", "execution_profile": "audited",
            "workspace_root": str(root), "created_at": _now(), "state": "admission_pending",
            "directories": list(DIRECTORIES), "research_memory": {"initialized": True, "admission_required": True}}
        return _initialize(root, {"manifest": manifest})

@workspace_transaction("workspace.admit")
def _admit(root, request):
    root = Path(root)
    manifest = validate_workspace_manifest(read_json(root / "workspace_manifest.json"), root)
    if manifest["state"] != "ready":
        manifest.update(state="ready", admitted_at=_now(), research_memory={"initialized": True, "admission_required": False})
        write_json(root / "workspace_manifest.json", manifest)
    return manifest

def admit_research_workspace(root):
    root = lexical_path(root)
    if path_has_symlink(root):
        raise WorkspaceModeError("workspace_root_symlink")
    return _admit(root, {})

def read_workspace_mode(root):
    with TransactionCoordinator(root).locked():
        return validate_workspace_manifest(read_json(Path(root) / "workspace_manifest.json"), root)["workspace_mode"]

def _reject_nested_workspace(path: Path, manifest_path: Path) -> None:
    """Reject creating a workspace below or above another workspace root."""

    for parent in path.parents:
        if (parent / "workspace_manifest.json").is_file():
            raise WorkspaceModeError("workspace_nested_in_workspace")
        if (parent / "research" / "journal.json").is_file() or (
            parent / "research" / "progress.json"
        ).is_file():
            raise WorkspaceModeError("workspace_nested_in_workspace")
    if not path.is_dir():
        return
    for marker in path.rglob("workspace_manifest.json"):
        if marker != manifest_path and marker.is_file() and not marker.is_symlink():
            raise WorkspaceModeError("workspace_root_contains_workspace")
