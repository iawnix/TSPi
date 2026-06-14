"""Action suggestion builders for ChemKernel plan-next packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.util.path_utils import clean_string

from .ids import latest_node_id, next_suggested_node_id
from .pathway import pathway_target_for_suggestions


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


__all__ = [
    "suggest_decision_cards",
    "decision_card_suggestion",
    "suggest_finalization_actions",
    "suggest_reframe_actions",
    "suggest_backtrack_actions",
    "candidate_backtrack_targets",
    "lineage_to_root",
    "backtrack_reason_from_failed_summary",
]
