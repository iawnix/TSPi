"""Core TS-search workspace state writers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import portable_record_path, safe_identifier_token


def append_ts_workspace_evidence_record_from_cli_args(args: argparse.Namespace) -> None:
    """Append one evidence registry record for a v2 workspace node."""

    append_ts_workspace_evidence_record(
        root=args.root,
        kind=args.kind,
        path=args.path,
        node_id=args.node_id,
        claim=args.claim,
        evidence_state=args.evidence_state,
    )


def append_ts_workspace_evidence_record(
    *,
    root: Path,
    kind: str,
    path: str,
    node_id: str,
    claim: str,
    evidence_state: str,
) -> str:
    """Append one evidence registry record and return its evidence id."""

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
    write_json_object(registry_path, registry, overwrite_existing=True)
    return evidence_id


def ensure_workspace_root_has_manifest_and_tree(root: Path) -> None:
    """Abort when root is missing the files required for a TS workspace."""

    missing = [name for name in ("manifest.json", "tree.json") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for workspace records."""

    return datetime.now(timezone.utc).isoformat()
