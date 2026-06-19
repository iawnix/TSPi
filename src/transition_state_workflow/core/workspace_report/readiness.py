"""Claim-readiness diagnostics for workspace reports."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.util.path_utils import clean_string

from .ids import node_sort_key


PUBLIC_DECISION_ACTIONS = ["start_node", "end_node", "ask_user", "stop"]


def build_claim_readiness(
    *,
    validation_errors: list[dict[str, Any]],
    active_nodes: list[dict[str, Any]],
    endpoint_nodes: list[tuple[str, dict[str, Any]]],
    candidate_nodes: list[tuple[str, dict[str, Any]]],
    tsfreq_nodes: list[tuple[str, dict[str, Any]]],
    connectivity_nodes: list[tuple[str, dict[str, Any]]],
    accepted_nodes: list[tuple[str, dict[str, Any]]],
    manifest: dict[str, Any],
    endpoint_evidence_blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return evidence-readiness diagnostics without route suggestions."""

    endpoint_ids = _node_ids(endpoint_nodes)
    candidate_ids = _node_ids(candidate_nodes)
    tsfreq_ids = _node_ids(tsfreq_nodes)
    connectivity_ids = _node_ids(connectivity_nodes)
    accepted_ids = _node_ids(accepted_nodes)
    current_accepted_ts = clean_string(manifest.get("current_accepted_ts"))
    if current_accepted_ts and current_accepted_ts not in accepted_ids:
        accepted_ids.append(current_accepted_ts)

    accepted_missing = []
    if not tsfreq_ids:
        accepted_missing.append("tsfreq")
    if not connectivity_ids:
        accepted_missing.append("connectivity")

    return {
        "workspace": {
            "status": "invalid" if validation_errors else ("active_work" if active_nodes else "valid"),
            "missing_evidence": ["workspace_validation_errors"] if validation_errors else [],
            "supporting_nodes": [],
            "diagnostics": _workspace_diagnostics(validation_errors, active_nodes),
        },
        "endpoint_minima": {
            "status": "supported" if endpoint_ids and not endpoint_evidence_blockers else "missing",
            "supporting_nodes": endpoint_ids,
            "missing_evidence": [] if endpoint_ids and not endpoint_evidence_blockers else ["endpoint_minima"],
            "diagnostics": endpoint_evidence_blockers[:8],
        },
        "candidate": {
            "status": "supported" if candidate_ids else "missing",
            "supporting_nodes": candidate_ids,
            "missing_evidence": [] if candidate_ids else ["candidate"],
            "diagnostics": [],
        },
        "tsfreq": {
            "status": "supported" if tsfreq_ids else "missing",
            "supporting_nodes": tsfreq_ids,
            "missing_evidence": [] if tsfreq_ids else ["tsfreq"],
            "diagnostics": [],
        },
        "connectivity": {
            "status": "supported" if connectivity_ids else "missing",
            "supporting_nodes": connectivity_ids,
            "missing_evidence": [] if connectivity_ids else ["connectivity"],
            "diagnostics": [],
        },
        "accepted_ts": {
            "status": _accepted_status(accepted_ids, accepted_missing),
            "supporting_nodes": accepted_ids,
            "missing_evidence": accepted_missing,
            "diagnostics": [],
        },
    }


def current_phase_reasons(
    *,
    phase: str,
    claim_readiness: dict[str, Any],
    focus: dict[str, Any],
) -> list[str]:
    """Explain the attention anchor without prescribing the next route."""

    reasons: list[str] = []
    focus_reason = clean_string(focus.get("reason"))
    if focus_reason:
        reasons.append(focus_reason)
    if phase == "workspace_repair_required":
        reasons.append("Workspace validation diagnostics need attention before scientific claim promotion.")
    elif phase == "active_work_running":
        reasons.append("An open node exists; inspect or close active work before treating outputs as evidence.")
    elif phase == "endpoint_discovery":
        reasons.append("Endpoint-minima readiness is not yet supported by structured evidence.")
    elif phase == "candidate_generation":
        reasons.append("Endpoint evidence is present but no candidate claim is supported yet.")
    elif phase == "gaussian_tsfreq_validation":
        reasons.append("A candidate exists but TS/Freq readiness is not supported yet.")
    elif phase == "connectivity_validation":
        reasons.append("TS/Freq evidence exists but endpoint or IRC connectivity is not supported yet.")
    elif phase == "accepted_ts_ready":
        reasons.append("TS/Freq and connectivity evidence are both present; accepted-TS promotion can be audited.")
    elif phase == "accepted_ts_present":
        reasons.append("An accepted TS is already recorded; further work needs an audit or distinct mechanism rationale.")
    else:
        reasons.append(f"Attention is scoped to {phase}.")
    accepted = claim_readiness.get("accepted_ts") if isinstance(claim_readiness.get("accepted_ts"), dict) else {}
    missing = [clean_string(item) for item in accepted.get("missing_evidence", []) if clean_string(item)]
    if missing:
        reasons.append("accepted_ts is not ready because these gates are missing: " + ", ".join(missing))
    return _unique(reasons)


def current_phase_scope(phase: str) -> dict[str, Any]:
    """Return the public meaning of ``current_phase``."""

    return {
        "role": "attention_anchor",
        "phase": phase,
        "not_a_route_decision": True,
        "model_may_choose_any_public_command": True,
        "claim_promotion_requires": "supporting claim_readiness evidence plus validator acceptance",
    }


def _accepted_status(accepted_ids: list[str], missing: list[str]) -> str:
    if accepted_ids:
        return "present"
    return "ready" if not missing else "not_ready"


def _node_ids(nodes: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [node_id for node_id, _ in sorted(nodes, key=lambda item: node_sort_key(item[0]))]


def _workspace_diagnostics(
    validation_errors: list[dict[str, Any]],
    active_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    diagnostics.extend(validation_errors[:8])
    diagnostics.extend(active_nodes[:8])
    return diagnostics


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "PUBLIC_DECISION_ACTIONS",
    "build_claim_readiness",
    "current_phase_reasons",
    "current_phase_scope",
]
