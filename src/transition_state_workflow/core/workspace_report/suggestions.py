"""Report-context requirement builders for ChemKernel packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.base.backtrack_chain import replacement_chain_covers
from transition_state_workflow.util.path_utils import clean_string

from .ids import latest_node_id, node_sort_key
from .pathway import pathway_target_for_suggestions


def suggest_finalization_actions(
    *,
    source: Path,
    phase: str,
    tsfreq_nodes: list[tuple[str, dict[str, Any]]],
    connectivity_nodes: list[tuple[str, dict[str, Any]]],
    pathway_attention: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return non-branch actions when a claim may be ready to close."""

    if phase != "accepted_ts_ready":
        return []
    tsfreq_node = latest_node_id(tsfreq_nodes)
    connectivity_node = latest_node_id(connectivity_nodes)
    pathway_target = pathway_target_for_suggestions(pathway_attention)
    pathway_args = []
    if pathway_target:
        pathway_args = [
            "--pathway-id",
            clean_string(pathway_target.get("pathway_id")),
            "--step-id",
            clean_string(pathway_target.get("step_id")),
        ]
    return [
        {
            "kind": "accepted_ts_finalization_check",
            "target": "agent_selected_connectivity_or_validation_node",
            "requires": ["structured_tsfreq_evidence", "structured_connectivity_evidence"],
            "reason": "TS/Freq and connectivity claim layers both exist; agent must verify they refer to the same intended reaction before accepted_ts.",
            "pathway_scope": pathway_args,
            "candidate_source_nodes": {"tsfreq": tsfreq_node, "connectivity": connectivity_node},
        }
    ]


def suggest_reframe_actions(
    *,
    source: Path,
    reframe_candidates: list[dict[str, Any]],
    max_suggestions: int,
) -> list[dict[str, Any]]:
    """Return required checks for using failed TS/Freq evidence under a new reaction boundary."""

    actions: list[dict[str, Any]] = []
    if max_suggestions <= 0:
        return actions
    for candidate in reframe_candidates[:max_suggestions]:
        source_node = clean_string(candidate.get("node_id"))
        if not source_node:
            continue
        actions.append(
            {
                "kind": "reframe_validated_wrong_mode_tsfreq_check",
                "source_node": source_node,
                "requires": [
                    "new_or_validated_endpoint_refs_for_reframed_reaction",
                    "agent_owned_decision_card_with_input_ref_to_source_tsfreq_node",
                    "new_connectivity_evidence_attached_to_new_node",
                ],
                "reason": (
                    "The source node contains TS/Freq evidence but was rejected or ambiguous under its original "
                    "mechanism. It can seed a new mechanism-boundary test only as an input reference."
                ),
                "finalization_rule": (
                    "If the reframed branch succeeds, finalize the new node with both copied/recorded TS/Freq "
                    "evidence and new connectivity evidence; do not promote the old rejected node."
                ),
            }
        )
    return actions


def suggest_backtrack_actions(
    *,
    source: Path,
    failed_nodes: list[dict[str, Any]],
    backtrack_events: list[dict[str, Any]],
    node_payloads: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suggest canonical backtrack records for failed branches without one."""

    parent_by_node = {
        node_id: clean_string(node.get("parent_id"))
        for node_id, node in node_payloads.items()
    }
    suggestions: list[dict[str, Any]] = []
    for failed in failed_nodes:
        node_id = clean_string(failed.get("node_id"))
        if not node_id:
            continue
        parent = clean_string(parent_by_node.get(node_id))
        events_for_failed = [
            event
            for event in backtrack_events
            if clean_string(event.get("from_node")) == node_id
        ]
        replacement_nodes = replacement_branch_nodes_for_failed(node_id, node_payloads)
        unlinked_replacements = [
            replacement
            for replacement in replacement_nodes
            if not replacement_chain_covers(
                from_node=node_id,
                to_node=parent,
                replacement_node=replacement,
                backtrack_events=backtrack_events,
                parent_by_node=parent_by_node,
            )
        ]
        if events_for_failed and not unlinked_replacements:
            continue
        candidate_targets = candidate_backtrack_targets(node_id, node_payloads)
        recommended_to_node = clean_string(node_payloads.get(node_id, {}).get("parent_id"))
        recommended_new_branch_node = unlinked_replacements[-1] if unlinked_replacements else ""
        reason_code = clean_string(failed.get("outcome_code")) or clean_string(failed.get("outcome")) or "branch_failed"
        suggestions.append(
            {
                "kind": "backtrack_event_required",
                "from_node": node_id,
                "candidate_to_nodes": candidate_targets,
                "detected_replacement_branch_nodes": unlinked_replacements,
                "default_to_node_from_parent": recommended_to_node,
                "detected_new_branch_node": recommended_new_branch_node,
                "reason_code": reason_code,
                "reason": backtrack_reason_from_failed_summary(failed),
                "agent_must_choose": [
                    "closest chemically meaningful ancestor",
                    "whether the new branch reuses any failed-branch artifacts as input_refs",
                    "which changed variable makes the new branch chemically distinct",
                ],
            }
        )
    return suggestions


def replacement_branch_nodes_for_failed(node_id: str, node_payloads: dict[str, dict[str, Any]]) -> list[str]:
    """Return later sibling branches that look like replacements for a failed node."""

    parent_id = clean_string(node_payloads.get(node_id, {}).get("parent_id"))
    if not parent_id:
        return []
    failed_key = node_sort_key(node_id)
    replacements: list[str] = []
    for candidate_id, candidate in sorted(node_payloads.items(), key=lambda item: node_sort_key(item[0])):
        if candidate_id == node_id:
            continue
        if clean_string(candidate.get("parent_id")) != parent_id:
            continue
        if node_sort_key(candidate_id) <= failed_key:
            continue
        replacements.append(candidate_id)
    return replacements


def candidate_backtrack_targets(node_id: str, node_payloads: dict[str, dict[str, Any]]) -> list[str]:
    """Return parent-lineage candidates ordered from closest ancestor to root."""

    lineage = lineage_to_root(node_id, node_payloads)
    if lineage and lineage[-1] == node_id:
        lineage = lineage[:-1]
    return list(reversed(lineage))


def lineage_to_root(node_id: str, node_payloads: dict[str, dict[str, Any]]) -> list[str]:
    """Return node ids from root to node using parent_id links."""

    lineage: list[str] = []
    seen: set[str] = set()
    current = clean_string(node_id)
    while current and current not in seen:
        seen.add(current)
        lineage.append(current)
        current = clean_string(node_payloads.get(current, {}).get("parent_id"))
    return list(reversed(lineage))


def backtrack_reason_from_failed_summary(failed: dict[str, Any]) -> str:
    """Build a short backtrack reason from a failed branch summary."""

    reflection = failed.get("reflection") if isinstance(failed.get("reflection"), dict) else {}
    next_branch = clean_string(reflection.get("next_branch"))
    if next_branch:
        return next_branch
    summary = clean_string(failed.get("summary"))
    if summary:
        return summary
    return "Failed or ambiguous branch should return to an earlier chemistry decision before opening a new branch."


__all__ = [
    "suggest_finalization_actions",
    "suggest_reframe_actions",
    "suggest_backtrack_actions",
    "replacement_branch_nodes_for_failed",
    "candidate_backtrack_targets",
    "lineage_to_root",
    "backtrack_reason_from_failed_summary",
]
