"""File and JSON helpers for ChemGate workspace validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import Finding


def require_file(path: Path, findings: list[Finding]) -> None:
    """Append a missing-file finding when a required workspace file is absent."""

    if not path.exists():
        findings.append(Finding("error", "missing_required_file", f"missing required file {path.name}", path=path.name))


def read_json_optional(path: Path, findings: list[Finding]) -> dict[str, Any]:
    """Read optional JSON for validation, recording errors instead of raising."""

    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        findings.append(Finding("error", "json_read_error", f"failed to read JSON: {exc}", path=str(path)))
        return {}
    if not isinstance(payload, dict):
        findings.append(Finding("error", "json_root_not_object", "JSON root is not an object", path=str(path)))
        return {}
    return payload


def collect_node_dirs(source: Path) -> set[str]:
    """Return node ids that have directories under nodes/."""

    nodes_dir = source / "nodes"
    if not nodes_dir.exists():
        return set()
    return {child.name for child in nodes_dir.iterdir() if child.is_dir()}


def walk_values(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    """Walk nested lists and dicts to expose all values with key paths."""

    out = [(prefix, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            out.extend(walk_values(child, (*prefix, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(walk_values(child, (*prefix, str(index))))
    return out


__all__ = [
    "require_file",
    "read_json_optional",
    "collect_node_dirs",
    "walk_values",
]
