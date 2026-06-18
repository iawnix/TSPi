"""Read-only workspace snapshots for ChemKernel workspace report packets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transition_state_workflow.base.evidence_gates import accepted_ts_evidence_gate_hits
from transition_state_workflow.base.pathway_model import read_pathway_model_optional, summarize_pathway_model
from transition_state_workflow.util.json_io import read_json_object_optional, read_json_object_required
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .context import (
    backtrack_event_summaries,
    evidence_records_from_registry,
    failed_or_ambiguous_node_summaries,
    reframe_candidate_summaries,
    summarize_node,
)
from .contracts import TsfreqEvidencePredicate, WorkspaceValidator
from .diagnostics import endpoint_evidence_blocker_summaries
from .ids import node_sort_key
from .loader import active_node_summaries, ensure_plan_workspace, load_node_payloads, nodes_with_claim


@dataclass(frozen=True)
class NodeClaimSnapshot:
    """Node groups derived from read-only claim and lifecycle fields."""

    node_payloads: dict[str, dict[str, Any]]
    prepared_nodes: list[dict[str, Any]]
    endpoint_nodes: list[tuple[str, dict[str, Any]]]
    candidate_nodes: list[tuple[str, dict[str, Any]]]
    tsfreq_nodes: list[tuple[str, dict[str, Any]]]
    connectivity_nodes: list[tuple[str, dict[str, Any]]]
    accepted_nodes: list[tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class PlanNextSnapshot:
    """Read-only workspace state used by the report-context orchestrator."""

    source: Path
    manifest: dict[str, Any]
    tree: dict[str, Any]
    evidence: dict[str, Any]
    mechanism: dict[str, Any]
    pathway: dict[str, Any]
    pathway_summary: dict[str, Any]
    node_payloads: dict[str, dict[str, Any]]
    validation: dict[str, Any]
    validation_errors: list[dict[str, Any]]
    active_nodes: list[dict[str, Any]]
    failed_nodes: list[dict[str, Any]]
    backtrack_events: list[dict[str, Any]]
    evidence_records: list[dict[str, Any]]
    reframe_candidates: list[dict[str, Any]]
    endpoint_evidence_blockers: list[dict[str, Any]]
    claims: NodeClaimSnapshot


def classify_node_claims(
    node_payloads: dict[str, dict[str, Any]],
    *,
    source: Path | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
) -> NodeClaimSnapshot:
    """Group nodes by claim fields without applying planning policy."""

    gate_hits_by_node = evidence_gate_hits_by_node(source, evidence_records or [])
    prepared_nodes = [
        summarize_node(node_id, node)
        for node_id, node in sorted(node_payloads.items(), key=lambda item: node_sort_key(item[0]))
        if clean_string(node.get("lifecycle_state")) == "prepared"
    ]
    tsfreq_nodes = [
        (node_id, node)
        for node_id, node in node_payloads.items()
        if clean_string(node.get("claim_status")) == "tsfreq_validated"
        and "tsfreq" in gate_hits_by_node.get(node_id, set())
    ]
    connectivity_nodes = [
        (node_id, node)
        for node_id, node in node_payloads.items()
        if clean_string(node.get("claim_status")) in {"endpoint_connected", "irc_connected"}
        and "connectivity" in gate_hits_by_node.get(node_id, set())
    ]
    return NodeClaimSnapshot(
        node_payloads=node_payloads,
        prepared_nodes=prepared_nodes,
        endpoint_nodes=nodes_with_claim(node_payloads, "endpoint_minima_ready"),
        candidate_nodes=nodes_with_claim(node_payloads, "candidate_found"),
        tsfreq_nodes=tsfreq_nodes,
        connectivity_nodes=connectivity_nodes,
        accepted_nodes=nodes_with_claim(node_payloads, "accepted_ts"),
    )


def load_plan_next_snapshot(
    root: Path,
    *,
    validate_workspace: WorkspaceValidator,
    supports_tsfreq_evidence: TsfreqEvidencePredicate,
) -> PlanNextSnapshot:
    """Load all read-only workspace state required for decision context."""

    source = root.expanduser().resolve()
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
    failed_nodes = failed_or_ambiguous_node_summaries(source, node_payloads)
    backtrack_events = backtrack_event_summaries(tree)
    evidence_records = evidence_records_from_registry(evidence)
    reframe_candidates = reframe_candidate_summaries(
        source=source,
        node_payloads=node_payloads,
        evidence_records=evidence_records,
        supports_tsfreq_evidence=supports_tsfreq_evidence,
    )
    endpoint_evidence_blockers = endpoint_evidence_blocker_summaries(
        source,
        node_payloads,
        evidence_records,
    )
    validation_errors = [
        item for item in list_or_empty(validation.get("findings")) if clean_string(item.get("severity")) == "error"
    ]

    return PlanNextSnapshot(
        source=source,
        manifest=manifest,
        tree=tree,
        evidence=evidence,
        mechanism=mechanism,
        pathway=pathway,
        pathway_summary=pathway_summary,
        node_payloads=node_payloads,
        validation=validation,
        validation_errors=validation_errors,
        active_nodes=active_nodes,
        failed_nodes=failed_nodes,
        backtrack_events=backtrack_events,
        evidence_records=evidence_records,
        reframe_candidates=reframe_candidates,
        endpoint_evidence_blockers=endpoint_evidence_blockers,
        claims=classify_node_claims(
            node_payloads,
            source=source,
            evidence_records=evidence_records,
        ),
    )


def evidence_gate_hits_by_node(
    source: Path | None,
    evidence_records: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Return accepted-TS gate hits keyed by evidence node id."""

    if source is None:
        return {}
    records_by_node: dict[str, list[dict[str, Any]]] = {}
    for record in evidence_records:
        node_id = clean_string(record.get("node_id"))
        if node_id:
            records_by_node.setdefault(node_id, []).append(record)
    return {
        node_id: accepted_ts_evidence_gate_hits(source, records)
        for node_id, records in records_by_node.items()
    }


__all__ = [
    "NodeClaimSnapshot",
    "PlanNextSnapshot",
    "classify_node_claims",
    "evidence_gate_hits_by_node",
    "load_plan_next_snapshot",
]
