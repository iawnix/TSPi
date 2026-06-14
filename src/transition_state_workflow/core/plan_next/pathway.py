"""Pathway-scoped planning helpers for ChemKernel plan-next packets."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.util.path_utils import clean_string, list_or_empty


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


def latest_pathway_status_node(pathway: dict[str, Any]) -> str | None:
    """Return the latest step-level node recorded in a pathway summary."""

    steps = [step for step in list_or_empty(pathway.get("steps")) if isinstance(step, dict)]
    for step in reversed(steps):
        for key in ("status_node", "accepted_ts_node"):
            node_id = clean_string(step.get(key))
            if node_id:
                return node_id
    return None


def pathway_target_for_suggestions(pathway_plan: dict[str, Any]) -> dict[str, str]:
    """Return pathway metadata for decision-card or finalization suggestions."""

    if pathway_plan.get("mode") not in {"start", "continue"}:
        return {}
    next_step = pathway_plan.get("next_step") if isinstance(pathway_plan.get("next_step"), dict) else {}
    return {
        "pathway_id": clean_string(next_step.get("pathway_id")),
        "step_id": clean_string(next_step.get("step_id")),
    }


__all__ = [
    "infer_pathway_plan",
    "filter_nodes_for_pathway_step",
    "latest_pathway_status_node",
    "pathway_target_for_suggestions",
]
