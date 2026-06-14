"""ChemKernel next-action planning packets.

This package keeps the historical ``transition_state_workflow.core.plan_next``
import surface while splitting the planner into small core-only modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.base.pathway_model import read_pathway_model_optional, summarize_pathway_model
from transition_state_workflow.util.json_io import read_json_object_optional, read_json_object_required
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .cli import register_plan_next_parser
from .context import (
    backtrack_event_summaries,
    build_context_items,
    evidence_records_from_registry,
    failed_branch_context_item,
    failed_or_ambiguous_node_summaries,
    failed_summary_by_id,
    first_section_line,
    jsonish_compact,
    node_context_item,
    rank_context_items,
    read_reflection_brief,
    reframe_candidate_summaries,
    summarize_evidence,
    summarize_node,
    summarize_reframe_tsfreq_record,
)
from .contracts import PLAN_SCHEMA, TsfreqEvidencePredicate, WorkspaceValidator
from .ids import latest_node_id, next_suggested_node_id, node_number, node_sort_key
from .loader import (
    active_node_summaries,
    conservative_workspace_validation,
    ensure_plan_workspace,
    load_node_payloads,
    no_tsfreq_evidence_support,
    nodes_with_claim,
)
from .pathway import (
    filter_nodes_for_pathway_step,
    infer_pathway_plan,
    latest_pathway_status_node,
    pathway_target_for_suggestions,
)
from .phase import (
    default_focus_node_for_phase,
    gates_for_phase,
    infer_phase_from_focus_node,
    infer_planning_focus,
    infer_planning_state,
)
from .suggestions import (
    backtrack_reason_from_failed_summary,
    candidate_backtrack_targets,
    decision_card_suggestion,
    lineage_to_root,
    suggest_backtrack_actions,
    suggest_decision_cards,
    suggest_finalization_actions,
    suggest_reframe_actions,
)


def build_plan_next_packet(
    root: Path,
    *,
    max_suggestions: int = 4,
    alternative_mechanism: bool = False,
    validate_workspace: WorkspaceValidator | None = None,
    supports_tsfreq_evidence: TsfreqEvidencePredicate | None = None,
) -> dict[str, Any]:
    """Return a compact planning context for the next agent decision."""

    source = root.expanduser().resolve()
    validate_workspace = validate_workspace or conservative_workspace_validation
    supports_tsfreq_evidence = supports_tsfreq_evidence or no_tsfreq_evidence_support
    ensure_plan_workspace(source)
    manifest = read_json_object_required(source / "manifest.json")
    tree = read_json_object_required(source / "tree.json")
    evidence = read_json_object_optional(source / "evidence_registry.json")
    mechanism = read_json_object_optional(source / "mechanism_model.json")
    pathway = read_pathway_model_optional(source)
    pathway_summary = summarize_pathway_model(pathway)
    node_payloads = load_node_payloads(source, tree)
    validation = dict(validate_workspace(source))

    active_nodes = active_node_summaries(tree, node_payloads)
    prepared_nodes = [
        summarize_node(node_id, node)
        for node_id, node in sorted(node_payloads.items(), key=lambda item: node_sort_key(item[0]))
        if clean_string(node.get("lifecycle_state")) == "prepared"
    ]
    endpoint_nodes = nodes_with_claim(node_payloads, "endpoint_minima_ready")
    candidate_nodes = nodes_with_claim(node_payloads, "candidate_found")
    tsfreq_nodes = nodes_with_claim(node_payloads, "tsfreq_validated")
    connectivity_nodes = [
        (node_id, node)
        for node_id, node in node_payloads.items()
        if clean_string(node.get("claim_status")) in {"endpoint_connected", "irc_connected"}
    ]
    accepted_nodes = nodes_with_claim(node_payloads, "accepted_ts")
    failed_nodes = failed_or_ambiguous_node_summaries(source, node_payloads)
    backtrack_events = backtrack_event_summaries(tree)
    evidence_records = evidence_records_from_registry(evidence)
    reframe_candidates = reframe_candidate_summaries(
        source=source,
        node_payloads=node_payloads,
        evidence_records=evidence_records,
        supports_tsfreq_evidence=supports_tsfreq_evidence,
    )

    validation_errors = [
        item for item in list_or_empty(validation.get("findings")) if clean_string(item.get("severity")) == "error"
    ]
    blocking_gates, allowed, forbidden, phase = infer_planning_state(
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        endpoint_nodes=endpoint_nodes,
        candidate_nodes=candidate_nodes,
        tsfreq_nodes=tsfreq_nodes,
        connectivity_nodes=connectivity_nodes,
        accepted_nodes=accepted_nodes,
        manifest=manifest,
        alternative_mechanism=alternative_mechanism,
    )
    global_phase = phase
    pathway_plan = infer_pathway_plan(
        pathway_summary=pathway_summary,
        accepted_nodes=accepted_nodes,
        manifest=manifest,
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        alternative_mechanism=alternative_mechanism,
    )
    planning_node_payloads = node_payloads
    planning_endpoint_nodes = endpoint_nodes
    planning_candidate_nodes = candidate_nodes
    planning_tsfreq_nodes = tsfreq_nodes
    planning_connectivity_nodes = connectivity_nodes
    planning_accepted_nodes = accepted_nodes
    if pathway_plan.get("mode") in {"start", "continue"}:
        next_step = pathway_plan.get("next_step") if isinstance(pathway_plan.get("next_step"), dict) else {}
        planning_node_payloads = filter_nodes_for_pathway_step(
            node_payloads,
            pathway_id=clean_string(next_step.get("pathway_id")),
            step_id=clean_string(next_step.get("step_id")),
        )
        planning_endpoint_nodes = nodes_with_claim(planning_node_payloads, "endpoint_minima_ready")
        planning_candidate_nodes = nodes_with_claim(planning_node_payloads, "candidate_found")
        planning_tsfreq_nodes = nodes_with_claim(planning_node_payloads, "tsfreq_validated")
        planning_connectivity_nodes = [
            (node_id, node)
            for node_id, node in planning_node_payloads.items()
            if clean_string(node.get("claim_status")) in {"endpoint_connected", "irc_connected"}
        ]
        planning_accepted_nodes = nodes_with_claim(planning_node_payloads, "accepted_ts")
        blocking_gates, allowed, forbidden, phase = infer_planning_state(
            validation_errors=validation_errors,
            active_nodes=active_nodes,
            endpoint_nodes=planning_endpoint_nodes,
            candidate_nodes=planning_candidate_nodes,
            tsfreq_nodes=planning_tsfreq_nodes,
            connectivity_nodes=planning_connectivity_nodes,
            accepted_nodes=planning_accepted_nodes,
            manifest={},
            alternative_mechanism=False,
        )
        if pathway_plan.get("mode") == "continue" and "continue_to_next_elementary_step" not in allowed:
            allowed.append("continue_to_next_elementary_step")
        if "archive_overall_pathway_with_incomplete_steps" not in forbidden:
            forbidden.append("archive_overall_pathway_with_incomplete_steps")
        if "reuse_previous_step_connectivity_for_next_step" not in forbidden:
            forbidden.append("reuse_previous_step_connectivity_for_next_step")
    elif pathway_plan.get("mode") == "complete":
        blocking_gates = []
        allowed = ["audit_pathway_evidence", "archive_search", "branch_alternative_pathway_if_requested"]
        forbidden = ["promote_additional_step_without_pathway_update"]
        phase = "pathway_complete"
    elif pathway_plan.get("mode") in {"ambiguous", "rejected"}:
        mode = clean_string(pathway_plan.get("mode"))
        blocking_gates = [f"pathway_{mode}_requires_mechanism_reassessment"]
        allowed = [
            "inspect_pathway_step_reflection",
            "record_backtrack_to_mechanism_hypothesis",
            "open_alternative_pathway_if_chemically_justified",
        ]
        forbidden = [
            "continue_rejected_or_ambiguous_pathway_without_changed_hypothesis",
            "reuse_refuted_step_as_proof",
        ]
        phase = f"pathway_{mode}"
    suggested_backtrack_actions = suggest_backtrack_actions(
        source=source,
        failed_nodes=failed_nodes,
        backtrack_events=backtrack_events,
        node_payloads=node_payloads,
    )
    planning_focus = infer_planning_focus(
        phase=phase,
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        accepted_nodes=accepted_nodes,
        failed_nodes=failed_nodes,
        backtrack_events=backtrack_events,
        suggested_backtrack_actions=suggested_backtrack_actions,
        node_payloads=node_payloads,
        manifest=manifest,
        alternative_mechanism=alternative_mechanism,
        pathway_plan=pathway_plan,
        pathway_step_node_payloads=planning_node_payloads,
    )
    parent_override = None
    if planning_focus["mode"] == "backtrack_replan":
        focus_phase = infer_phase_from_focus_node(
            clean_string(planning_focus.get("focus_node")),
            node_payloads,
        )
        if focus_phase:
            blocking_gates, allowed, forbidden, phase = gates_for_phase(focus_phase)
        parent_override = clean_string(planning_focus.get("parent_for_new_branch")) or None
    elif planning_focus["mode"] == "pathway_step_planning":
        parent_override = clean_string(planning_focus.get("parent_for_new_branch")) or None
    elif planning_focus["mode"] == "backtrack_decision_needed":
        blocking_gates = ["backtrack_target_missing"]
        allowed = ["record_backtrack_to_chemically_meaningful_ancestor", "inspect_failed_branch_reflection"]
        forbidden = ["new_child_under_failed_node_without_backtrack", "continue_failed_branch_without_changed_hypothesis"]
        phase = "backtrack_decision_needed"
    if reframe_candidates and not validation_errors and not active_nodes and not (accepted_nodes and not alternative_mechanism):
        if "reframe_validated_wrong_mode_tsfreq_with_new_endpoint_refs" not in allowed:
            allowed.append("reframe_validated_wrong_mode_tsfreq_with_new_endpoint_refs")
        if "promote_rejected_tsfreq_without_new_connectivity_boundary" not in forbidden:
            forbidden.append("promote_rejected_tsfreq_without_new_connectivity_boundary")
    suggestions = suggest_decision_cards(
        source=source,
        phase=phase,
        endpoint_nodes=planning_endpoint_nodes,
        candidate_nodes=planning_candidate_nodes,
        tsfreq_nodes=planning_tsfreq_nodes,
        parent_override=parent_override,
        pathway_plan=pathway_plan,
        max_suggestions=max_suggestions,
    )
    if validation_errors or active_nodes or (
        accepted_nodes and not alternative_mechanism and pathway_plan.get("mode") not in {"start", "continue"}
    ):
        suggestions = []
    if pathway_plan.get("mode") in {"ambiguous", "rejected"}:
        suggestions = []
    if planning_focus["mode"] == "backtrack_decision_needed":
        suggestions = []

    return {
        "schema": PLAN_SCHEMA,
        "source": str(source),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_decision_required": True,
        "planner_role": "Summarize state and gate constraints; the agent must choose the chemical hypothesis and tool.",
        "workspace": {
            "system": clean_string(manifest.get("system")),
            "charge": manifest.get("charge"),
            "multiplicity": manifest.get("multiplicity"),
            "current_accepted_ts": clean_string(manifest.get("current_accepted_ts")),
        },
        "pathway": pathway_summary,
        "validation_summary": validation.get("summary", {}),
        "validation_errors": validation_errors[:8],
        "current_frontier": active_nodes,
        "prepared_nodes": prepared_nodes[:8],
        "search_state": {
            "phase": phase,
            "global_phase": global_phase,
            "endpoint_minima_ready_nodes": [node_id for node_id, _ in sorted(endpoint_nodes, key=lambda item: node_sort_key(item[0]))],
            "candidate_nodes": [node_id for node_id, _ in sorted(candidate_nodes, key=lambda item: node_sort_key(item[0]))],
            "tsfreq_validated_nodes": [node_id for node_id, _ in sorted(tsfreq_nodes, key=lambda item: node_sort_key(item[0]))],
            "connectivity_nodes": [node_id for node_id, _ in sorted(connectivity_nodes, key=lambda item: node_sort_key(item[0]))],
            "accepted_nodes": [node_id for node_id, _ in sorted(accepted_nodes, key=lambda item: node_sort_key(item[0]))],
            "current_pathway_step_nodes": [node_id for node_id in sorted(planning_node_payloads, key=node_sort_key)]
            if pathway_plan.get("mode") in {"start", "continue"}
            else [],
            "pathway_phase": clean_string(pathway_plan.get("mode")) or "none",
        },
        "planning_focus": planning_focus,
        "context_policy": {
            "mode": "alternative_mechanism_context" if alternative_mechanism else "structured_priority_context",
            "retrieval_mode": "ranked_workspace_artifacts",
            "ranking_keys": ["priority", "planning_focus", "failed_branch_lesson", "accepted_node", "mechanism_memory"],
            "raw_excerpt_policy": "include parsed summaries and reflections first; read raw logs only when a blocking gate requires exact error text",
            "parent_rule": "new decision cards follow planning_focus.parent_for_new_branch when backtracking is active",
            "reframe_rule": "rejected or wrong-mode TS/Freq nodes stay historical; reuse them only through input_refs on a new node with a new intended reaction boundary",
            "pathway_rule": "accepted_ts remains an elementary-step claim; pathway completion is derived only when every required pathway step is bound to an accepted_ts node",
        },
        "context_items": build_context_items(
            source=source,
            phase=phase,
            planning_focus=planning_focus,
            node_payloads=node_payloads,
            failed_nodes=failed_nodes,
            reframe_candidates=reframe_candidates,
            pathway_summary=pathway_summary,
            mechanism=mechanism,
            validation_summary=validation.get("summary", {}),
            backtrack_events=backtrack_events,
            accepted_nodes=accepted_nodes,
            active_nodes=active_nodes,
        ),
        "blocking_gates": blocking_gates,
        "allowed_next_actions": allowed,
        "forbidden_next_actions": forbidden,
        "validated_facts": list_or_empty(mechanism.get("validated_facts"))[:12],
        "refuted_hypotheses": list_or_empty(mechanism.get("refuted_hypotheses"))[:12],
        "open_questions": list_or_empty(mechanism.get("open_questions"))[:12],
        "evidence_summary": summarize_evidence(evidence),
        "reframe_candidates": reframe_candidates[:8],
        "backtrack_events": backtrack_events[:8],
        "failed_or_ambiguous_branches": failed_nodes[:8],
        "suggested_backtrack_actions": suggested_backtrack_actions[:8],
        "suggested_reframe_actions": suggest_reframe_actions(
            source=source,
            reframe_candidates=reframe_candidates,
            max_suggestions=max_suggestions,
        ),
        "suggested_decision_cards": suggestions,
        "suggested_finalization_actions": suggest_finalization_actions(
            source=source,
            phase=phase,
            tsfreq_nodes=planning_tsfreq_nodes,
            connectivity_nodes=planning_connectivity_nodes,
            pathway_plan=pathway_plan,
        ),
    }


__all__ = [
    "PLAN_SCHEMA",
    "WorkspaceValidator",
    "TsfreqEvidencePredicate",
    "register_plan_next_parser",
    "build_plan_next_packet",
    "ensure_plan_workspace",
    "conservative_workspace_validation",
    "no_tsfreq_evidence_support",
    "load_node_payloads",
    "active_node_summaries",
    "nodes_with_claim",
    "infer_pathway_plan",
    "filter_nodes_for_pathway_step",
    "infer_planning_state",
    "gates_for_phase",
    "infer_phase_from_focus_node",
    "infer_planning_focus",
    "default_focus_node_for_phase",
    "latest_pathway_status_node",
    "suggest_decision_cards",
    "pathway_target_for_suggestions",
    "decision_card_suggestion",
    "suggest_finalization_actions",
    "suggest_reframe_actions",
    "summarize_node",
    "failed_or_ambiguous_node_summaries",
    "evidence_records_from_registry",
    "reframe_candidate_summaries",
    "summarize_reframe_tsfreq_record",
    "backtrack_event_summaries",
    "suggest_backtrack_actions",
    "candidate_backtrack_targets",
    "lineage_to_root",
    "backtrack_reason_from_failed_summary",
    "build_context_items",
    "rank_context_items",
    "node_context_item",
    "failed_branch_context_item",
    "failed_summary_by_id",
    "jsonish_compact",
    "read_reflection_brief",
    "first_section_line",
    "summarize_evidence",
    "latest_node_id",
    "next_suggested_node_id",
    "node_sort_key",
    "node_number",
]
