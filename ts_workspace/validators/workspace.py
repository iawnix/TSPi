"""Workspace contract validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import read_json
from .decision import (
    FORBIDDEN_PUBLIC_FIELDS,
    VALID_CLAIM_VERDICTS,
    VALID_LIFECYCLES,
    VALID_PHASES,
    VALID_PROGRAM_STATUSES,
)

REQUIRED_FILES = {
    "manifest.json",
    "tree.json",
    "evidence_registry.json",
    "mechanism_model.json",
    "pathway_model.json",
    "knowledge_base.md",
}

REQUIRED_DIRS = {"inputs", "nodes", "reports", "accepted", "rejected"}


def validate_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    findings: list[dict[str, str]] = []

    for filename in sorted(REQUIRED_FILES):
        path = root_path / filename
        if not path.exists():
            _finding(findings, "error", "missing_file", f"missing {filename}", filename)

    for dirname in sorted(REQUIRED_DIRS):
        path = root_path / dirname
        if not path.is_dir():
            _finding(findings, "error", "missing_dir", f"missing {dirname}/", dirname)

    loaded: dict[str, Any] = {}
    for filename in sorted(REQUIRED_FILES - {"knowledge_base.md"}):
        path = root_path / filename
        if path.exists():
            try:
                loaded[filename] = read_json(path)
            except Exception as exc:  # noqa: BLE001
                _finding(findings, "error", "invalid_json", str(exc), filename)

    tree = loaded.get("tree.json", {})
    node_entries = tree.get("nodes", []) if isinstance(tree, dict) else []
    node_ids = set()
    if not isinstance(node_entries, list):
        _finding(findings, "error", "invalid_tree", "tree.nodes must be a list", "tree.json")
        node_entries = []

    for entry in node_entries:
        if not isinstance(entry, dict):
            _finding(findings, "error", "invalid_tree_node", "tree node entry must be an object", "tree.json")
            continue
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            _finding(findings, "error", "invalid_node_id", "tree node missing node_id", "tree.json")
            continue
        node_ids.add(node_id)
        node_path = root_path / "nodes" / node_id / "node.json"
        if not node_path.exists():
            _finding(findings, "error", "missing_node_json", f"missing node.json for {node_id}", str(node_path))
            continue
        try:
            node = read_json(node_path)
        except Exception as exc:  # noqa: BLE001
            _finding(findings, "error", "invalid_node_json", str(exc), str(node_path))
            continue
        _validate_node(node, node_id, findings, str(node_path))

    current_node = tree.get("current_node") if isinstance(tree, dict) else None
    if current_node is not None and current_node not in node_ids:
        _finding(findings, "error", "invalid_current_node", "tree.current_node does not exist", "tree.json")

    for filename, data in loaded.items():
        _reject_forbidden(data, findings, filename)

    evidence = loaded.get("evidence_registry.json", {}).get("evidence", [])
    if isinstance(evidence, list):
        ids: set[str] = set()
        for item in evidence:
            if not isinstance(item, dict):
                _finding(findings, "error", "invalid_evidence", "evidence entry must be an object", "evidence_registry.json")
                continue
            evidence_id = item.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                _finding(findings, "error", "invalid_evidence_id", "evidence entry missing evidence_id", "evidence_registry.json")
            elif evidence_id in ids:
                _finding(findings, "error", "duplicate_evidence_id", f"duplicate evidence {evidence_id}", "evidence_registry.json")
            else:
                ids.add(evidence_id)

    return {"valid": not any(item["severity"] == "error" for item in findings), "findings": findings}


def _validate_node(node: dict[str, Any], expected_id: str, findings: list[dict[str, str]], source: str) -> None:
    if node.get("node_id") != expected_id:
        _finding(findings, "error", "node_id_mismatch", "node_id does not match tree entry", source)
    if node.get("phase") not in VALID_PHASES:
        _finding(findings, "error", "invalid_phase", "node phase is invalid", source)
    lifecycle = node.get("lifecycle")
    if lifecycle not in VALID_LIFECYCLES:
        _finding(findings, "error", "invalid_lifecycle", "node lifecycle is invalid", source)
    if not isinstance(node.get("hypothesis"), str) or not node["hypothesis"].strip():
        _finding(findings, "error", "missing_hypothesis", "node hypothesis is required", source)

    closure = node.get("closure")
    if lifecycle == "running" and closure is not None:
        _finding(findings, "error", "running_node_has_closure", "running node cannot have closure", source)
    if lifecycle in {"closed", "stopped"}:
        if not isinstance(closure, dict):
            _finding(findings, "error", "missing_closure", "closed or stopped node requires closure", source)
            return
        if closure.get("program_status") not in VALID_PROGRAM_STATUSES:
            _finding(findings, "error", "invalid_program_status", "closure.program_status is invalid", source)
        if closure.get("claim_verdict") not in VALID_CLAIM_VERDICTS:
            _finding(findings, "error", "invalid_claim_verdict", "closure.claim_verdict is invalid", source)


def _reject_forbidden(value: Any, findings: list[dict[str, str]], path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_PUBLIC_FIELDS:
                _finding(findings, "error", "forbidden_public_field", f"forbidden field {key}", path)
            _reject_forbidden(nested, findings, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden(nested, findings, f"{path}[{index}]")


def _finding(findings: list[dict[str, str]], severity: str, code: str, message: str, path: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message, "path": path})
