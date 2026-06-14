"""Timeline and backtrack event checks for ChemGate workspace validation."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.config.state_contract import VALID_BACKTRACK_EVENT_STATES
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .common import (
    evidence_ids_from_records,
    iter_object_records,
    register_unique_id,
    validate_evidence_refs,
    validate_known_node_ref,
)
from .contracts import Finding


def validate_tree_events(
    tree: dict[str, Any],
    node_ids: list[str],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate canonical timeline and backtrack events in tree.json."""

    if "branch_decisions" in tree:
        findings.append(Finding("error", "legacy_branch_decisions", "tree.json contains legacy branch_decisions; use events[]", path="tree.json"))
    if "backtrack_edges" in tree:
        findings.append(Finding("error", "legacy_backtrack_edges", "tree.json contains legacy backtrack_edges; use backtrack_events[]", path="tree.json"))
    known_nodes = set(node_ids)
    evidence_ids = evidence_ids_from_records(evidence)
    seen_event_ids: set[str] = set()
    for _index, event in iter_object_records(
        list_or_empty(tree.get("events")),
        findings,
        code="event_not_object",
        message_template="events[{index}] is not an object",
        path="tree.json",
    ):
        node_id = clean_string(event.get("node_id"))
        register_unique_id(
            event.get("event_id"),
            seen_event_ids,
            findings,
            missing_code="event_missing_id",
            missing_message="event missing event_id",
            duplicate_code="duplicate_event_id",
            duplicate_message_template="duplicate event_id: {value}",
            path="tree.json",
            node_id=node_id,
        )
        validate_known_node_ref(
            node_id,
            known_nodes,
            findings,
            code="event_missing_node",
            message="event references missing node",
            path="tree.json",
        )
        if "evidence" in event:
            findings.append(Finding("error", "legacy_event_evidence", "event uses legacy evidence; use evidence_refs", path="tree.json", node_id=node_id))
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="event_missing_evidence_ref",
            message_template="event references missing evidence_id {ref_id}",
            path="tree.json",
            node_id=node_id,
        )
    seen_backtrack_ids: set[str] = set()
    active_backtrack_ids: list[str] = []
    for index, event in iter_object_records(
        list_or_empty(tree.get("backtrack_events")),
        findings,
        code="backtrack_event_not_object",
        message_template="backtrack_events[{index}] is not an object",
        path="tree.json",
    ):
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        event_id = register_unique_id(
            event.get("id"),
            seen_backtrack_ids,
            findings,
            missing_code="backtrack_missing_id",
            missing_message="backtrack event missing id",
            duplicate_code="duplicate_backtrack_event_id",
            duplicate_message_template="duplicate backtrack event id: {value}",
            path="tree.json",
            node_id=from_node,
        )
        validate_known_node_ref(
            from_node,
            known_nodes,
            findings,
            code="backtrack_missing_from_node",
            message="backtrack from_node is missing",
            path="tree.json",
            allow_empty=False,
        )
        validate_known_node_ref(
            to_node,
            known_nodes,
            findings,
            code="backtrack_missing_to_node",
            message="backtrack to_node is missing",
            path="tree.json",
            allow_empty=False,
        )
        state = clean_string(event.get("event_state")) or "active"
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", path="tree.json", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id or f"backtrack_events[{index}]")
        if "evidence" in event:
            findings.append(Finding("error", "legacy_backtrack_evidence", "backtrack event uses legacy evidence; use evidence_refs", path="tree.json", node_id=from_node))
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="backtrack_missing_evidence_ref",
            message_template="backtrack references missing evidence_id {ref_id}",
            path="tree.json",
            node_id=from_node,
        )
    if len(active_backtrack_ids) > 1:
        findings.append(
            Finding(
                "error",
                "multiple_active_backtracks",
                f"tree.json has multiple active backtrack events: {', '.join(active_backtrack_ids)}",
                path="tree.json",
            )
        )


def validate_events(graph: dict[str, Any], node_ids: list[str], findings: list[Finding]) -> None:
    """Validate normalized graph events after normalizer processing."""

    known_nodes = set(node_ids)
    evidence_ids = evidence_ids_from_records(graph.get("evidence", {}))
    for event in list_or_empty(graph.get("events")):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("event_id"))
        node_id = clean_string(event.get("node_id"))
        if not event_id:
            findings.append(Finding("error", "event_missing_id", "event missing event_id"))
        validate_known_node_ref(
            node_id,
            known_nodes,
            findings,
            code="event_missing_node",
            message="event references missing node",
        )
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="event_missing_evidence_ref",
            message_template="event references missing evidence_id {ref_id}",
            node_id=node_id,
        )
    active_backtrack_ids: list[str] = []
    for index, event in enumerate(list_or_empty(graph.get("backtrack_events"))):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("id")) or f"backtrack_events[{index}]"
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        validate_known_node_ref(
            from_node,
            known_nodes,
            findings,
            code="backtrack_missing_from_node",
            message="backtrack from_node is missing",
            allow_empty=False,
        )
        validate_known_node_ref(
            to_node,
            known_nodes,
            findings,
            code="backtrack_missing_to_node",
            message="backtrack to_node is missing",
            allow_empty=False,
        )
        state = clean_string(event.get("event_state"))
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id)
        validate_evidence_refs(
            event,
            evidence_ids,
            findings,
            code="backtrack_missing_evidence_ref",
            message_template="backtrack references missing evidence_id {ref_id}",
            node_id=from_node,
        )
    if len(active_backtrack_ids) > 1:
        findings.append(
            Finding(
                "error",
                "multiple_active_backtracks",
                f"normalized graph has multiple active backtrack events: {', '.join(active_backtrack_ids)}",
            )
        )


__all__ = ["validate_tree_events", "validate_events"]
