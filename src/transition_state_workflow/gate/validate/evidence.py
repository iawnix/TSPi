"""Evidence-registry checks for ChemGate workspace validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import VALID_EVIDENCE_STATES
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, relative_path_or_absolute

from .common import iter_object_records, register_unique_id, validate_known_node_ref
from .contracts import Finding, PRE_EXECUTION_EVIDENCE_KEYS, REGISTRY_REQUIRED_SUFFIXES


def validate_evidence(source: Path, evidence: dict[str, Any], node_ids: list[str], findings: list[Finding]) -> None:
    """Validate evidence registry ids, states, node references, and paths."""

    records = list_or_empty(evidence.get("records"))
    seen_ids: set[str] = set()
    known_nodes = set(node_ids)
    for index, item in iter_object_records(
        records,
        findings,
        code="evidence_record_not_object",
        message_template="evidence record is not an object",
        path="evidence_registry.json",
    ):
        evidence_id = clean_string(item.get("evidence_id")) or f"record[{index}]"
        register_unique_id(
            evidence_id,
            seen_ids,
            findings,
            duplicate_code="duplicate_evidence_id",
            duplicate_message_template="duplicate evidence_id {value}",
            path="evidence_registry.json",
        )
        node_id = clean_string(item.get("node_id"))
        validate_known_node_ref(
            node_id,
            known_nodes,
            findings,
            code="evidence_missing_node",
            message="evidence references missing node",
            path="evidence_registry.json",
        )
        state = clean_string(item.get("evidence_state"))
        if state and state not in VALID_EVIDENCE_STATES:
            findings.append(Finding("warning", "unknown_evidence_state", f"unknown evidence state: {state}", path="evidence_registry.json", node_id=node_id))
        if not state:
            findings.append(Finding("error", "missing_evidence_state", "evidence record missing evidence_state", path="evidence_registry.json", node_id=node_id))
        legacy = [key for key in ("status", "state") if key in item]
        if legacy:
            findings.append(Finding("error", "legacy_evidence_fields", f"evidence record contains legacy fields: {', '.join(legacy)}", path="evidence_registry.json", node_id=node_id))
        path_text = clean_string(item.get("path"))
        if path_text:
            if Path(path_text).is_absolute() and not bool(item.get("external_path")):
                findings.append(Finding("warning", "absolute_evidence_path", "absolute evidence path should be marked external_path or made relative", path="evidence_registry.json", node_id=node_id))
            if not Path(path_text).is_absolute():
                target = source / path_text
                if not target.exists() and not bool(item.get("external_unavailable")):
                    findings.append(Finding("warning", "missing_evidence_path", f"evidence path does not exist: {path_text}", path="evidence_registry.json", node_id=node_id))


def validate_node_evidence_registry_coverage(
    *,
    source: Path,
    node_id: str,
    node_json: dict[str, Any],
    registry_paths: set[str],
    findings: list[Finding],
) -> None:
    """Warn when post-execution node evidence paths are absent from the registry."""

    node_evidence = node_json.get("evidence") if isinstance(node_json.get("evidence"), dict) else {}
    for key, value in node_evidence.items():
        if key in PRE_EXECUTION_EVIDENCE_KEYS or not isinstance(value, str):
            continue
        evidence_path = clean_string(value)
        if not evidence_path:
            continue
        if not path_should_have_registry_record(source, evidence_path):
            continue
        normalized = normalize_workspace_path(source, evidence_path)
        if normalized not in registry_paths:
            findings.append(
                Finding(
                    "warning",
                    "node_evidence_missing_registry_record",
                    f"node evidence path has no evidence_registry record: {evidence_path}",
                    path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                    node_id=node_id,
                )
            )


def path_should_have_registry_record(source: Path, raw_path: str) -> bool:
    """Return true for evidence-like files that should be registered."""

    path = Path(raw_path)
    target = path if path.is_absolute() else source / path
    if target.exists() and target.is_dir():
        return False
    return path.suffix.lower() in REGISTRY_REQUIRED_SUFFIXES


def group_evidence_records_by_node(evidence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return evidence registry records keyed by node id."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in list_or_empty(evidence.get("records")):
        if not isinstance(item, dict):
            continue
        node_id = clean_string(item.get("node_id"))
        if node_id:
            grouped.setdefault(node_id, []).append(item)
    return grouped


def group_registry_paths_by_node(source: Path, evidence: dict[str, Any]) -> dict[str, set[str]]:
    """Return normalized registry evidence paths keyed by node id."""

    grouped: dict[str, set[str]] = {}
    for item in list_or_empty(evidence.get("records")):
        if not isinstance(item, dict):
            continue
        node_id = clean_string(item.get("node_id"))
        path_text = clean_string(item.get("path"))
        if node_id and path_text:
            grouped.setdefault(node_id, set()).add(normalize_workspace_path(source, path_text))
    return grouped


def normalize_workspace_path(source: Path, raw_path: str) -> str:
    """Normalize an absolute or workspace-relative path for path set comparison."""

    path = Path(raw_path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(source.resolve()).as_posix()
        except ValueError:
            return str(path)
    return path.as_posix()


__all__ = [
    "validate_evidence",
    "validate_node_evidence_registry_coverage",
    "path_should_have_registry_record",
    "group_evidence_records_by_node",
    "group_registry_paths_by_node",
    "normalize_workspace_path",
]
