"""Timeline and backtrack event checks for ChemGate workspace validation."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.config.state_contract import VALID_BACKTRACK_EVENT_STATES
from transition_state_workflow.config.state_contract import derive_node_audit_view
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .common import (
    evidence_ids_from_records,
    iter_object_records,
    register_unique_id,
    validate_evidence_refs,
    validate_known_node_ref,
)
from .contracts import Finding

FAILED_BRANCH_OUTCOMES = {
    "chemical_failure",
    "numerical_failure",
    "wrong_mode",
    "wrong_endpoint",
    "parser_refused",
}


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


def validate_backtrack_replacement_links(
    node_json_by_id: dict[str, dict[str, Any]],
    parent_by_node: dict[str, str],
    backtrack_events: list[Any],
    findings: list[Finding],
) -> None:
    """Warn when a failed branch has an apparent replacement sibling but no backtrack link."""

    normalized_events = [event for event in backtrack_events if isinstance(event, dict)]
    linked_replacements = {
        (
            clean_string(event.get("from_node")),
            clean_string(event.get("to_node")),
            clean_string(event.get("new_branch_node")),
        )
        for event in normalized_events
    }
    for failed_node, node_json in sorted(node_json_by_id.items(), key=lambda item: _node_sort_key(item[0])):
        if not _is_failed_or_ambiguous_branch(node_json):
            continue
        parent = clean_string(parent_by_node.get(failed_node))
        if not parent:
            continue
        replacements = _replacement_siblings(failed_node, parent, parent_by_node)
        for replacement in replacements:
            if (failed_node, parent, replacement) in linked_replacements:
                continue
            findings.append(
                Finding(
                    "warning",
                    "missing_replacement_backtrack_event",
                    (
                        f"replacement branch {replacement} shares parent {parent} with failed branch {failed_node}; "
                        f"record a canonical backtrack event with --from-node {failed_node} --to-node {parent} "
                        f"--new-branch-node {replacement}"
                    ),
                    path="tree.json",
                    node_id=failed_node,
                )
            )


def _is_failed_or_ambiguous_branch(node_json: dict[str, Any]) -> bool:
    audit = derive_node_audit_view(node_json)
    claim = clean_string(audit.get("claim_status"))
    outcome = clean_string(audit.get("outcome"))
    return claim in {"rejected", "ambiguous"} or outcome in FAILED_BRANCH_OUTCOMES


def _replacement_siblings(
    failed_node: str,
    parent: str,
    parent_by_node: dict[str, str],
) -> list[str]:
    failed_key = _node_sort_key(failed_node)
    replacements: list[str] = []
    for node_id, node_parent in sorted(parent_by_node.items(), key=lambda item: _node_sort_key(item[0])):
        if node_id == failed_node:
            continue
        if clean_string(node_parent) != parent:
            continue
        if _node_sort_key(node_id) <= failed_key:
            continue
        replacements.append(node_id)
    return replacements


def _node_sort_key(node_id: str) -> tuple[int, str]:
    text = clean_string(node_id)
    if len(text) >= 4 and text.startswith("n") and text[1:4].isdigit():
        return (int(text[1:4]), text)
    return (999999, text)


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


__all__ = ["validate_tree_events", "validate_backtrack_replacement_links", "validate_events"]
