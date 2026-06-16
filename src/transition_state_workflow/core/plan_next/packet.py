"""Packet orchestration for ChemKernel next-action planning."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .context import build_context_items, summarize_evidence
from .contracts import PLAN_SCHEMA, TsfreqEvidencePredicate, WorkspaceValidator
from .ids import node_sort_key
from .loader import conservative_workspace_validation, no_tsfreq_evidence_support
from .pathway import filter_nodes_for_pathway_step, infer_pathway_plan
from .phase import gates_for_phase, infer_phase_from_focus_node, infer_planning_focus, infer_planning_state
from .snapshot import classify_node_claims, load_plan_next_snapshot
from .suggestions import (
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

    validate_workspace = validate_workspace or conservative_workspace_validation
    supports_tsfreq_evidence = supports_tsfreq_evidence or no_tsfreq_evidence_support
    snapshot = load_plan_next_snapshot(
        root,
        validate_workspace=validate_workspace,
        supports_tsfreq_evidence=supports_tsfreq_evidence,
    )

    source = snapshot.source
    manifest = snapshot.manifest
    mechanism = snapshot.mechanism
    pathway_summary = snapshot.pathway_summary
    node_payloads = snapshot.node_payloads
    validation = snapshot.validation
    validation_errors = snapshot.validation_errors
    active_nodes = snapshot.active_nodes
    failed_nodes = snapshot.failed_nodes
    backtrack_events = snapshot.backtrack_events
    reframe_candidates = snapshot.reframe_candidates
    endpoint_evidence_blockers = snapshot.endpoint_evidence_blockers

    endpoint_nodes = snapshot.claims.endpoint_nodes
    candidate_nodes = snapshot.claims.candidate_nodes
    tsfreq_nodes = snapshot.claims.tsfreq_nodes
    connectivity_nodes = snapshot.claims.connectivity_nodes
    accepted_nodes = snapshot.claims.accepted_nodes

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
    planning_claims = snapshot.claims
    if pathway_plan.get("mode") in {"start", "continue"}:
        next_step = pathway_plan.get("next_step") if isinstance(pathway_plan.get("next_step"), dict) else {}
        planning_node_payloads = filter_nodes_for_pathway_step(
            node_payloads,
            pathway_id=clean_string(next_step.get("pathway_id")),
            step_id=clean_string(next_step.get("step_id")),
        )
        planning_claims = classify_node_claims(planning_node_payloads)
        blocking_gates, allowed, forbidden, phase = infer_planning_state(
            validation_errors=validation_errors,
            active_nodes=active_nodes,
            endpoint_nodes=planning_claims.endpoint_nodes,
            candidate_nodes=planning_claims.candidate_nodes,
            tsfreq_nodes=planning_claims.tsfreq_nodes,
            connectivity_nodes=planning_claims.connectivity_nodes,
            accepted_nodes=planning_claims.accepted_nodes,
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
    endpoint_blockers_gate_scientific_planning = bool(endpoint_evidence_blockers) and not (
        validation_errors
        or active_nodes
        or (accepted_nodes and not alternative_mechanism and pathway_plan.get("mode") not in {"start", "continue"})
    )
    if endpoint_blockers_gate_scientific_planning:
        _append_unique(blocking_gates, "endpoint_evidence_not_validated")
        _append_unique(allowed, "record_backtrack_to_endpoint_or_connectivity_ancestor")
        _append_unique(allowed, "replan_endpoint_or_connectivity_evidence_with_changed_variable")
        _append_unique(forbidden, "endpoint_promotion_from_error_terminated_log")
        _append_unique(forbidden, "repeat_unchanged_endpoint_restart")
        _append_unique(forbidden, "neb_qst_from_failed_endpoint_evidence")
        _append_unique(forbidden, "accepted_ts_from_failed_endpoint_evidence")
        if planning_focus["mode"] == "advance":
            latest_blocker = endpoint_evidence_blockers[-1]
            planning_focus = {
                "mode": "endpoint_evidence_replan",
                "focus_node": clean_string(latest_blocker.get("node_id")),
                "parent_for_new_branch": None,
                "reason": (
                    "Parsed endpoint evidence is not validated; choose a chemically meaningful "
                    "ancestor and changed endpoint/connectivity hypothesis before opening the next branch."
                ),
            }

    suggestions = suggest_decision_cards(
        source=source,
        phase=phase,
        endpoint_nodes=planning_claims.endpoint_nodes,
        candidate_nodes=planning_claims.candidate_nodes,
        tsfreq_nodes=planning_claims.tsfreq_nodes,
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
        "prepared_nodes": snapshot.claims.prepared_nodes[:8],
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
            "ranking_keys": [
                "priority",
                "planning_focus",
                "endpoint_evidence_blocker",
                "failed_branch_lesson",
                "accepted_node",
                "mechanism_memory",
            ],
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
            endpoint_evidence_blockers=endpoint_evidence_blockers,
        ),
        "blocking_gates": blocking_gates,
        "allowed_next_actions": allowed,
        "forbidden_next_actions": forbidden,
        "validated_facts": list_or_empty(mechanism.get("validated_facts"))[:12],
        "refuted_hypotheses": list_or_empty(mechanism.get("refuted_hypotheses"))[:12],
        "open_questions": list_or_empty(mechanism.get("open_questions"))[:12],
        "evidence_summary": summarize_evidence(snapshot.evidence),
        "endpoint_evidence_blockers": endpoint_evidence_blockers[:8],
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
            tsfreq_nodes=planning_claims.tsfreq_nodes,
            connectivity_nodes=planning_claims.connectivity_nodes,
            pathway_plan=pathway_plan,
        ),
    }


__all__ = ["build_plan_next_packet"]


def _append_unique(values: list[str], item: str) -> None:
    if item not in values:
        values.append(item)
