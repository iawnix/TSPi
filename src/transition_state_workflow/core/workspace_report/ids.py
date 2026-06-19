"""Node-id helpers for ChemKernel workspace report packets."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.util.path_utils import clean_string


def latest_node_id(nodes: list[tuple[str, dict[str, Any]]]) -> str | None:
    """Return the latest node id by numeric node prefix."""

    if not nodes:
        return None
    return sorted((node_id for node_id, _ in nodes), key=node_sort_key)[-1]


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
    "node_sort_key",
    "node_number",
]
