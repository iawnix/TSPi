"""Context extraction and ranking for ChemKernel next-action planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .contracts import TsfreqEvidencePredicate
from .ids import node_sort_key


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
    supports_tsfreq_evidence: TsfreqEvidencePredicate,
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
            if supports_tsfreq_evidence(source, record)
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

    from .suggestions import lineage_to_root

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
            items.append(
                node_context_item(
                    lineage_node,
                    node_payloads,
                    priority=priority,
                    kind="focus_lineage",
                    reason=f"Lineage node {index + 1} leading to planning focus.",
                )
            )
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
            items.append(
                node_context_item(
                    node_id,
                    node_payloads,
                    priority="must",
                    kind="accepted_node",
                    reason="Accepted claims must remain visible during audit or alternative-branch planning.",
                )
            )
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


__all__ = [
    "summarize_node",
    "failed_or_ambiguous_node_summaries",
    "evidence_records_from_registry",
    "reframe_candidate_summaries",
    "summarize_reframe_tsfreq_record",
    "backtrack_event_summaries",
    "build_context_items",
    "rank_context_items",
    "node_context_item",
    "failed_branch_context_item",
    "failed_summary_by_id",
    "jsonish_compact",
    "read_reflection_brief",
    "first_section_line",
    "summarize_evidence",
]
