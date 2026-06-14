"""Generic evidence-registry writers for TS-search workspaces."""

from __future__ import annotations

import json
from pathlib import Path

from transition_state_workflow.config.state_contract import EVIDENCE_REGISTRY_SCHEMA

from .io import relative_artifact_path, write_json
from .naming import utc_timestamp, workspace_slug


def append_evidence_record(
    root: Path,
    *,
    node_id: str,
    kind: str,
    path: Path | str,
    claim: str,
    evidence_state: str,
) -> None:
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


__all__ = ["append_evidence_record"]
