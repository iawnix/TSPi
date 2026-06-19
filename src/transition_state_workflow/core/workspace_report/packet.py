"""Packet orchestration for ChemKernel workspace report context."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .context import build_context_items, summarize_evidence
from .contracts import WORKSPACE_REPORT_PACKET_SCHEMA, TsfreqEvidencePredicate, WorkspaceValidator
from .ids import node_sort_key
from .loader import conservative_workspace_validation, no_tsfreq_evidence_support
from .pathway import filter_nodes_for_pathway_step, infer_pathway_attention
from .phase import infer_attention_phase, infer_phase_from_focus_node, infer_report_focus
from .readiness import (
    PUBLIC_DECISION_ACTIONS,
    build_claim_readiness,
    current_phase_reasons,
    current_phase_scope,
)
from .snapshot import classify_node_claims, load_workspace_report_snapshot
from .suggestions import (
    suggest_backtrack_actions,
    suggest_finalization_actions,
    suggest_reframe_actions,
)


def build_workspace_report_packet(
    root: Path,
    *,
    max_suggestions: int = 4,
    alternative_mechanism: bool = False,
    command_alias: str = "report_workspace",
    validate_workspace: WorkspaceValidator | None = None,
    supports_tsfreq_evidence: TsfreqEvidencePredicate | None = None,
) -> dict[str, Any]:
    """Return compact workspace context for the next agent decision."""

    validate_workspace = validate_workspace or conservative_workspace_validation
    supports_tsfreq_evidence = supports_tsfreq_evidence or no_tsfreq_evidence_support
    snapshot = load_workspace_report_snapshot(
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

    phase = infer_attention_phase(
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
    pathway_attention = infer_pathway_attention(
        pathway_summary=pathway_summary,
        accepted_nodes=accepted_nodes,
        manifest=manifest,
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        alternative_mechanism=alternative_mechanism,
    )
    report_node_payloads = node_payloads
    report_claims = snapshot.claims
    if pathway_attention.get("mode") in {"start", "continue"}:
        next_step = pathway_attention.get("next_step") if isinstance(pathway_attention.get("next_step"), dict) else {}
        report_node_payloads = filter_nodes_for_pathway_step(
            node_payloads,
            pathway_id=clean_string(next_step.get("pathway_id")),
            step_id=clean_string(next_step.get("step_id")),
        )
        report_claims = classify_node_claims(
            report_node_payloads,
            source=source,
            evidence_records=snapshot.evidence_records,
        )
        phase = infer_attention_phase(
            validation_errors=validation_errors,
            active_nodes=active_nodes,
            endpoint_nodes=report_claims.endpoint_nodes,
            candidate_nodes=report_claims.candidate_nodes,
            tsfreq_nodes=report_claims.tsfreq_nodes,
            connectivity_nodes=report_claims.connectivity_nodes,
            accepted_nodes=report_claims.accepted_nodes,
            manifest={},
            alternative_mechanism=False,
        )
    elif pathway_attention.get("mode") == "complete":
        phase = "pathway_complete"
    elif pathway_attention.get("mode") in {"ambiguous", "rejected"}:
        mode = clean_string(pathway_attention.get("mode"))
        phase = f"pathway_{mode}"

    required_backtrack_events = suggest_backtrack_actions(
        source=source,
        failed_nodes=failed_nodes,
        backtrack_events=backtrack_events,
        node_payloads=node_payloads,
    )
    focus = infer_report_focus(
        phase=phase,
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        accepted_nodes=accepted_nodes,
        failed_nodes=failed_nodes,
        backtrack_events=backtrack_events,
        required_backtrack_events=required_backtrack_events,
        node_payloads=node_payloads,
        manifest=manifest,
        alternative_mechanism=alternative_mechanism,
        pathway_attention=pathway_attention,
        pathway_step_node_payloads=report_node_payloads,
    )
    if focus["mode"] == "backtrack_focus":
        focus_phase = infer_phase_from_focus_node(
            clean_string(focus.get("focus_node")),
            node_payloads,
        )
        if focus_phase:
            phase = focus_phase
    elif focus["mode"] == "backtrack_decision_needed":
        phase = "backtrack_decision_needed"
    endpoint_blockers_require_attention = bool(endpoint_evidence_blockers) and not (
        validation_errors
        or active_nodes
        or (accepted_nodes and not alternative_mechanism and pathway_attention.get("mode") not in {"start", "continue"})
    )
    if endpoint_blockers_require_attention:
        if focus["mode"] == "advance":
            latest_blocker = endpoint_evidence_blockers[-1]
            focus = {
                "mode": "endpoint_evidence_focus",
                "focus_node": clean_string(latest_blocker.get("node_id")),
                "parent_for_new_branch": None,
                "reason": (
                    "Parsed endpoint evidence is not validated; choose a chemically meaningful "
                    "ancestor and changed endpoint/connectivity hypothesis before opening the next branch."
                ),
            }

    required_reframe_checks = suggest_reframe_actions(
        source=source,
        reframe_candidates=reframe_candidates,
        max_suggestions=max_suggestions,
    )
    required_finalization_checks = suggest_finalization_actions(
        source=source,
        phase=phase,
        tsfreq_nodes=report_claims.tsfreq_nodes,
        connectivity_nodes=report_claims.connectivity_nodes,
        pathway_attention=pathway_attention,
    )
    claim_readiness = build_claim_readiness(
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        endpoint_nodes=report_claims.endpoint_nodes,
        candidate_nodes=report_claims.candidate_nodes,
        tsfreq_nodes=report_claims.tsfreq_nodes,
        connectivity_nodes=report_claims.connectivity_nodes,
        accepted_nodes=report_claims.accepted_nodes,
        manifest=manifest,
        endpoint_evidence_blockers=endpoint_evidence_blockers,
    )
    phase_reasons = current_phase_reasons(
        phase=phase,
        claim_readiness=claim_readiness,
        focus=focus,
    )

    packet = {
        "schema": WORKSPACE_REPORT_PACKET_SCHEMA,
        "packet_role": "decision_context",
        "source": str(source),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": command_alias,
        "agent_decision_required": True,
        "context_role": "Summarize workspace state, claim readiness, attention focus, and evidence pointers for the model.",
        "decision_authority": {
            "model_owns": ["route", "method", "next public command", "chemical hypothesis"],
            "report_owns": ["workspace summary", "claim readiness", "attention focus", "evidence pointers"],
            "validators_own": ["workspace structure", "decision provenance completeness", "evidence gate consistency"],
        },
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
            "phase_scope": current_phase_scope(phase),
            "phase_reasons": phase_reasons,
            "global_phase": global_phase,
            "endpoint_minima_ready_nodes": [node_id for node_id, _ in sorted(endpoint_nodes, key=lambda item: node_sort_key(item[0]))],
            "candidate_nodes": [node_id for node_id, _ in sorted(candidate_nodes, key=lambda item: node_sort_key(item[0]))],
            "tsfreq_validated_nodes": [node_id for node_id, _ in sorted(tsfreq_nodes, key=lambda item: node_sort_key(item[0]))],
            "connectivity_nodes": [node_id for node_id, _ in sorted(connectivity_nodes, key=lambda item: node_sort_key(item[0]))],
            "accepted_nodes": [node_id for node_id, _ in sorted(accepted_nodes, key=lambda item: node_sort_key(item[0]))],
            "current_pathway_step_nodes": [node_id for node_id in sorted(report_node_payloads, key=node_sort_key)]
            if pathway_attention.get("mode") in {"start", "continue"}
            else [],
            "pathway_phase": clean_string(pathway_attention.get("mode")) or "none",
        },
        "focus": focus,
        "claim_readiness": claim_readiness,
        "available_commands": PUBLIC_DECISION_ACTIONS,
        "decision_constraints": build_decision_constraints(
            phase=phase,
            focus=focus,
            endpoint_evidence_blockers=endpoint_evidence_blockers,
            required_backtrack_events=required_backtrack_events,
            pathway_attention=pathway_attention,
        ),
        "context_policy": {
            "mode": "alternative_mechanism_context" if alternative_mechanism else "structured_priority_context",
            "retrieval_mode": "ranked_workspace_artifacts",
            "ranking_keys": [
                "priority",
                "focus",
                "endpoint_evidence_blocker",
                "failed_branch_lesson",
                "accepted_node",
                "mechanism_memory",
            ],
            "raw_excerpt_policy": "include parsed summaries and reflections first; read raw logs only when exact program or chemistry evidence is needed",
            "parent_rule": "decision payloads may use focus.parent_for_new_branch when the model chooses a new branch from active backtrack context",
            "reframe_rule": "rejected or wrong-mode TS/Freq nodes stay historical; reuse them only through input_refs on a new node with a new intended reaction boundary",
            "pathway_rule": "accepted_ts remains an elementary-step claim; pathway completion is derived only when every required pathway step is bound to an accepted_ts node",
        },
        "context_items": build_context_items(
            source=source,
            phase=phase,
            focus=focus,
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
        "validated_facts": list_or_empty(mechanism.get("validated_facts"))[:12],
        "refuted_hypotheses": list_or_empty(mechanism.get("refuted_hypotheses"))[:12],
        "open_questions": list_or_empty(mechanism.get("open_questions"))[:12],
        "evidence_summary": summarize_evidence(snapshot.evidence),
        "endpoint_evidence_blockers": endpoint_evidence_blockers[:8],
        "reframe_candidates": reframe_candidates[:8],
        "backtrack_events": backtrack_events[:8],
        "failed_or_ambiguous_branches": failed_nodes[:8],
        "required_backtrack_events": required_backtrack_events[:8],
        "required_reframe_checks": required_reframe_checks[:8],
        "required_finalization_checks": required_finalization_checks[:8],
    }
    return packet


__all__ = ["build_workspace_report_packet"]


def build_decision_constraints(
    *,
    phase: str,
    focus: dict[str, Any],
    endpoint_evidence_blockers: list[dict[str, Any]],
    required_backtrack_events: list[dict[str, Any]],
    pathway_attention: dict[str, Any],
) -> dict[str, Any]:
    """Return neutral claim checks without route or command suggestions."""

    required_checks = [
        "read focus and justify any parent_for_new_branch use before creating a new node",
        "write an agent-owned decision_card with explicit decision_provenance before execution",
        "keep claim ceiling at the next evidence layer unless parsed evidence supports promotion",
    ]
    if endpoint_evidence_blockers:
        required_checks.append("treat endpoint_evidence_blockers as invalid endpoint evidence, not repair instructions")
    if required_backtrack_events:
        required_checks.append("record canonical backtrack_events before opening replacement branches")
    if pathway_attention.get("mode") in {"start", "continue"}:
        required_checks.append("scope any new decision to the reported pathway_id and step_id")
    return {
        "phase": phase,
        "focus_mode": clean_string(focus.get("mode")),
        "parent_for_new_branch": clean_string(focus.get("parent_for_new_branch")),
        "required_checks": required_checks,
        "available_commands": PUBLIC_DECISION_ACTIONS,
        "agent_owns": [
            "chemical hypothesis",
            "parent selection reason",
            "search strategy and level/backend choice",
            "changed variables",
            "support and refutation criteria",
            "cost/risk decision",
        ],
        "validator_owns": [
            "workspace structure",
            "decision provenance completeness",
            "evidence gate consistency",
            "backtrack event linkage",
            "accepted_ts claim gates",
        ],
    }
