"""Generate agent-facing planning packets from a TS-search workspace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.tool.evidence_gates import (
    TSFREQ_KINDS,
    load_record_payload,
    normalized_token,
    supports_tsfreq_gate,
)
from transition_state_workflow.tool.pathway_model import read_pathway_model_optional, summarize_pathway_model
from transition_state_workflow.tool.validate_workspace import validate_ts_workspace_contract
from transition_state_workflow.util.json_io import read_json_object_optional, read_json_object_required
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, safe_identifier_token


PLAN_SCHEMA = "ts-next-action-plan-v1"


def register_plan_next_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the plan-next subcommand to the workspace CLI."""

    plan = subparsers.add_parser(
        "plan-next",
        help="Summarize tree/evidence state into an agent-facing next-action packet.",
    )
    plan.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    plan.add_argument("--max-suggestions", type=int, default=4, help="Maximum decision-card suggestions.")
    plan.add_argument(
        "--write-decision-cards",
        action="store_true",
        help="Materialize suggested decision-card nodes. Default is read-only.",
    )
    plan.add_argument("--force", action="store_true", help="Overwrite existing suggested node templates.")
    plan.add_argument(
        "--alternative-mechanism",
        action="store_true",
        help="After an accepted TS exists, plan a chemically distinct alternative mechanism instead of audit-only mode.",
    )
    plan.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    plan.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    plan.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")


def build_plan_next_packet(
    root: Path,
    *,
    max_suggestions: int = 4,
    alternative_mechanism: bool = False,
) -> dict[str, Any]:
    """Return a compact planning context for the next agent decision."""

    source = root.expanduser().resolve()
    ensure_plan_workspace(source)
    manifest = read_json_object_required(source / "manifest.json")
    tree = read_json_object_required(source / "tree.json")
    evidence = read_json_object_optional(source / "evidence_registry.json")
    mechanism = read_json_object_optional(source / "mechanism_model.json")
    pathway = read_pathway_model_optional(source)
    pathway_summary = summarize_pathway_model(pathway)
    node_payloads = load_node_payloads(source, tree)
    validation = validate_ts_workspace_contract(source)

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


def ensure_plan_workspace(root: Path) -> None:
    """Fail early when the root cannot be planned from."""

    missing = [name for name in ("manifest.json", "tree.json", "nodes") if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")


def load_node_payloads(root: Path, tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Load node.json payloads for all tree or directory nodes."""

    tree_nodes = tree.get("nodes") if isinstance(tree.get("nodes"), dict) else {}
    node_ids = {str(key) for key in tree_nodes}
    nodes_dir = root / "nodes"
    if nodes_dir.exists():
        node_ids.update(path.name for path in nodes_dir.iterdir() if path.is_dir())
    payloads: dict[str, dict[str, Any]] = {}
    for node_id in sorted(node_ids, key=node_sort_key):
        node_path = root / "nodes" / node_id / "node.json"
        if node_path.exists():
            try:
                payloads[node_id] = read_json_object_required(node_path)
            except ValueError:
                payloads[node_id] = {}
        else:
            payloads[node_id] = {}
    return payloads


def active_node_summaries(tree: dict[str, Any], node_payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return nodes that are currently active according to tree indexes or node state."""

    active_ids = {clean_string(item) for item in list_or_empty(tree.get("active_frontier")) if clean_string(item)}
    for node_id, node in node_payloads.items():
        if clean_string(node.get("lifecycle_state")) == "active" or clean_string(node.get("run_state")) in {
            "pending",
            "running",
            "parsing",
        }:
            active_ids.add(node_id)
    return [summarize_node(node_id, node_payloads.get(node_id, {})) for node_id in sorted(active_ids, key=node_sort_key)]


def nodes_with_claim(node_payloads: dict[str, dict[str, Any]], claim_status: str) -> list[tuple[str, dict[str, Any]]]:
    """Return nodes whose current claim matches claim_status."""

    return [
        (node_id, node)
        for node_id, node in node_payloads.items()
        if clean_string(node.get("claim_status")) == claim_status
    ]


def infer_pathway_plan(
    *,
    pathway_summary: dict[str, Any],
    accepted_nodes: list[tuple[str, dict[str, Any]]],
    manifest: dict[str, Any],
    validation_errors: list[dict[str, Any]],
    active_nodes: list[dict[str, Any]],
    alternative_mechanism: bool,
) -> dict[str, Any]:
    """Return pathway planning mode without changing node-level TS logic."""

    if validation_errors or active_nodes or alternative_mechanism:
        return {"mode": "none"}
    if not bool(pathway_summary.get("present")):
        return {"mode": "none"}
    if clean_string(pathway_summary.get("mode")) != "multi_step":
        return {"mode": "none"}
    active = pathway_summary.get("active_pathway") if isinstance(pathway_summary.get("active_pathway"), dict) else {}
    if not active:
        return {"mode": "none"}
    status = clean_string(active.get("status"))
    if status == "complete":
        return {"mode": "complete", "pathway": active}
    if status in {"ambiguous", "rejected"}:
        return {"mode": status, "pathway": active}
    next_step = pathway_summary.get("next_incomplete_step")
    if not isinstance(next_step, dict) or not clean_string(next_step.get("step_id")):
        return {"mode": "complete", "pathway": active}
    steps = [step for step in list_or_empty(active.get("steps")) if isinstance(step, dict)]
    accepted_step_count = sum(
        1
        for step in steps
        if clean_string(step.get("status")) == "accepted_ts" and clean_string(step.get("accepted_ts_node"))
    )
    if accepted_step_count:
        return {"mode": "continue", "pathway": active, "next_step": next_step}
    return {"mode": "start", "pathway": active, "next_step": next_step}


def filter_nodes_for_pathway_step(
    node_payloads: dict[str, dict[str, Any]],
    *,
    pathway_id: str,
    step_id: str,
) -> dict[str, dict[str, Any]]:
    """Return nodes explicitly assigned to one pathway step."""

    if not pathway_id or not step_id:
        return {}
    return {
        node_id: node
        for node_id, node in node_payloads.items()
        if clean_string(node.get("pathway_id")) == pathway_id
        and clean_string(node.get("elementary_step_id")) == step_id
    }


def infer_planning_state(
    *,
    validation_errors: list[dict[str, Any]],
    active_nodes: list[dict[str, Any]],
    endpoint_nodes: list[tuple[str, dict[str, Any]]],
    candidate_nodes: list[tuple[str, dict[str, Any]]],
    tsfreq_nodes: list[tuple[str, dict[str, Any]]],
    connectivity_nodes: list[tuple[str, dict[str, Any]]],
    accepted_nodes: list[tuple[str, dict[str, Any]]],
    manifest: dict[str, Any],
    alternative_mechanism: bool,
) -> tuple[list[str], list[str], list[str], str]:
    """Infer state-machine blockers and allowed action classes."""

    blocking: list[str] = []
    allowed: list[str] = []
    forbidden: list[str] = []

    if validation_errors:
        return (
            ["workspace_validation_errors"],
            ["repair_workspace_contract", "rerun_ts_validate_workspace"],
            ["any_claim_promotion_until_workspace_validates"],
            "workspace_repair_required",
        )
    if active_nodes:
        return (
            ["active_nodes_pending"],
            ["wait_for_active_nodes", "parse_active_outputs", "administrative_stop_if_needed"],
            ["accepted_ts", "candidate_or_validation_promotion_without_parsed_outputs"],
            "active_work_running",
        )
    if accepted_nodes or clean_string(manifest.get("current_accepted_ts")):
        if alternative_mechanism:
            return (
                ["accepted_ts_present_requires_distinct_mechanism"],
                ["mechanism_preflight_alternative", "endpoint_discovery_for_alternative", "branch_alternative_mechanism"],
                ["overwrite_accepted_branch_without_new_evidence", "reuse_accepted_ts_as_alternative_proof"],
                "alternative_mechanism_planning",
            )
        return (
            [],
            ["audit_accepted_ts_evidence", "archive_search", "branch_alternative_mechanism_if_requested"],
            ["overwrite_accepted_branch_without_new_evidence"],
            "accepted_ts_present",
        )
    if not endpoint_nodes:
        blocking.append("endpoint_minima_missing")
        allowed.extend(
            [
                "xtb_endpoint_preopt",
                "gaussian_endpoint_validation",
                "constrained_endpoint_reference",
                "pose_search",
                "fragment_identity_check",
            ]
        )
        forbidden.extend(
            [
                "candidate_found_promotion",
                "xtb_neb_from_reference_hypothesis",
                "gaussian_neb_from_reference_hypothesis",
                "qst_from_unvalidated_endpoints",
                "accepted_ts",
            ]
        )
        return blocking, allowed, forbidden, "endpoint_discovery"
    if not candidate_nodes and not tsfreq_nodes:
        blocking.append("candidate_missing")
        allowed.extend(
            [
                "xtb_neb_candidate_generation",
                "xtb_relaxed_scan",
                "xtb_dimer_screen",
                "gaussian_neb_refinement",
                "qst2_qst3_guess",
                "qbics_dmecp_candidate_generation",
            ]
        )
        forbidden.extend(["accepted_ts", "tsfreq_validation_without_candidate"])
        return blocking, allowed, forbidden, "candidate_generation"
    if not tsfreq_nodes:
        blocking.append("tsfreq_validation_missing")
        allowed.extend(["gaussian_tsfreq_validation", "gaussian_input_preflight", "candidate_quality_review"])
        forbidden.extend(["accepted_ts", "connectivity_claim_without_tsfreq"])
        return blocking, allowed, forbidden, "gaussian_tsfreq_validation"
    if not connectivity_nodes:
        blocking.append("connectivity_missing")
        allowed.extend(["imaginary_mode_endpoint_follow", "endpoint_connectivity_check", "irc_connectivity_check"])
        forbidden.extend(["accepted_ts_without_connectivity", "visual_only_connectivity_claim"])
        return blocking, allowed, forbidden, "connectivity_validation"
    return (
        [],
        ["finalize_accepted_ts_if_structured_evidence_passes", "audit_frequency_and_connectivity_payloads"],
        ["accepted_ts_without_structured_tsfreq_and_connectivity_evidence"],
        "accepted_ts_ready",
    )


def gates_for_phase(phase: str) -> tuple[list[str], list[str], list[str], str]:
    """Return planning gates for a focus-local phase."""

    if phase == "endpoint_discovery":
        return (
            ["endpoint_minima_missing"],
            [
                "xtb_endpoint_preopt",
                "gaussian_endpoint_validation",
                "constrained_endpoint_reference",
                "pose_search",
                "fragment_identity_check",
            ],
            [
                "candidate_found_promotion",
                "xtb_neb_from_reference_hypothesis",
                "gaussian_neb_from_reference_hypothesis",
                "qst_from_unvalidated_endpoints",
                "accepted_ts",
            ],
            phase,
        )
    if phase == "candidate_generation":
        return (
            ["candidate_missing_after_backtrack_target"],
            [
                "xtb_neb_candidate_generation",
                "xtb_relaxed_scan",
                "xtb_dimer_screen",
                "gaussian_neb_refinement",
                "qst2_qst3_guess",
                "qbics_dmecp_candidate_generation",
            ],
            ["accepted_ts", "tsfreq_validation_without_candidate"],
            phase,
        )
    if phase == "gaussian_tsfreq_validation":
        return (
            ["tsfreq_validation_missing_after_backtrack_target"],
            ["gaussian_tsfreq_validation", "gaussian_input_preflight", "candidate_quality_review"],
            ["accepted_ts", "connectivity_claim_without_tsfreq"],
            phase,
        )
    if phase == "connectivity_validation":
        return (
            ["connectivity_missing_after_backtrack_target"],
            ["imaginary_mode_endpoint_follow", "endpoint_connectivity_check", "irc_connectivity_check"],
            ["accepted_ts_without_connectivity", "visual_only_connectivity_claim"],
            phase,
        )
    if phase == "accepted_ts_ready":
        return (
            [],
            ["finalize_accepted_ts_if_structured_evidence_passes", "audit_frequency_and_connectivity_payloads"],
            ["accepted_ts_without_structured_tsfreq_and_connectivity_evidence"],
            phase,
        )
    return ([], ["inspect_backtrack_target"], ["new_child_under_failed_node_without_backtrack"], phase)


def infer_phase_from_focus_node(node_id: str, node_payloads: dict[str, dict[str, Any]]) -> str:
    """Infer the next planning phase from the node selected as focus."""

    node = node_payloads.get(node_id, {})
    claim_status = clean_string(node.get("claim_status"))
    if claim_status == "endpoint_minima_ready":
        return "candidate_generation"
    if claim_status == "candidate_found":
        return "gaussian_tsfreq_validation"
    if claim_status == "tsfreq_validated":
        return "connectivity_validation"
    if claim_status in {"endpoint_connected", "irc_connected"}:
        return "accepted_ts_ready"
    if claim_status == "accepted_ts":
        return "accepted_ts_present"
    return "endpoint_discovery"


def infer_planning_focus(
    *,
    phase: str,
    validation_errors: list[dict[str, Any]],
    active_nodes: list[dict[str, Any]],
    accepted_nodes: list[tuple[str, dict[str, Any]]],
    failed_nodes: list[dict[str, Any]],
    backtrack_events: list[dict[str, Any]],
    suggested_backtrack_actions: list[dict[str, Any]],
    node_payloads: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    alternative_mechanism: bool,
    pathway_plan: dict[str, Any],
    pathway_step_node_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Choose the node and context mode that should guide the next model call."""

    if validation_errors:
        return {
            "mode": "workspace_repair",
            "focus_node": None,
            "parent_for_new_branch": None,
            "reason": "Workspace validation errors block scientific planning.",
        }
    if active_nodes:
        focus_node = clean_string(active_nodes[-1].get("node_id"))
        return {
            "mode": "active_work",
            "focus_node": focus_node or None,
            "parent_for_new_branch": None,
            "reason": "A node is pending, running, or parsing; parse or stop it before opening a new branch.",
        }
    if pathway_plan.get("mode") in {"start", "continue"}:
        next_step = pathway_plan.get("next_step") if isinstance(pathway_plan.get("next_step"), dict) else {}
        focus_node = default_focus_node_for_phase(phase, pathway_step_node_payloads)
        previous_step_node = clean_string(manifest.get("current_accepted_ts")) or latest_node_id(accepted_nodes)
        if not focus_node and pathway_plan.get("mode") == "continue":
            focus_node = previous_step_node
        parent_for_new_branch = focus_node
        if phase == "endpoint_discovery":
            parent_for_new_branch = previous_step_node if pathway_plan.get("mode") == "continue" else None
        return {
            "mode": "pathway_step_planning",
            "focus_node": focus_node,
            "parent_for_new_branch": parent_for_new_branch,
            "pathway_id": clean_string(next_step.get("pathway_id")),
            "step_id": clean_string(next_step.get("step_id")),
            "reason": (
                "The active multi-step pathway is scoped to the next incomplete elementary step; "
                "plan this step through endpoint, candidate, TS/Freq, and connectivity gates without reusing a previous step as proof."
            ),
        }
    if pathway_plan.get("mode") == "complete":
        focus_node = clean_string(manifest.get("current_accepted_ts")) or latest_node_id(accepted_nodes)
        return {
            "mode": "pathway_complete",
            "focus_node": focus_node,
            "parent_for_new_branch": None,
            "reason": "Every required elementary step in the active pathway is bound to an accepted_ts node.",
        }
    if pathway_plan.get("mode") in {"ambiguous", "rejected"}:
        active_pathway = pathway_plan.get("pathway") if isinstance(pathway_plan.get("pathway"), dict) else {}
        focus_node = latest_pathway_status_node(active_pathway) or clean_string(manifest.get("current_accepted_ts")) or latest_node_id(accepted_nodes)
        return {
            "mode": f"pathway_{clean_string(pathway_plan.get('mode'))}_review",
            "focus_node": focus_node,
            "parent_for_new_branch": None,
            "pathway_id": clean_string(active_pathway.get("pathway_id")),
            "reason": (
                "The active multi-step pathway has an ambiguous or rejected step; "
                "reassess the mechanism hypothesis before opening another forward step."
            ),
        }
    if accepted_nodes or clean_string(manifest.get("current_accepted_ts")):
        focus_node = clean_string(manifest.get("current_accepted_ts")) or latest_node_id(accepted_nodes)
        if alternative_mechanism:
            return {
                "mode": "alternative_mechanism_planning",
                "focus_node": focus_node,
                "parent_for_new_branch": None,
                "reason": "Accepted TS state exists and the user requested a chemically distinct alternative-mechanism branch.",
            }
        return {
            "mode": "accepted_audit",
            "focus_node": focus_node,
            "parent_for_new_branch": None,
            "reason": "Accepted TS state exists; next planning should audit or branch only on explicit request.",
        }

    active_backtracks = [event for event in backtrack_events if clean_string(event.get("event_state")) == "active"]
    if active_backtracks:
        event = active_backtracks[-1]
        focus_node = clean_string(event.get("to_node"))
        from_node = clean_string(event.get("from_node"))
        return {
            "mode": "backtrack_replan",
            "focus_node": focus_node,
            "from_failed_node": from_node,
            "parent_for_new_branch": focus_node or None,
            "backtrack_event_id": clean_string(event.get("id")),
            "reason_code": clean_string(event.get("reason_code")),
            "reason": clean_string(event.get("reason")) or "Backtrack event routes planning to an earlier chemistry decision.",
        }

    if suggested_backtrack_actions:
        latest = suggested_backtrack_actions[-1]
        return {
            "mode": "backtrack_decision_needed",
            "focus_node": clean_string(latest.get("from_node")),
            "parent_for_new_branch": None,
            "reason": "A failed or ambiguous branch has no canonical backtrack event; record the backtrack target before opening a new child branch.",
        }

    return {
        "mode": "advance",
        "focus_node": default_focus_node_for_phase(phase, node_payloads),
        "parent_for_new_branch": None,
        "reason": "No active backtrack or blocking failure; continue from the current evidence gate.",
    }


def default_focus_node_for_phase(phase: str, node_payloads: dict[str, dict[str, Any]]) -> str | None:
    """Return a reasonable focus node for ordinary forward planning."""

    claim_by_phase = {
        "candidate_generation": "endpoint_minima_ready",
        "gaussian_tsfreq_validation": "candidate_found",
        "connectivity_validation": "tsfreq_validated",
        "accepted_ts_ready": "endpoint_connected",
    }
    claim = claim_by_phase.get(phase)
    if not claim:
        return latest_node_id([(node_id, node) for node_id, node in node_payloads.items()])
    nodes = nodes_with_claim(node_payloads, claim)
    if not nodes and phase == "accepted_ts_ready":
        nodes = nodes_with_claim(node_payloads, "irc_connected")
    return latest_node_id(nodes)


def latest_pathway_status_node(pathway: dict[str, Any]) -> str | None:
    """Return the latest step-level node recorded in a pathway summary."""

    steps = [step for step in list_or_empty(pathway.get("steps")) if isinstance(step, dict)]
    for step in reversed(steps):
        for key in ("status_node", "accepted_ts_node"):
            node_id = clean_string(step.get(key))
            if node_id:
                return node_id
    return None


def suggest_decision_cards(
    *,
    source: Path,
    phase: str,
    endpoint_nodes: list[tuple[str, dict[str, Any]]],
    candidate_nodes: list[tuple[str, dict[str, Any]]],
    tsfreq_nodes: list[tuple[str, dict[str, Any]]],
    parent_override: str | None,
    pathway_plan: dict[str, Any],
    max_suggestions: int,
) -> list[dict[str, Any]]:
    """Return decision-card suggestions for the current planning phase."""

    suggestions: list[dict[str, Any]] = []
    if max_suggestions <= 0:
        return suggestions
    pathway_target = pathway_target_for_suggestions(pathway_plan)
    pathway_id = clean_string(pathway_target.get("pathway_id"))
    step_id = clean_string(pathway_target.get("step_id"))

    if phase == "endpoint_discovery":
        parent = parent_override
        suggestions.append(
            decision_card_suggestion(
                source,
                stage="endpoint_minima_validation",
                operation="agent-selected-xtb-preopt-or-gaussian-endpoint-validation",
                parent_id=parent,
                hypothesis="Validate distinct reactant/product endpoint minima or chemically justified constrained references before candidate generation, using xTB for low-cost preoptimization or Gaussian when endpoint evidence must be definitive.",
                reason="Candidate generation is blocked until endpoint_minima_ready evidence exists.",
                pathway_id=pathway_id,
                step_id=step_id,
            )
        )
    elif phase == "candidate_generation":
        parent = parent_override or latest_node_id(endpoint_nodes)
        suggestions.append(
            decision_card_suggestion(
                source,
                stage="candidate_generation",
                operation="agent-selected-xtb-neb-scan-dimer-gaussian-refinement-qst-or-qbics",
                parent_id=parent,
                hypothesis="Generate a TS candidate from validated endpoint references, usually with xTB for broad path discovery or Gaussian refinement only when lower-level evidence justifies the cost.",
                reason="Endpoints are ready and no candidate_found node exists.",
                pathway_id=pathway_id,
                step_id=step_id,
            )
        )
    elif phase == "gaussian_tsfreq_validation":
        parent = parent_override or latest_node_id(candidate_nodes)
        suggestions.append(
            decision_card_suggestion(
                source,
                stage="gaussian_tsfreq_validation",
                operation="gaussian-tsfreq",
                parent_id=parent,
                hypothesis="Test whether the candidate is a stationary point with exactly one intended imaginary frequency.",
                reason="A candidate exists but TS/Freq validation is missing.",
                pathway_id=pathway_id,
                step_id=step_id,
            )
        )
    elif phase == "connectivity_validation":
        parent = parent_override or latest_node_id(tsfreq_nodes)
        suggestions.append(
            decision_card_suggestion(
                source,
                stage="connectivity_validation",
                operation="mode-endpoint-or-irc-connectivity",
                parent_id=parent,
                hypothesis="Check whether the frequency-validated TS connects the intended reactant and product references.",
                reason="TS/Freq validation exists but endpoint/IRC connectivity evidence is missing.",
                pathway_id=pathway_id,
                step_id=step_id,
            )
        )
    elif phase == "alternative_mechanism_planning":
        suggestions.append(
            decision_card_suggestion(
                source,
                stage="mechanism_preflight",
                operation="alternative-mechanism-preflight",
                parent_id=None,
                hypothesis="Test a chemically distinct mechanism after preserving the accepted TS as prior evidence, starting from mechanism preflight and endpoint identity rather than reusing the accepted branch as proof.",
                reason="An accepted TS already exists; alternative planning must be explicitly distinct and cannot overwrite the accepted branch.",
            )
        )
    elif phase == "pathway_step_planning":
        next_step = pathway_plan.get("next_step") if isinstance(pathway_plan.get("next_step"), dict) else {}
        parent = parent_override
        pathway_id = clean_string(next_step.get("pathway_id"))
        step_id = clean_string(next_step.get("step_id"))
        label = clean_string(next_step.get("label")) or f"{clean_string(next_step.get('from'))} -> {clean_string(next_step.get('to'))}"
        suggestions.append(
            decision_card_suggestion(
                source,
                stage="endpoint_minima_validation",
                operation="next-step-endpoint-or-intermediate-validation",
                parent_id=parent,
                hypothesis=f"Validate endpoint or intermediate references for pathway step {step_id}: {label}.",
                reason="The active multi-step pathway has an accepted TS for an earlier step but at least one elementary step remains incomplete.",
                pathway_id=pathway_id,
                step_id=step_id,
            )
        )
    return suggestions[:max_suggestions]


def pathway_target_for_suggestions(pathway_plan: dict[str, Any]) -> dict[str, str]:
    """Return pathway metadata for decision-card or finalization suggestions."""

    if pathway_plan.get("mode") not in {"start", "continue"}:
        return {}
    next_step = pathway_plan.get("next_step") if isinstance(pathway_plan.get("next_step"), dict) else {}
    return {
        "pathway_id": clean_string(next_step.get("pathway_id")),
        "step_id": clean_string(next_step.get("step_id")),
    }


def decision_card_suggestion(
    root: Path,
    *,
    stage: str,
    operation: str,
    parent_id: str | None,
    hypothesis: str,
    reason: str,
    pathway_id: str = "",
    step_id: str = "",
) -> dict[str, Any]:
    """Build one suggested decision-card entry."""

    node_id = next_suggested_node_id(root, stage)
    command = [
        "python",
        "scripts/ts_hypothesis_workspace.py",
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--stage",
        stage,
        "--hypothesis",
        hypothesis,
        "--operation",
        operation,
    ]
    if parent_id:
        command.extend(["--parent-id", parent_id])
    if pathway_id and step_id:
        command.extend(["--pathway-id", pathway_id, "--step-id", step_id])
    return {
        "kind": "decision_card",
        "node_id": node_id,
        "parent_id": parent_id,
        "input_refs": [],
        "pathway_id": pathway_id,
        "step_id": step_id,
        "stage": stage,
        "operation": operation,
        "hypothesis": hypothesis,
        "reason": reason,
        "decision_card_command": command,
        "agent_must_choose": [
            "specific chemical hypothesis",
            "method/route details",
            "reaction-center observables",
            "cost and failure criteria",
        ],
    }


def suggest_finalization_actions(
    *,
    source: Path,
    phase: str,
    tsfreq_nodes: list[tuple[str, dict[str, Any]]],
    connectivity_nodes: list[tuple[str, dict[str, Any]]],
    pathway_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return non-decision-card actions when a claim may be ready to close."""

    if phase != "accepted_ts_ready":
        return []
    tsfreq_node = latest_node_id(tsfreq_nodes)
    connectivity_node = latest_node_id(connectivity_nodes)
    pathway_target = pathway_target_for_suggestions(pathway_plan)
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
            "kind": "finalize_node",
            "target": "agent_selected_connectivity_or_validation_node",
            "requires": ["structured_tsfreq_evidence", "structured_connectivity_evidence"],
            "reason": "TS/Freq and connectivity claim layers both exist; agent must verify they refer to the same intended reaction before accepted_ts.",
            "command_template": [
                "python",
                "scripts/ts_hypothesis_workspace.py",
                "finalize-node",
                "--root",
                str(source),
                "--node-id",
                "<agent_selected_node>",
                "--claim-status",
                "accepted_ts",
                "--decision",
                "stop_search_accept_ts",
                "--summary",
                "<source-backed acceptance summary>",
                "--primary-file",
                "<connectivity_summary.json>",
                *pathway_args,
                "--evidence",
                "<tsfreq_evidence_json>",
                "--evidence",
                "<connectivity_evidence_json>",
                "--computational-outcome",
                "<validated computation outcome>",
                "--mechanistic-implication",
                "<mechanism implication>",
                "--next-branch",
                "No further branch unless an alternative mechanism is requested.",
            ],
            "candidate_source_nodes": {"tsfreq": tsfreq_node, "connectivity": connectivity_node},
        }
    ]


def suggest_reframe_actions(
    *,
    source: Path,
    reframe_candidates: list[dict[str, Any]],
    max_suggestions: int,
) -> list[dict[str, Any]]:
    """Return planning actions for reusing a failed TS/Freq node under a new reaction boundary."""

    actions: list[dict[str, Any]] = []
    if max_suggestions <= 0:
        return actions
    for candidate in reframe_candidates[:max_suggestions]:
        source_node = clean_string(candidate.get("node_id"))
        if not source_node:
            continue
        actions.append(
            {
                "kind": "reframe_validated_wrong_mode_tsfreq",
                "source_node": source_node,
                "requires": [
                    "new_or_validated_endpoint_refs_for_reframed_reaction",
                    "decision_card_with_input_ref_to_source_tsfreq_node",
                    "new_connectivity_evidence_attached_to_new_node",
                ],
                "reason": (
                    "The source node contains TS/Freq evidence but was rejected or ambiguous under its original "
                    "mechanism. It can seed a new mechanism-boundary test only as an input reference."
                ),
                "decision_card_command_template": [
                    "python",
                    "scripts/ts_hypothesis_workspace.py",
                    "decision-card",
                    "--root",
                    str(source),
                    "--node-id",
                    "<new_reframed_connectivity_node>",
                    "--parent-id",
                    "<agent_selected_endpoint_or_intermediate_node>",
                    "--input-ref",
                    source_node,
                    "--stage",
                    "connectivity_validation",
                    "--hypothesis",
                    "<new intended reaction boundary that makes the old TS/Freq chemically relevant>",
                    "--operation",
                    "reframe-validated-wrong-mode-tsfreq-connectivity",
                ],
                "finalization_rule": (
                    "If the reframed branch succeeds, finalize the new node with both copied/recorded TS/Freq "
                    "evidence and new connectivity evidence; do not promote the old rejected node."
                ),
            }
        )
    return actions


def summarize_node(node_id: str, node: dict[str, Any]) -> dict[str, Any]:
    """Return compact node state for planner context."""

    display = node.get("display") if isinstance(node.get("display"), dict) else {}
    return {
        "node_id": node_id,
        "parent_id": clean_string(node.get("parent_id")) or None,
        "stage": clean_string(node.get("stage")),
        "operation": clean_string(node.get("operation")),
        "lifecycle_state": clean_string(node.get("lifecycle_state")),
        "run_state": clean_string(node.get("run_state")),
        "claim_status": clean_string(node.get("claim_status")),
        "outcome": clean_string(node.get("outcome")),
        "outcome_code": node.get("outcome_code"),
        "decision": clean_string(node.get("decision")),
        "summary": clean_string(display.get("summary")) or clean_string(node.get("hypothesis")),
    }


def failed_or_ambiguous_node_summaries(root: Path, node_payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact context for branches that should inform backtracking."""

    out: list[dict[str, Any]] = []
    for node_id, node in sorted(node_payloads.items(), key=lambda item: node_sort_key(item[0])):
        claim = clean_string(node.get("claim_status"))
        outcome = clean_string(node.get("outcome"))
        if claim not in {"rejected", "ambiguous"} and outcome not in {
            "chemical_failure",
            "numerical_failure",
            "wrong_mode",
            "wrong_endpoint",
            "parser_refused",
        }:
            continue
        summary = summarize_node(node_id, node)
        summary["reflection"] = read_reflection_brief(root / "nodes" / node_id / "reflection.md")
        out.append(summary)
    return out


def evidence_records_from_registry(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Return valid evidence records from the registry payload."""

    return [item for item in list_or_empty(evidence.get("records")) if isinstance(item, dict)]


def reframe_candidate_summaries(
    *,
    source: Path,
    node_payloads: dict[str, dict[str, Any]],
    evidence_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find failed TS/Freq nodes that may be input evidence for a reframed mechanism."""

    records_by_node: dict[str, list[dict[str, Any]]] = {}
    for record in evidence_records:
        node_id = clean_string(record.get("node_id"))
        if node_id:
            records_by_node.setdefault(node_id, []).append(record)

    out: list[dict[str, Any]] = []
    for node_id, node in sorted(node_payloads.items(), key=lambda item: node_sort_key(item[0])):
        claim = clean_string(node.get("claim_status"))
        outcome = clean_string(node.get("outcome"))
        if claim not in {"rejected", "ambiguous"} and outcome not in {"wrong_mode", "wrong_endpoint"}:
            continue
        tsfreq_records = [
            summarize_reframe_tsfreq_record(record)
            for record in records_by_node.get(node_id, [])
            if record_supports_tsfreq_reframe(source, record)
        ]
        if not tsfreq_records:
            continue
        summary = summarize_node(node_id, node)
        out.append(
            {
                "node_id": node_id,
                "claim_status": clean_string(summary.get("claim_status")),
                "outcome": clean_string(summary.get("outcome")),
                "outcome_code": summary.get("outcome_code"),
                "stage": clean_string(summary.get("stage")),
                "operation": clean_string(summary.get("operation")),
                "summary": clean_string(summary.get("summary")),
                "tsfreq_evidence": tsfreq_records[:4],
                "reuse_rule": (
                    "Keep this node closed under its original hypothesis; create a new node with "
                    "input_refs to this node and attach new connectivity evidence for the reframed intended reaction."
                ),
            }
        )
    return out


def record_supports_tsfreq_reframe(root: Path, record: dict[str, Any]) -> bool:
    """Return true when an evidence record can support TS/Freq reuse planning."""

    if clean_string(record.get("evidence_state")) != "supports":
        return False
    payload = load_record_payload(root, record)
    if supports_tsfreq_gate(record, payload):
        return True
    kind = normalized_token(record.get("kind"))
    return kind in TSFREQ_KINDS


def summarize_reframe_tsfreq_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return compact TS/Freq evidence metadata for reframe planning."""

    return {
        "evidence_id": clean_string(record.get("evidence_id")),
        "kind": clean_string(record.get("kind")),
        "path": clean_string(record.get("path")),
        "claim": clean_string(record.get("claim")),
    }


def backtrack_event_summaries(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact canonical backtrack events for planning packets."""

    out: list[dict[str, Any]] = []
    for item in list_or_empty(tree.get("backtrack_events")):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": clean_string(item.get("id")),
                "from_node": clean_string(item.get("from_node")),
                "to_node": clean_string(item.get("to_node")),
                "new_branch_node": clean_string(item.get("new_branch_node")),
                "reason_code": clean_string(item.get("reason_code")),
                "reason": clean_string(item.get("reason")),
                "evidence_refs": [clean_string(ref) for ref in list_or_empty(item.get("evidence_refs")) if clean_string(ref)],
                "event_state": clean_string(item.get("event_state")) or "active",
                "created_at": clean_string(item.get("created_at")),
            }
        )
    return out


def suggest_backtrack_actions(
    *,
    source: Path,
    failed_nodes: list[dict[str, Any]],
    backtrack_events: list[dict[str, Any]],
    node_payloads: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suggest canonical backtrack records for failed branches without one."""

    from_nodes_with_event = {clean_string(event.get("from_node")) for event in backtrack_events}
    suggestions: list[dict[str, Any]] = []
    for failed in failed_nodes:
        node_id = clean_string(failed.get("node_id"))
        if not node_id or node_id in from_nodes_with_event:
            continue
        candidate_targets = candidate_backtrack_targets(node_id, node_payloads)
        reason_code = clean_string(failed.get("outcome_code")) or clean_string(failed.get("outcome")) or "branch_failed"
        suggestions.append(
            {
                "kind": "record_backtrack",
                "from_node": node_id,
                "candidate_to_nodes": candidate_targets,
                "reason_code": reason_code,
                "reason": backtrack_reason_from_failed_summary(failed),
                "command_template": [
                    "python",
                    "scripts/ts_hypothesis_workspace.py",
                    "record-backtrack",
                    "--root",
                    str(source),
                    "--from-node",
                    node_id,
                    "--to-node",
                    "<agent_selected_chemically_meaningful_ancestor>",
                    "--reason-code",
                    reason_code,
                    "--reason",
                    "<source-backed reason for returning to that ancestor>",
                ],
                "agent_must_choose": [
                    "closest chemically meaningful ancestor",
                    "whether the new branch reuses any failed-branch artifacts as input_refs",
                    "which changed variable makes the new branch chemically distinct",
                ],
            }
        )
    return suggestions


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


def build_context_items(
    *,
    source: Path,
    phase: str,
    planning_focus: dict[str, Any],
    node_payloads: dict[str, dict[str, Any]],
    failed_nodes: list[dict[str, Any]],
    reframe_candidates: list[dict[str, Any]],
    pathway_summary: dict[str, Any],
    mechanism: dict[str, Any],
    validation_summary: dict[str, Any],
    backtrack_events: list[dict[str, Any]],
    accepted_nodes: list[tuple[str, dict[str, Any]]],
    active_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select prioritized context for the next model planning step."""

    items: list[dict[str, Any]] = []
    items.append(
        {
            "priority": "must",
            "kind": "workspace_validation",
            "source": "validator",
            "reason": "Workspace contract status controls whether scientific planning is allowed.",
            "summary": jsonish_compact(validation_summary),
        }
    )
    items.append(
        {
            "priority": "must",
            "kind": "planning_focus",
            "source": "tree.json",
            "reason": "The planning focus determines where new tree branches may attach.",
            "summary": jsonish_compact(planning_focus),
        }
    )
    if bool(pathway_summary.get("present")):
        items.append(
            {
                "priority": "must" if clean_string(pathway_summary.get("mode")) == "multi_step" else "should",
                "kind": "pathway_model",
                "source": "pathway_model.json",
                "reason": "Pathway state controls whether accepted_ts is only one completed elementary step or the whole active pathway is complete.",
                "summary": jsonish_compact(pathway_summary),
            }
        )
    focus_node = clean_string(planning_focus.get("focus_node"))
    if focus_node:
        for index, lineage_node in enumerate(lineage_to_root(focus_node, node_payloads)):
            priority = "must" if lineage_node == focus_node else "should"
            items.append(node_context_item(lineage_node, node_payloads, priority=priority, kind="focus_lineage", reason=f"Lineage node {index + 1} leading to planning focus."))
    from_failed_node = clean_string(planning_focus.get("from_failed_node"))
    if from_failed_node:
        failed = failed_summary_by_id(failed_nodes).get(from_failed_node)
        if failed:
            items.append(failed_branch_context_item(failed, priority="must", reason="Failed branch that triggered the active backtrack."))
    for failed in failed_nodes[:6]:
        node_id = clean_string(failed.get("node_id"))
        if node_id and node_id != from_failed_node:
            items.append(failed_branch_context_item(failed, priority="should", reason="Sibling or historical failed branch that may prevent repeated mistakes."))
    for candidate in reframe_candidates[:4]:
        items.append(
            {
                "priority": "should",
                "kind": "reframe_candidate",
                "source": f"nodes/{clean_string(candidate.get('node_id'))}/node.json",
                "node_id": clean_string(candidate.get("node_id")),
                "claim_status": clean_string(candidate.get("claim_status")),
                "outcome": clean_string(candidate.get("outcome")),
                "outcome_code": candidate.get("outcome_code"),
                "reason": "Failed TS/Freq evidence may be useful only as an input_ref for a new mechanism-boundary branch.",
                "summary": clean_string(candidate.get("summary")),
            }
        )
    if active_nodes:
        for active in active_nodes[:4]:
            items.append(
                {
                    "priority": "must",
                    "kind": "active_node",
                    "source": f"nodes/{clean_string(active.get('node_id'))}/node.json",
                    "node_id": clean_string(active.get("node_id")),
                    "reason": "Active work should be parsed or stopped before a new scientific branch is opened.",
                    "summary": clean_string(active.get("summary")),
                }
            )
    if accepted_nodes:
        for node_id, _node in accepted_nodes[:3]:
            items.append(node_context_item(node_id, node_payloads, priority="must", kind="accepted_node", reason="Accepted claims must remain visible during audit or alternative-branch planning."))
    if backtrack_events:
        items.append(
            {
                "priority": "should",
                "kind": "backtrack_events",
                "source": "tree.json",
                "reason": "Backtrack edges route new planning to ancestor nodes without losing failed-branch lessons.",
                "summary": jsonish_compact(backtrack_events[:6]),
            }
        )
    mechanism_bits = []
    for label, key in (
        ("validated_facts", "validated_facts"),
        ("refuted_hypotheses", "refuted_hypotheses"),
        ("open_questions", "open_questions"),
    ):
        values = list_or_empty(mechanism.get(key))[:6]
        if values:
            mechanism_bits.append({label: values})
    if mechanism_bits:
        items.append(
            {
                "priority": "should",
                "kind": "mechanism_memory",
                "source": "mechanism_model.json",
                "reason": "Mechanism facts and refutations guide chemically distinct replanning.",
                "summary": jsonish_compact(mechanism_bits),
            }
        )
    return rank_context_items(items)[:24]


def rank_context_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach explicit retrieval ranks so agents know what to read first."""

    priority_score = {"must": 100, "should": 60, "could": 25}
    kind_bonus = {
        "planning_focus": 30,
        "workspace_validation": 25,
        "pathway_model": 24,
        "failed_branch_lesson": 22,
        "accepted_node": 20,
        "focus_lineage": 15,
        "reframe_candidate": 14,
        "mechanism_memory": 12,
        "backtrack_events": 10,
        "active_node": 10,
    }
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for original_index, item in enumerate(items):
        priority = clean_string(item.get("priority"))
        kind = clean_string(item.get("kind"))
        score = priority_score.get(priority, 0) + kind_bonus.get(kind, 0)
        enriched = dict(item)
        enriched["retrieval_score"] = score
        enriched["retrieval_action"] = "read_first" if score >= 100 else "skim_if_needed"
        ranked.append((-score, original_index, enriched))
    out: list[dict[str, Any]] = []
    for rank, (_negative_score, _original_index, item) in enumerate(sorted(ranked), start=1):
        item["retrieval_rank"] = rank
        out.append(item)
    return out


def node_context_item(
    node_id: str,
    node_payloads: dict[str, dict[str, Any]],
    *,
    priority: str,
    kind: str,
    reason: str,
) -> dict[str, Any]:
    """Return a compact node context item."""

    node = node_payloads.get(node_id, {})
    summary = summarize_node(node_id, node)
    return {
        "priority": priority,
        "kind": kind,
        "source": f"nodes/{node_id}/node.json",
        "node_id": node_id,
        "claim_status": clean_string(summary.get("claim_status")),
        "outcome": clean_string(summary.get("outcome")),
        "outcome_code": summary.get("outcome_code"),
        "reason": reason,
        "summary": clean_string(summary.get("summary")),
    }


def failed_branch_context_item(failed: dict[str, Any], *, priority: str, reason: str) -> dict[str, Any]:
    """Return a compact failed-branch lesson for planning context."""

    node_id = clean_string(failed.get("node_id"))
    reflection = failed.get("reflection") if isinstance(failed.get("reflection"), dict) else {}
    summary = clean_string(reflection.get("mechanistic_implication")) or clean_string(failed.get("summary"))
    return {
        "priority": priority,
        "kind": "failed_branch_lesson",
        "source": f"nodes/{node_id}/reflection.md",
        "node_id": node_id,
        "claim_status": clean_string(failed.get("claim_status")),
        "outcome": clean_string(failed.get("outcome")),
        "outcome_code": failed.get("outcome_code"),
        "reason": reason,
        "summary": summary,
        "next_branch": clean_string(reflection.get("next_branch")),
    }


def failed_summary_by_id(failed_nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index failed branch summaries by node id."""

    return {clean_string(item.get("node_id")): item for item in failed_nodes if clean_string(item.get("node_id"))}


def jsonish_compact(value: Any) -> str:
    """Return a compact JSON-like string for context summaries."""

    if isinstance(value, str):
        return value
    return str(value)[:800]


def read_reflection_brief(path: Path) -> dict[str, str]:
    """Read a short reflection summary without expanding the whole file."""

    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "computational_outcome": first_section_line(text, "Computational Outcome"),
        "mechanistic_implication": first_section_line(text, "Mechanistic Implication"),
        "next_branch": first_section_line(text, "Next Branch"),
    }


def first_section_line(text: str, section: str) -> str:
    """Return the first non-empty line after a markdown heading."""

    marker = f"## {section}".lower()
    lines = text.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower() == marker:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            return ""
        if in_section and stripped:
            return stripped[:240]
    return ""


def summarize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return evidence counts for planner context."""

    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_node: dict[str, int] = {}
    for record in list_or_empty(evidence.get("records")):
        if not isinstance(record, dict):
            continue
        state = clean_string(record.get("evidence_state")) or "unknown"
        kind = clean_string(record.get("kind")) or "unknown"
        node_id = clean_string(record.get("node_id")) or "unknown"
        by_state[state] = by_state.get(state, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_node[node_id] = by_node.get(node_id, 0) + 1
    return {
        "records": sum(by_state.values()),
        "by_state": by_state,
        "by_kind": by_kind,
        "by_node": by_node,
    }


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
