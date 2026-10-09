"""Immutable material manifests, owned alongside the payloads they describe."""
import re
from pathlib import Path
from research_agent.foundation.transactions import read_json, write_json
from research_agent.foundation.path_safety import path_has_symlink


def read_manifest(root, artifact_id):
    if not isinstance(artifact_id, str) or not re.fullmatch(r"art_[a-f0-9]{64}", artifact_id):
        raise ValueError("artifact_id_invalid")
    path = Path(root) / "artifacts" / artifact_id / "manifest.json"
    if path_has_symlink(path):
        raise ValueError("artifact_manifest_symlink")
    value = read_json(path)
    if value.get("artifact_id") != artifact_id or value.get("schema_version") != "material/1":
        raise ValueError("artifact_manifest_invalid")
    return value


def register_manifest(root, value):
    artifact_id = value["artifact_id"]
    material = {"schema_version": "material/1", **value}
    try:
        old = read_manifest(root, artifact_id)
    except FileNotFoundError:
        old = None
    if old is not None and old != material:
        raise ValueError("artifact_identity_reused")
    write_json(Path(root) / "artifacts" / artifact_id / "manifest.json", material)
    return material


def manifests(root):
    return [read_manifest(root, path.parent.name) for path in sorted((Path(root) / "artifacts").glob("*/manifest.json"))]
