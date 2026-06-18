"""Helpers for deriving replacement chains from canonical backtrack events."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.util.path_utils import clean_string


def replacement_chain_nodes(
    *,
    from_node: str,
    to_node: str,
    backtrack_events: list[dict[str, Any]],
    parent_by_node: dict[str, str] | None = None,
) -> list[str]:
    """Return replacement nodes reachable through chained ``new_branch_node`` links.

    Canonical events stay immutable: A failed branch can be replaced by B, and if
    B later fails then B can be replaced by C. This helper derives that A is
    transitively replaced by C without requiring a redundant A -> C event.
    """

    source = clean_string(from_node)
    target_parent = clean_string(to_node)
    if not source or not target_parent:
        return []

    events_by_source: dict[str, list[dict[str, Any]]] = {}
    for event in backtrack_events:
        event_source = clean_string(event.get("from_node"))
        if event_source:
            events_by_source.setdefault(event_source, []).append(event)

    out: list[str] = []
    seen = {source}
    stack = [source]
    while stack:
        current = stack.pop()
        for event in events_by_source.get(current, []):
            if clean_string(event.get("to_node")) != target_parent:
                continue
            replacement = clean_string(event.get("new_branch_node"))
            if not replacement:
                continue
            if parent_by_node is not None and clean_string(parent_by_node.get(replacement)) != target_parent:
                continue
            if replacement in seen:
                continue
            seen.add(replacement)
            out.append(replacement)
            stack.append(replacement)
    return out


def replacement_chain_covers(
    *,
    from_node: str,
    to_node: str,
    replacement_node: str,
    backtrack_events: list[dict[str, Any]],
    parent_by_node: dict[str, str] | None = None,
) -> bool:
    """Return true if ``replacement_node`` is direct or transitive replacement."""

    replacement = clean_string(replacement_node)
    if not replacement:
        return False
    return replacement in replacement_chain_nodes(
        from_node=from_node,
        to_node=to_node,
        backtrack_events=backtrack_events,
        parent_by_node=parent_by_node,
    )


__all__ = ["replacement_chain_covers", "replacement_chain_nodes"]
