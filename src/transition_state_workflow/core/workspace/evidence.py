"""Generic evidence-registry writers for TS-search workspaces."""

from __future__ import annotations

import json
from pathlib import Path

from transition_state_workflow.config.state_contract import EVIDENCE_REGISTRY_SCHEMA
from transition_state_workflow.util.json_io import read_json_object_required
from transition_state_workflow.util.path_utils import portable_record_path, safe_identifier_token

from .io import relative_artifact_path, write_json
from .naming import utc_timestamp, workspace_slug
from .scaffold import ensure_workspace_root_has_manifest_and_tree


def append_evidence_record(
    root: Path,
    *,
    node_id: str,
    kind: str,
    path: Path | str,
    claim: str,
    evidence_state: str,
) -> str:
    """Append or update one v2 evidence-registry record."""

    registry_path = root / "evidence_registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {
            "schema": EVIDENCE_REGISTRY_SCHEMA,
            "system": root.name,
            "records": [],
            "updated_at": utc_timestamp(),
        }
    records = registry.setdefault("records", [])
    rel_path = relative_artifact_path(root, path)
    evidence_id = f"{node_id}:{kind}:{workspace_slug(Path(rel_path).name, kind)}"
    record = {
        "evidence_id": evidence_id,
        "node_id": node_id,
        "kind": kind,
        "path": rel_path,
        "claim": claim,
        "evidence_state": evidence_state,
        "recorded_at": utc_timestamp(),
    }
    for index, old in enumerate(records):
        if isinstance(old, dict) and old.get("evidence_id") == evidence_id:
            records[index] = record
            break
    else:
        records.append(record)
    registry["schema"] = EVIDENCE_REGISTRY_SCHEMA
    registry["updated_at"] = utc_timestamp()
    write_json(registry_path, registry)
    return evidence_id


def append_portable_evidence_record(
    *,
    root: Path,
    kind: str,
    path: str,
    node_id: str,
    claim: str,
    evidence_state: str,
) -> str:
    """Append one CLI-style portable evidence record and return its evidence id."""

    source = root.resolve()
    ensure_workspace_root_has_manifest_and_tree(source)
    registry_path = source / "evidence_registry.json"
    registry = read_json_object_required(registry_path)
    records = list(registry.get("records") or [])
    evidence_id = f"ev_{safe_identifier_token(node_id)}_{len(records) + 1:04d}"
    path_payload = portable_record_path(source, path)
    now = utc_timestamp()
    records.append(
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "path": path_payload["path"],
            "node_id": node_id,
            "claim": claim,
            "evidence_state": evidence_state,
            "external_path": path_payload["external_path"],
            "external_unavailable": path_payload["external_unavailable"],
            "created_at": now,
        }
    )
    registry["records"] = records
    registry["updated_at"] = utc_timestamp()
    write_json(registry_path, registry)
    return evidence_id


__all__ = ["append_evidence_record", "append_portable_evidence_record"]
