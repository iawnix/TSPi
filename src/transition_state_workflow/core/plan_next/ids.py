"""Node-id helpers for ChemKernel next-action planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.util.json_io import read_json_object_required
from transition_state_workflow.util.path_utils import clean_string, safe_identifier_token


def latest_node_id(nodes: list[tuple[str, dict[str, Any]]]) -> str | None:
    """Return the latest node id by numeric node prefix."""

    if not nodes:
        return None
    return sorted((node_id for node_id, _ in nodes), key=node_sort_key)[-1]


def next_suggested_node_id(root: Path, stage: str) -> str:
    """Return an unused nNNN_stage node id."""

    used_numbers: list[int] = []
    used_ids: set[str] = set()
    tree_path = root / "tree.json"
    if tree_path.exists():
        try:
            tree = read_json_object_required(tree_path)
            tree_nodes = tree.get("nodes") if isinstance(tree.get("nodes"), dict) else {}
            used_ids.update(str(key) for key in tree_nodes)
        except ValueError:
            pass
    nodes_dir = root / "nodes"
    if nodes_dir.exists():
        used_ids.update(path.name for path in nodes_dir.iterdir() if path.is_dir())
    for node_id in used_ids:
        number = node_number(node_id)
        if number is not None:
            used_numbers.append(number)
    next_number = 10 if not used_numbers else max(used_numbers) + 10
    slug = safe_identifier_token(stage)
    candidate = f"n{next_number:03d}_{slug}"
    while candidate in used_ids:
        next_number += 10
        candidate = f"n{next_number:03d}_{slug}"
    return candidate


def node_sort_key(node_id: str) -> tuple[int, str]:
    """Sort nNNN node ids naturally while keeping nonstandard ids stable."""

    number = node_number(node_id)
    return (number if number is not None else 999999, node_id)


def node_number(node_id: str) -> int | None:
    """Extract the numeric nNNN prefix from a node id."""

    text = clean_string(node_id)
    if len(text) < 4 or not text.startswith("n") or not text[1:4].isdigit():
        return None
    return int(text[1:4])


__all__ = [
    "latest_node_id",
    "next_suggested_node_id",
    "node_sort_key",
    "node_number",
]
