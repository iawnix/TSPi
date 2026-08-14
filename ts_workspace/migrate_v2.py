"""One-time, copy-only migration from a v2 workspace into canonical v3 state."""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from .engine_v3 import init_workspace
from .io import now_iso, read_json, write_json
from .model_v3 import NODE_SCHEMA
from .state_v3 import CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE, RESEARCH_STATE_FILE
from .validator_v3 import validate_workspace


class MigrationError(ValueError):
    """Raised when a source cannot be copied into a valid v3 workspace."""


def migrate_workspace_v2(source: str | Path, target: str | Path) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    target_root = Path(target).expanduser().resolve()
    if source_root == target_root:
        raise MigrationError("migration target must differ from the source workspace")
    if source_root.is_symlink() or not source_root.is_dir():
        raise MigrationError("source workspace must be a real directory")
    if target_root.exists():
        raise MigrationError("migration target already exists")
    _reject_symlinks(source_root)

    research_v2 = _read_object(source_root / RESEARCH_STATE_FILE, required=True)
    hypotheses_v2 = _read_object(source_root / "hypotheses.json", required=True)
    evidence_v2 = _read_object(source_root / EVIDENCE_FILE, required=True)
    if research_v2.get("schema_version") != "ts-research-state":
        raise MigrationError("source is not a v2 ts-research-state workspace")
    if hypotheses_v2.get("schema_version") != "ts-hypotheses":
        raise MigrationError("source hypotheses.json is not a v2 registry")

    init_workspace(target_root)
    timestamp = now_iso()
    node_rows = [row for row in research_v2.get("nodes", []) if isinstance(row, dict)]
    node_ids = _node_ids(node_rows)
    _copy_noncanonical_content(source_root, target_root, node_ids)
    claim_rows, claim_id_map = _migrate_claims(hypotheses_v2, node_ids, timestamp)
    evidence_rows, evidence_events, evidence_id_map = _migrate_evidence(
        evidence_v2,
        node_ids,
        target_root,
        timestamp,
    )
    nodes = _migrate_nodes(
        source_root,
        target_root,
        node_rows,
        node_ids,
        claim_rows,
        evidence_rows,
        timestamp,
    )

    focus_source = hypotheses_v2.get("focus_hypothesis_id")
    focus_claims = [claim_id_map[focus_source]] if focus_source in claim_id_map else []
    claims = {
        "schema_version": "ts-claim-registry/1",
        "focus_claim_refs": focus_claims,
        "claims": claim_rows,
    }
    evidence = {
        "schema_version": "ts-evidence-registry/2",
        "evidence": evidence_rows,
        "events": evidence_events,
    }
    research = {
        "schema_version": "ts-research-state/3",
        "nodes": [_node_summary(node) for node in nodes],
        "edges": [
            {"parent_node": node["parent_node"], "child_node": node["node_id"]}
            for node in nodes
            if node["parent_node"] is not None
        ],
        "open_nodes": [node["node_id"] for node in nodes if node["state"] == "open"],
        "branch_events": [
            {
                "node_id": node["node_id"],
                "parent_node": node["parent_node"],
                "decision_id": node["created_by_decision"],
                "created_at": node["opened_at"],
            }
            for node in nodes
        ],
        "accepted_refs": [],
        "provenance": [
            {
                "kind": "workspace_migration",
                "schema_version": "ts-workspace-migration/1",
                "source_schema": "ts-research-state",
                "source_root": str(source_root),
                "migrated_at": timestamp,
                "scientific_acceptance_carried_forward": False,
            }
        ],
    }
    write_json(target_root / RESEARCH_STATE_FILE, research)
    write_json(target_root / CLAIMS_FILE, claims)
    write_json(target_root / EVIDENCE_FILE, evidence)
    write_json(target_root / GATE_RESULTS_FILE, {"schema_version": "ts-gate-registry/1", "gate_results": []})
    for node in nodes:
        write_json(target_root / "nodes" / node["node_id"] / "node.json", node)

    report = {
        "schema_version": "ts-workspace-migration/1",
        "source_root": str(source_root),
        "target_root": str(target_root),
        "source_schema": "ts-research-state",
        "target_schema": "ts-research-state/3",
        "migrated_at": timestamp,
        "counts": {
            "nodes": len(nodes),
            "claims": len(claim_rows),
            "evidence": len(evidence_rows),
            "evidence_events": len(evidence_events),
            "gate_results": 0,
        },
        "id_maps": {"claims": claim_id_map, "evidence": evidence_id_map},
        "warnings": [
            "v2 accepted TS and audit records were not promoted to accepted_refs",
            "all migrated claims require v3 review before scientific acceptance",
            "deterministic gate results must be recomputed from active evidence",
        ],
    }
    write_json(target_root / "reports" / "migration_v2_to_v3.json", report)
    validation = validate_workspace(target_root)
    if not validation["valid"]:
        messages = "; ".join(item["message"] for item in validation["findings"] if item["severity"] == "error")
        raise MigrationError(f"migration produced an invalid v3 workspace: {messages}")
    return {**report, "validation": validation}


def _migrate_claims(
    hypotheses: dict[str, Any],
    node_ids: set[str],
    timestamp: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    source_rows = [row for row in hypotheses.get("hypotheses", []) if isinstance(row, dict)]
    mapping = _unique_id_map(
        [str(row.get("hypothesis_id") or f"hypothesis_{index}") for index, row in enumerate(source_rows)],
        prefix="claim_migrated_",
    )
    fallback_node = sorted(node_ids)[0] if node_ids else None
    claims: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows):
        source_id = str(row.get("hypothesis_id") or f"hypothesis_{index}")
        owner = str(row.get("source_node") or fallback_node or "")
        if owner not in node_ids:
            owner = str(fallback_node or "")
        if not owner:
            continue
        parent_source = row.get("parent_hypothesis_id")
        parent = mapping.get(str(parent_source)) if parent_source is not None else None
        claim = {
            "claim_id": mapping[source_id],
            "created_in_node": owner,
            "kind": "legacy-hypothesis/1",
            "statement": str(row.get("summary") or f"Migrated v2 hypothesis {source_id}"),
            "status": "inconclusive" if row.get("status") else "proposed",
            "required_gates": [],
            "evidence_refs": [],
            "gate_result_refs": [],
            "details": {"source_schema": "ts-hypotheses", "legacy_record": row},
            "created_by_decision": "migration_v2_to_v3",
            "created_at": timestamp,
            "history": [],
        }
        if parent is not None and parent != claim["claim_id"]:
            claim["parent_claim_id"] = parent
        claims.append(claim)
    return claims, mapping


def _migrate_evidence(
    registry: dict[str, Any],
    node_ids: set[str],
    target_root: Path,
    timestamp: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    source_rows = [row for row in registry.get("evidence", []) if isinstance(row, dict)]
    data_rows = [row for row in source_rows if row.get("role") != "evidence_lifecycle"]
    source_ids = [str(row.get("evidence_id") or f"evidence_{index}") for index, row in enumerate(data_rows)]
    mapping = _unique_id_map(source_ids, prefix="ev_migrated_")
    fallback_node = sorted(node_ids)[0] if node_ids else None
    records: list[dict[str, Any]] = []
    for index, row in enumerate(data_rows):
        source_id = str(row.get("evidence_id") or f"evidence_{index}")
        owner = str(row.get("node_id") or fallback_node or "")
        if owner not in node_ids:
            owner = str(fallback_node or "")
        if not owner:
            continue
        facts = dict(row.get("facts")) if isinstance(row.get("facts"), dict) else {}
        if isinstance(row.get("quality"), dict):
            facts["quality"] = row["quality"]
        for key in ("normal_termination", "diagnostics"):
            if key in row:
                facts[key] = row[key]
        provenance: dict[str, Any] = {
            "producer": "v2-workspace-migration",
            "producer_version": "1",
            "legacy_kind": row.get("kind"),
            "legacy_role": row.get("role"),
        }
        source_sha = row.get("source_sha256")
        if isinstance(source_sha, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", source_sha):
            provenance["source_sha256"] = source_sha
        record = {
            "schema_version": "ts-evidence/2",
            "evidence_id": mapping[source_id],
            "node_id": owner,
            "kind": _versioned_kind(row.get("kind")),
            "evidence_tier": _evidence_tier(row.get("evidence_tier")),
            "summary": str(row.get("summary") or f"Migrated v2 evidence {source_id}"),
            "facts": facts,
            "artifact_refs": _artifact_refs(row, target_root, owner),
            "provenance": provenance,
            "created_at": timestamp,
        }
        predecessor = row.get("supersedes_evidence_id")
        if predecessor is not None and str(predecessor) in mapping:
            record["supersedes_evidence_id"] = mapping[str(predecessor)]
        records.append(record)

    events: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows):
        if row.get("role") != "evidence_lifecycle":
            continue
        target_source = row.get("supersedes_evidence_id")
        state = row.get("lifecycle_status")
        if str(target_source) not in mapping or state not in {"withdrawn", "invalidated"}:
            continue
        events.append(
            {
                "event_id": f"ee_migrated_{index:04d}",
                "evidence_id": mapping[str(target_source)],
                "state": state,
                "reason": str(row.get("summary") or "Migrated v2 evidence lifecycle event."),
                "created_at": timestamp,
            }
        )
    return records, events, mapping


def _migrate_nodes(
    source_root: Path,
    target_root: Path,
    rows: list[dict[str, Any]],
    node_ids: set[str],
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    timestamp: str,
) -> list[dict[str, Any]]:
    claim_refs = _group_refs(claims, "created_in_node", "claim_id")
    evidence_refs = _group_refs(evidence, "node_id", "evidence_id")
    nodes: list[dict[str, Any]] = []
    for row in rows:
        node_id = str(row["node_id"])
        detail = _read_object(source_root / "nodes" / node_id / "node.json")
        parent = detail.get("parent_node", row.get("parent_node"))
        if parent not in node_ids:
            parent = None
        old_state = detail.get("lifecycle", row.get("lifecycle"))
        state = {"running": "open", "closed": "closed", "stopped": "stopped"}.get(old_state, "closed")
        opened_at = str(detail.get("opened_at") or detail.get("created_at") or timestamp)
        closed_at = str(detail.get("closed_at") or timestamp)
        tags = _legacy_tags(detail or row)
        result = None
        if state != "open":
            closure = detail.get("closure") if isinstance(detail.get("closure"), dict) else {}
            result = {
                "outcome": "stopped" if state == "stopped" else "completed",
                "summary": str(closure.get("summary") or f"Migrated closed v2 node {node_id}."),
                "claim_updates": [],
                "audit": None,
                "open_questions": [
                    str(item) for item in closure.get("open_questions", []) if isinstance(item, str) and item
                ],
            }
        node = {
            "schema_version": NODE_SCHEMA,
            "node_id": node_id,
            "parent_node": parent,
            "objective": str(detail.get("objective") or row.get("objective") or f"Migrated node {node_id}"),
            "state": state,
            "tags": tags,
            "claim_refs": claim_refs.get(node_id, []),
            "operation_refs": _existing_owner_refs(detail.get("operation_refs"), target_root, node_id),
            "evidence_refs": evidence_refs.get(node_id, []),
            "gate_result_refs": [],
            "created_by_decision": f"migration_start_{node_id}",
            "opened_at": opened_at,
            "artifacts": {
                "inputs": f"nodes/{node_id}/inputs",
                "outputs": f"nodes/{node_id}/outputs",
                "attempts": f"nodes/{node_id}/attempts",
                "scratch": f"nodes/{node_id}/scratch",
                "remote": f"nodes/{node_id}/remote",
            },
            "result": result,
        }
        if state != "open":
            node["closed_at"] = closed_at
            node["ended_by_decision"] = f"migration_end_{node_id}"
        nodes.append(node)
    return nodes


def _copy_noncanonical_content(source: Path, target: Path, node_ids: set[str]) -> None:
    for name in ("inputs", "reports"):
        source_dir = source / name
        if source_dir.is_dir():
            _copy_directory_contents(source_dir, target / name)
    for node_id in sorted(node_ids):
        source_node = source / "nodes" / node_id
        target_node = target / "nodes" / node_id
        target_node.mkdir(parents=True, exist_ok=True)
        if not source_node.is_dir():
            continue
        for path in sorted(source_node.iterdir()):
            if path.name == "node.json":
                continue
            destination = target_node / path.name
            if path.is_dir():
                shutil.copytree(path, destination, dirs_exist_ok=True)
            elif path.is_file():
                shutil.copy2(path, destination)
    for node_id in sorted(node_ids):
        for name in ("inputs", "outputs", "attempts", "scratch", "remote"):
            (target / "nodes" / node_id / name).mkdir(parents=True, exist_ok=True)


def _copy_directory_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        destination = target / path.name
        if path.is_dir():
            shutil.copytree(path, destination, dirs_exist_ok=True)
        elif path.is_file():
            shutil.copy2(path, destination)


def _artifact_refs(row: dict[str, Any], target: Path, owner: str) -> list[str]:
    values: list[Any] = []
    values.extend(row.get("artifact_refs", []) if isinstance(row.get("artifact_refs"), list) else [])
    values.extend(row.get("source_files", []) if isinstance(row.get("source_files"), list) else [])
    if row.get("path") is not None:
        values.append(row["path"])
    return _existing_owner_refs(values, target, owner)


def _existing_owner_refs(values: Any, target: Path, owner: str) -> list[str]:
    refs: list[str] = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, str) or "\\" in value:
            continue
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("nodes", owner):
            continue
        path = target.joinpath(*relative.parts)
        if path.is_file() and not path.is_symlink():
            refs.append(relative.as_posix())
    return list(dict.fromkeys(refs))


def _node_summary(node: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "node_id": node["node_id"],
        "parent_node": node["parent_node"],
        "objective": node["objective"],
        "state": node["state"],
        "tags": node["tags"],
    }
    if node["state"] != "open":
        summary["outcome"] = node["result"]["outcome"]
        summary["closed_at"] = node["closed_at"]
    return summary


def _legacy_tags(node: dict[str, Any]) -> list[str]:
    values = [
        node.get("node_type"),
        node.get("mechanism_action"),
        node.get("candidate_kind"),
        node.get("validation_scope"),
        node.get("audit_scope"),
    ]
    return list(dict.fromkeys(_tag(value) for value in values if value))[:32]


def _node_ids(rows: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for row in rows:
        node_id = row.get("node_id")
        if not isinstance(node_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", node_id):
            raise MigrationError(f"v2 node_id cannot be represented in v3: {node_id!r}")
        if node_id in values:
            raise MigrationError(f"duplicate v2 node_id: {node_id}")
        values.add(node_id)
    return values


def _unique_id_map(values: list[str], *, prefix: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for value in values:
        base = prefix + _slug(value)
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        mapping[value] = candidate
        used.add(candidate)
    return mapping


def _versioned_kind(value: Any) -> str:
    text = str(value or "legacy-evidence")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[0-9]+", text):
        return text
    return f"{_slug(text)}/1"


def _evidence_tier(value: Any) -> str:
    allowed = {"local_compute", "local_parse", "manual_observation", "literature", "user_provided", "hypothesis"}
    return str(value) if value in allowed else "manual_observation"


def _group_refs(rows: list[dict[str, Any]], owner_key: str, ref_key: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(str(row[owner_key]), []).append(str(row[ref_key]))
    return grouped


def _tag(value: Any) -> str:
    return _slug(str(value)).lower()[:128]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.-")
    return normalized or "record"


def _read_object(path: Path, *, required: bool = False) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise MigrationError(f"missing v2 workspace file: {path.name}")
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError) as exc:
        raise MigrationError(f"cannot read v2 JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"v2 JSON root must be an object: {path}")
    return value


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise MigrationError(f"source workspace contains a symbolic link: {path.relative_to(root)}")
