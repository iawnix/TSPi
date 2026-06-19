"""ChemKernel workspace report context packets.

This package owns read-only workspace summarization for ``report_workspace``.
Route, method, and command choice stay with the model decision validated by the
public control plane.
"""

from __future__ import annotations

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
from .contracts import WORKSPACE_REPORT_PACKET_SCHEMA, TsfreqEvidencePredicate, WorkspaceValidator
from .diagnostics import endpoint_evidence_blocker_summaries
from .ids import latest_node_id, node_number, node_sort_key
from .loader import (
    active_node_summaries,
    conservative_workspace_validation,
    ensure_report_workspace,
    load_node_payloads,
    no_tsfreq_evidence_support,
    nodes_with_claim,
)
from .packet import build_workspace_report_packet
from .pathway import (
    filter_nodes_for_pathway_step,
    infer_pathway_attention,
    latest_pathway_status_node,
    pathway_target_for_suggestions,
)
from .readiness import (
    PUBLIC_DECISION_ACTIONS,
    build_claim_readiness,
    current_phase_reasons,
    current_phase_scope,
)
from .phase import (
    default_focus_node_for_phase,
    infer_attention_phase,
    infer_phase_from_focus_node,
    infer_report_focus,
)
from .snapshot import NodeClaimSnapshot, WorkspaceReportSnapshot, classify_node_claims, load_workspace_report_snapshot
from .suggestions import (
    backtrack_reason_from_failed_summary,
    candidate_backtrack_targets,
    lineage_to_root,
    suggest_backtrack_actions,
    suggest_finalization_actions,
    suggest_reframe_actions,
)


__all__ = [
    "WORKSPACE_REPORT_PACKET_SCHEMA",
    "WorkspaceValidator",
    "TsfreqEvidencePredicate",
    "endpoint_evidence_blocker_summaries",
    "build_workspace_report_packet",
    "ensure_report_workspace",
    "conservative_workspace_validation",
    "no_tsfreq_evidence_support",
    "load_node_payloads",
    "active_node_summaries",
    "nodes_with_claim",
    "NodeClaimSnapshot",
    "WorkspaceReportSnapshot",
    "classify_node_claims",
    "load_workspace_report_snapshot",
    "infer_pathway_attention",
    "filter_nodes_for_pathway_step",
    "infer_attention_phase",
    "PUBLIC_DECISION_ACTIONS",
    "build_claim_readiness",
    "current_phase_reasons",
    "current_phase_scope",
    "infer_phase_from_focus_node",
    "infer_report_focus",
    "default_focus_node_for_phase",
    "latest_pathway_status_node",
    "pathway_target_for_suggestions",
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
    "node_sort_key",
    "node_number",
]
