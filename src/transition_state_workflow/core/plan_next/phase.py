"""Phase and focus inference for ChemKernel workspace report packets."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.util.path_utils import clean_string

from .ids import latest_node_id
from .loader import nodes_with_claim
from .pathway import latest_pathway_status_node


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
) -> str:
    """Infer the report attention phase."""

    if validation_errors:
        return "workspace_repair_required"
    if active_nodes:
        return "active_work_running"
    if accepted_nodes or clean_string(manifest.get("current_accepted_ts")):
        if alternative_mechanism:
            return "alternative_mechanism_planning"
        return "accepted_ts_present"
    if not endpoint_nodes:
        return "endpoint_discovery"
    if not candidate_nodes and not tsfreq_nodes:
        return "candidate_generation"
    if not tsfreq_nodes:
        return "gaussian_tsfreq_validation"
    if not connectivity_nodes:
        return "connectivity_validation"
    return "accepted_ts_ready"


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
    required_backtrack_events: list[dict[str, Any]],
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

    if required_backtrack_events:
        latest = required_backtrack_events[-1]
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


__all__ = [
    "infer_planning_state",
    "infer_phase_from_focus_node",
    "infer_planning_focus",
    "default_focus_node_for_phase",
]
