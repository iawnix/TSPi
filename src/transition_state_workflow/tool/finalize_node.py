"""Finalize completed TS-search nodes across v2 workspace artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import (
    DEFAULT_OUTCOME_BY_CLAIM_STATUS,
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    VALID_CLAIM_STATUSES,
    VALID_EVIDENCE_STATES,
    VALID_LIFECYCLE_STATES,
    MECHANISM_ANALYSIS_LAYERS,
    MECHANISM_ANALYSIS_STATUSES,
    VALID_OUTCOMES,
    VALID_RUN_STATES,
    derive_claim_level,
    valid_outcomes_for_claim_status,
)
from transition_state_workflow.tool.evidence_gates import accepted_ts_missing_evidence_gates
from transition_state_workflow.tool.pathway_model import (
    bind_pathway_step_to_accepted_ts,
    mark_pathway_step_status,
    validate_pathway_step_reference,
)
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import (
    clean_string,
    portable_record_path,
    relative_path_or_absolute,
    safe_identifier_token,
)


@dataclass(frozen=True)
class EvidenceSpec:
    """Structured evidence record requested by the finalization caller."""

    kind: str
    path: str
    claim: str
    evidence_state: str
    evidence_id: str = ""
    node_evidence_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MechanismAnalysisSpec:
    """Structured mechanism-analysis observation for one finalized node."""

    layer: str
    status: str
    summary: str
    source: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReflectionSpec:
    """Structured post-execution reflection text for one finalized node."""

    computational_outcome: str
    mechanistic_implication: str
    knowledge_updates: tuple[str, ...] = ()
    next_branch: str = ""


@dataclass(frozen=True)
class KnowledgeUpdateSpec:
    """Optional append-only knowledge-base and mechanism-model updates."""

    facts: tuple[str, ...] = ()
    refutations: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    next_decision: str = ""
    mechanism_facts: tuple[str, ...] = ()
    mechanism_refutations: tuple[str, ...] = ()
    mechanism_open_questions: tuple[str, ...] = ()
    tool_implications: tuple[str, ...] = ()
    mechanism_analysis: tuple[MechanismAnalysisSpec, ...] = ()


@dataclass(frozen=True)
class NodeFinalizationRequest:
    """All caller-supplied state needed to finalize a node."""

    root: Path
    node_id: str
    claim_status: str
    outcome: str
    decision: str
    summary: str
    primary_file: str
    outcome_code: str | None = None
    pathway_id: str = ""
    step_id: str = ""
    pathway_step_status: str = ""
    lifecycle_state: str = "closed"
    run_state: str = "completed"
    badges: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceSpec, ...] = ()
    reflection: ReflectionSpec = field(
        default_factory=lambda: ReflectionSpec(
            computational_outcome="Not specified.",
            mechanistic_implication="Not specified.",
            next_branch="Not specified.",
        )
    )
    knowledge: KnowledgeUpdateSpec = field(default_factory=KnowledgeUpdateSpec)


def register_finalize_node_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the finalize-node subcommand to an existing argparse parser."""

    finalize = subparsers.add_parser("finalize-node", help="Finalize one completed v2 node.")
    finalize.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    finalize.add_argument("--node-id", required=True, help="Node id under nodes/.")
    finalize.add_argument("--claim-status", required=True, choices=sorted(VALID_CLAIM_STATUSES))
    finalize.add_argument(
        "--outcome",
        choices=sorted(VALID_OUTCOMES),
        default="",
        help=(
            "Outcome classification. Optional for successful claim statuses (derived "
            "automatically); required for rejected/ambiguous nodes to say what failed."
        ),
    )
    finalize.add_argument("--outcome-code", default=None)
    finalize.add_argument("--lifecycle-state", choices=sorted(VALID_LIFECYCLE_STATES), default="closed")
    finalize.add_argument("--run-state", choices=sorted(VALID_RUN_STATES), default="completed")
    finalize.add_argument("--decision", required=True, help="Next decision/action token.")
    finalize.add_argument("--summary", required=True, help="User-facing node summary.")
    finalize.add_argument("--primary-file", required=True, help="Primary evidence file path.")
    finalize.add_argument("--pathway-id", default="", help="Optional pathway id for multi-step aggregation.")
    finalize.add_argument("--step-id", default="", help="Optional elementary step id within --pathway-id.")
    finalize.add_argument(
        "--pathway-step-status",
        choices=("candidate", "ambiguous", "rejected"),
        default="",
        help=(
            "Explicitly mark the current pathway step as candidate, ambiguous, or rejected. "
            "Use only when this node updates the elementary-step conclusion, not for an ordinary failed branch."
        ),
    )
    finalize.add_argument("--badge", action="append", default=[], help="Display badge; may be repeated.")
    finalize.add_argument(
        "--metric",
        action="append",
        default=[],
        help="Display metric as key=value; may be repeated.",
    )
    finalize.add_argument(
        "--evidence",
        action="append",
        default=[],
        help=(
            "Evidence JSON object with kind,path,claim,evidence_state and optional "
            "evidence_id,node_evidence_key; may be repeated."
        ),
    )
    finalize.add_argument("--computational-outcome", required=True)
    finalize.add_argument("--mechanistic-implication", required=True)
    finalize.add_argument("--knowledge-update", action="append", default=[])
    finalize.add_argument("--next-branch", required=True)
    finalize.add_argument("--knowledge-fact", action="append", default=[])
    finalize.add_argument("--knowledge-refutation", action="append", default=[])
    finalize.add_argument("--open-question", action="append", default=[])
    finalize.add_argument("--next-decision", default="")
    finalize.add_argument("--mechanism-fact", action="append", default=[])
    finalize.add_argument("--mechanism-refutation", action="append", default=[])
    finalize.add_argument("--mechanism-open-question", action="append", default=[])
    finalize.add_argument("--tool-implication", action="append", default=[])
    finalize.add_argument(
        "--mechanism-analysis",
        action="append",
        default=[],
        help=(
            "Mechanism-analysis JSON object with layer,status,summary and optional "
            "source,metrics,details; may be repeated."
        ),
    )


def finalize_ts_workspace_node_from_cli_args(args: argparse.Namespace) -> None:
    """Build a finalization request from argparse values and execute it."""

    user_outcome = clean_string(args.outcome)
    derived_outcome = DEFAULT_OUTCOME_BY_CLAIM_STATUS.get(args.claim_status, "")
    valid_outcomes = valid_outcomes_for_claim_status(args.claim_status)
    if user_outcome and valid_outcomes and user_outcome not in valid_outcomes:
        if derived_outcome and user_outcome != derived_outcome:
            raise SystemExit(
                f"--outcome must not override derived outcome for claim_status={args.claim_status}: "
                f"expected {derived_outcome}, got {user_outcome}"
            )
        raise SystemExit(
            f"outcome {user_outcome} is not valid for claim_status={args.claim_status}; "
            f"valid outcomes: {', '.join(sorted(valid_outcomes))}"
        )
    outcome = user_outcome or derived_outcome
    if not outcome:
        raise SystemExit(
            f"--outcome is required for claim_status={args.claim_status}: "
            "say what failed (e.g. chemical_failure, numerical_failure, wrong_mode)"
        )
    request = NodeFinalizationRequest(
        root=args.root,
        node_id=args.node_id,
        claim_status=args.claim_status,
        outcome=outcome,
        outcome_code=args.outcome_code,
        lifecycle_state=args.lifecycle_state,
        run_state=args.run_state,
        decision=args.decision,
        summary=args.summary,
        primary_file=args.primary_file,
        pathway_id=clean_string(args.pathway_id),
        step_id=clean_string(args.step_id),
        pathway_step_status=clean_string(args.pathway_step_status),
        badges=tuple(args.badge or ()),
        metrics=parse_metric_specs(args.metric or ()),
        evidence=tuple(parse_evidence_spec(item) for item in (args.evidence or ())),
        reflection=ReflectionSpec(
            computational_outcome=args.computational_outcome,
            mechanistic_implication=args.mechanistic_implication,
            knowledge_updates=tuple(args.knowledge_update or ()),
            next_branch=args.next_branch,
        ),
        knowledge=KnowledgeUpdateSpec(
            facts=tuple(args.knowledge_fact or ()),
            refutations=tuple(args.knowledge_refutation or ()),
            open_questions=tuple(args.open_question or ()),
            next_decision=args.next_decision,
            mechanism_facts=tuple(args.mechanism_fact or ()),
            mechanism_refutations=tuple(args.mechanism_refutation or ()),
            mechanism_open_questions=tuple(args.mechanism_open_question or ()),
            tool_implications=tuple(args.tool_implication or ()),
            mechanism_analysis=tuple(parse_mechanism_analysis_spec(item) for item in (args.mechanism_analysis or ())),
        ),
    )
    finalize_ts_workspace_node(request)


def finalize_ts_workspace_node(request: NodeFinalizationRequest) -> None:
    """Finalize one node across node, tree, evidence, reflection, and model files."""

    root = request.root.expanduser().resolve()
    validate_finalization_request(request)
    ensure_workspace_root(root)
    node_dir = root / "nodes" / request.node_id
    node_path = node_dir / "node.json"
    if not node_path.exists():
        raise SystemExit(f"node does not exist: {request.node_id}")

    now = utc_timestamp()
    node_payload = read_json_object_required(node_path)
    tree_payload = read_json_object_required(root / "tree.json")
    registry_payload = read_json_object_required(root / "evidence_registry.json")
    manifest_payload = read_json_object_required(root / "manifest.json")
    validate_pathway_request(root=root, request=request)
    validate_candidate_endpoint_gate(
        root=root,
        node_id=request.node_id,
        claim_status=request.claim_status,
        pathway_id=request.pathway_id,
        step_id=request.step_id,
        node_payload=node_payload,
        tree_payload=tree_payload,
    )

    new_records, node_evidence_updates, evidence_ids = build_evidence_records(
        root=root,
        node_id=request.node_id,
        existing_registry=registry_payload,
        evidence_specs=request.evidence,
        created_at=now,
    )
    validate_accepted_ts_evidence_gates(
        node_id=request.node_id,
        claim_status=request.claim_status,
        root=root,
        existing_registry=registry_payload,
        new_records=new_records,
    )

    update_node_payload(
        root=root,
        node_dir=node_dir,
        node_payload=node_payload,
        request=request,
        node_evidence_updates=node_evidence_updates,
    )
    update_tree_payload(
        tree_payload=tree_payload,
        request=request,
        evidence_ids=evidence_ids,
        timestamp=now,
    )
    update_evidence_registry(registry_payload, new_records, timestamp=now)
    update_manifest(manifest_payload, request)

    write_reflection(node_dir / "reflection.md", request.reflection)
    append_knowledge_base(root / "knowledge_base.md", request, evidence_ids, timestamp=now)
    update_mechanism_model(root / "mechanism_model.json", request, evidence_ids, timestamp=now)

    write_json_object(node_path, node_payload, overwrite_existing=True)
    write_json_object(root / "tree.json", tree_payload, overwrite_existing=True)
    write_json_object(root / "evidence_registry.json", registry_payload, overwrite_existing=True)
    write_json_object(root / "manifest.json", manifest_payload, overwrite_existing=True)
    if request.claim_status == "accepted_ts" and request.pathway_id:
        bind_pathway_step_to_accepted_ts(
            root=root,
            pathway_id=request.pathway_id,
            step_id=request.step_id,
            node_id=request.node_id,
            timestamp=now,
            require_node_claim=False,
        )
    elif request.pathway_step_status:
        mark_pathway_step_status(
            root=root,
            pathway_id=request.pathway_id,
            step_id=request.step_id,
            status=request.pathway_step_status,
            node_id=request.node_id,
            evidence_refs=evidence_ids,
            timestamp=now,
        )


def validate_finalization_request(request: NodeFinalizationRequest) -> None:
    """Fail early when requested state combinations contradict the v2 contract."""

    if request.claim_status not in VALID_CLAIM_STATUSES:
        raise SystemExit(f"invalid claim_status: {request.claim_status}")
    if request.outcome not in VALID_OUTCOMES:
        raise SystemExit(f"invalid outcome: {request.outcome}")
    valid_outcomes = valid_outcomes_for_claim_status(request.claim_status)
    if valid_outcomes and request.outcome not in valid_outcomes:
        raise SystemExit(
            f"outcome {request.outcome} is not valid for claim_status={request.claim_status}; "
            f"valid outcomes: {', '.join(sorted(valid_outcomes))}"
        )
    if request.lifecycle_state not in VALID_LIFECYCLE_STATES:
        raise SystemExit(f"invalid lifecycle_state: {request.lifecycle_state}")
    if request.run_state not in VALID_RUN_STATES:
        raise SystemExit(f"invalid run_state: {request.run_state}")
    if request.claim_status != "not_evaluated" and not request.evidence:
        raise SystemExit("finalized evaluated nodes require at least one --evidence record")
    if bool(request.pathway_id) != bool(request.step_id):
        raise SystemExit("--pathway-id and --step-id must be provided together")
    if request.pathway_step_status and not request.pathway_id:
        raise SystemExit("--pathway-step-status requires --pathway-id and --step-id")
    if request.pathway_step_status == "candidate" and request.claim_status not in {
        "candidate_found",
        "tsfreq_validated",
        "irc_raw_completed",
        "endpoint_connected",
        "irc_connected",
    }:
        raise SystemExit("--pathway-step-status candidate requires a candidate or validation-layer claim")
    if request.pathway_step_status in {"ambiguous", "rejected"} and request.claim_status != request.pathway_step_status:
        raise SystemExit(
            f"--pathway-step-status {request.pathway_step_status} requires "
            f"claim_status={request.pathway_step_status}"
        )
    if request.knowledge.mechanism_analysis and not request.evidence:
        missing_source_layers = [item.layer for item in request.knowledge.mechanism_analysis if not item.source]
        if missing_source_layers:
            raise SystemExit(
                "--mechanism-analysis requires either same-finalization --evidence records "
                "or per-record source fields; missing source for layers: "
                + ", ".join(missing_source_layers)
            )


def validate_pathway_request(*, root: Path, request: NodeFinalizationRequest) -> None:
    """Validate optional pathway metadata before writing finalization artifacts."""

    if not request.pathway_id:
        return
    validate_pathway_step_reference(root, request.pathway_id, request.step_id)


def validate_candidate_endpoint_gate(
    *,
    root: Path,
    node_id: str,
    claim_status: str,
    pathway_id: str,
    step_id: str,
    node_payload: dict[str, Any],
    tree_payload: dict[str, Any],
) -> None:
    """Reject candidate promotion unless endpoint readiness is upstream."""

    if claim_status != "candidate_found":
        return
    target_pathway_id = clean_string(pathway_id) or clean_string(node_payload.get("pathway_id"))
    target_step_id = clean_string(step_id) or clean_string(node_payload.get("elementary_step_id"))
    if bool(target_pathway_id) != bool(target_step_id):
        raise SystemExit("pathway-scoped candidate requires both pathway_id and elementary_step_id")
    tree_nodes = tree_payload.get("nodes") if isinstance(tree_payload.get("nodes"), dict) else {}
    parent_by_node: dict[str, str] = {}
    input_refs_by_node: dict[str, list[str]] = {}
    for current_id, entry in tree_nodes.items():
        entry_payload = entry if isinstance(entry, dict) else {}
        current_node_path = root / "nodes" / str(current_id) / "node.json"
        current_node = read_json_object_required(current_node_path) if current_node_path.exists() else {}
        parent_by_node[str(current_id)] = clean_string(entry_payload.get("parent_id")) or clean_string(current_node.get("parent_id"))
        refs = []
        for raw in list(entry_payload.get("input_refs") or []) + list(current_node.get("input_refs") or []):
            ref = clean_string(raw)
            if ref and ref not in refs:
                refs.append(ref)
        input_refs_by_node[str(current_id)] = refs
    if node_id not in parent_by_node:
        parent_by_node[node_id] = clean_string(node_payload.get("parent_id"))
    if node_id not in input_refs_by_node:
        input_refs_by_node[node_id] = [clean_string(raw) for raw in list(node_payload.get("input_refs") or []) if clean_string(raw)]

    seen = {node_id}
    stack = [parent_by_node.get(node_id, ""), *input_refs_by_node.get(node_id, [])]
    while stack:
        upstream_id = clean_string(stack.pop())
        if not upstream_id or upstream_id in seen:
            continue
        seen.add(upstream_id)
        upstream_path = root / "nodes" / upstream_id / "node.json"
        upstream = read_json_object_required(upstream_path) if upstream_path.exists() else {}
        if clean_string(upstream.get("claim_status")) == "endpoint_minima_ready":
            if target_pathway_id:
                if (
                    clean_string(upstream.get("pathway_id")) == target_pathway_id
                    and clean_string(upstream.get("elementary_step_id")) == target_step_id
                ):
                    return
                continue
            return
        stack.append(parent_by_node.get(upstream_id, ""))
        stack.extend(input_refs_by_node.get(upstream_id, []))
    suffix = " in the same pathway step" if target_pathway_id else ""
    raise SystemExit(
        "candidate_found requires an upstream or dependency node with "
        f"claim_status=endpoint_minima_ready{suffix}"
    )


def validate_accepted_ts_evidence_gates(
    *,
    root: Path,
    node_id: str,
    claim_status: str,
    existing_registry: dict[str, Any],
    new_records: list[dict[str, Any]],
) -> None:
    """Require TS/Freq and connectivity evidence before accepting a TS."""

    if claim_status != "accepted_ts":
        return
    existing_records = [
        item
        for item in existing_registry.get("records", [])
        if isinstance(item, dict) and clean_string(item.get("node_id")) == node_id
    ]
    missing = accepted_ts_missing_evidence_gates(root, existing_records + new_records)
    if missing:
        raise SystemExit(
            "accepted_ts requires supporting TS/Freq and connectivity evidence "
            f"for this node; missing gates: {', '.join(missing)}"
        )


def ensure_workspace_root(root: Path) -> None:
    """Ensure root has the v2 files required for finalization."""

    required = ("manifest.json", "tree.json", "evidence_registry.json", "nodes")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise SystemExit(f"not a TS-search workspace, missing: {', '.join(missing)}")
    tree = read_json_object_required(root / "tree.json")
    registry = read_json_object_required(root / "evidence_registry.json")
    if clean_string(tree.get("schema")) != TREE_SCHEMA:
        raise SystemExit("tree.json must declare schema=tssearch-branching-tree-v2")
    if clean_string(registry.get("schema")) != EVIDENCE_REGISTRY_SCHEMA:
        raise SystemExit("evidence_registry.json must declare schema=tssearch-evidence-registry-v2")


def parse_metric_specs(raw_specs: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Parse repeated key=value metric specifications."""

    metrics: dict[str, Any] = {}
    for raw in raw_specs:
        if "=" not in raw:
            raise SystemExit(f"metric must be key=value, got {raw!r}")
        key, value = raw.split("=", 1)
        key = clean_string(key)
        if not key:
            raise SystemExit(f"metric key is empty in {raw!r}")
        metrics[key] = parse_scalar(value)
    return metrics


def parse_scalar(raw_value: str) -> Any:
    """Parse simple CLI scalar text into bool/number/string."""

    text = clean_string(raw_value)
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        if any(character in text for character in ".eE"):
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_evidence_spec(raw_spec: str) -> EvidenceSpec:
    """Parse an evidence JSON object from the CLI."""

    try:
        payload = json.loads(raw_spec)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--evidence must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--evidence must be a JSON object")
    evidence_state = clean_string(payload.get("evidence_state") or payload.get("state"))
    spec = EvidenceSpec(
        kind=clean_string(payload.get("kind")),
        path=clean_string(payload.get("path")),
        claim=clean_string(payload.get("claim")),
        evidence_state=evidence_state,
        evidence_id=clean_string(payload.get("evidence_id")),
        node_evidence_key=clean_string(payload.get("node_evidence_key")),
        metadata={
            str(key): value
            for key, value in payload.items()
            if key
            not in {
                "kind",
                "path",
                "claim",
                "evidence_state",
                "state",
                "evidence_id",
                "node_evidence_key",
            }
        },
    )
    missing = [name for name in ("kind", "path", "claim", "evidence_state") if not clean_string(getattr(spec, name))]
    if missing:
        raise SystemExit(f"--evidence missing required fields: {', '.join(missing)}")
    if spec.evidence_state not in VALID_EVIDENCE_STATES:
        raise SystemExit(f"invalid evidence_state: {spec.evidence_state}")
    return spec


def parse_mechanism_analysis_spec(raw_spec: str) -> MechanismAnalysisSpec:
    """Parse one structured mechanism-analysis JSON object from the CLI."""

    try:
        payload = json.loads(raw_spec)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--mechanism-analysis must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--mechanism-analysis must be a JSON object")
    layer = clean_string(payload.get("layer"))
    status = clean_string(payload.get("status"))
    summary = clean_string(payload.get("summary"))
    source = clean_string(payload.get("source"))
    if layer not in MECHANISM_ANALYSIS_LAYERS:
        raise SystemExit(f"invalid mechanism-analysis layer: {layer}")
    if status not in MECHANISM_ANALYSIS_STATUSES:
        raise SystemExit(f"invalid mechanism-analysis status: {status}")
    if not summary:
        raise SystemExit("--mechanism-analysis requires a non-empty summary")
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    details = {
        str(key): value
        for key, value in payload.items()
        if key not in {"layer", "status", "summary", "source", "metrics"}
    }
    return MechanismAnalysisSpec(
        layer=layer,
        status=status,
        summary=summary,
        source=source,
        metrics=dict(metrics),
        details=details,
    )


def build_evidence_records(
    *,
    root: Path,
    node_id: str,
    existing_registry: dict[str, Any],
    evidence_specs: tuple[EvidenceSpec, ...],
    created_at: str,
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Build registry records and node evidence pointers for requested evidence."""

    existing_records = [item for item in existing_registry.get("records", []) if isinstance(item, dict)]
    existing_ids = {clean_string(item.get("evidence_id")) for item in existing_records}
    new_records: list[dict[str, Any]] = []
    node_evidence_updates: dict[str, str] = {}
    evidence_ids: list[str] = []
    for spec in evidence_specs:
        evidence_id = spec.evidence_id or next_evidence_id(node_id, spec.kind, existing_ids | set(evidence_ids))
        if evidence_id in existing_ids or evidence_id in evidence_ids:
            raise SystemExit(f"duplicate evidence_id: {evidence_id}")
        portable = portable_record_path(root, spec.path)
        record: dict[str, Any] = {
            "evidence_id": evidence_id,
            "kind": spec.kind,
            "path": portable["path"],
            "node_id": node_id,
            "claim": spec.claim,
            "evidence_state": spec.evidence_state,
            "created_at": created_at,
        }
        if portable["external_path"]:
            record["external_path"] = True
        if portable["external_unavailable"]:
            record["external_unavailable"] = True
        record.update(spec.metadata)
        new_records.append(record)
        evidence_ids.append(evidence_id)
        key = spec.node_evidence_key or safe_identifier_token(spec.kind)
        node_evidence_updates[key] = portable["path"]
    return new_records, node_evidence_updates, evidence_ids


def next_evidence_id(node_id: str, kind: str, taken_ids: set[str]) -> str:
    """Return a deterministic unused evidence id for a node/kind pair."""

    base = f"ev_{safe_identifier_token(node_id)}_{safe_identifier_token(kind)}"
    if base not in taken_ids:
        return base
    index = 2
    while f"{base}_{index:02d}" in taken_ids:
        index += 1
    return f"{base}_{index:02d}"


def update_node_payload(
    *,
    root: Path,
    node_dir: Path,
    node_payload: dict[str, Any],
    request: NodeFinalizationRequest,
    node_evidence_updates: dict[str, str],
) -> None:
    """Apply final state and display/evidence updates to node.json."""

    display = node_payload.get("display") if isinstance(node_payload.get("display"), dict) else {}
    evidence = node_payload.get("evidence") if isinstance(node_payload.get("evidence"), dict) else {}
    evidence.update(node_evidence_updates)
    evidence["reflection"] = relative_path_or_absolute(root, node_dir / "reflection.md")

    node_payload["lifecycle_state"] = request.lifecycle_state
    node_payload["run_state"] = request.run_state
    node_payload["claim_status"] = request.claim_status
    node_payload["outcome"] = request.outcome
    node_payload["outcome_code"] = request.outcome_code
    node_payload["claim_level"] = derive_claim_level(request.claim_status)
    node_payload["decision"] = request.decision
    if request.pathway_id:
        node_payload["pathway_id"] = request.pathway_id
        node_payload["elementary_step_id"] = request.step_id
    node_payload["evidence"] = evidence
    node_payload["display"] = {
        **display,
        "badges": list(request.badges),
        "metrics": request.metrics,
        "primary_file": portable_record_path(root, request.primary_file)["path"],
        "summary": request.summary,
        "title": display.get("title") or request.node_id,
        "subtitle": display.get("subtitle") or node_payload.get("stage", ""),
    }


def update_tree_payload(
    *,
    tree_payload: dict[str, Any],
    request: NodeFinalizationRequest,
    evidence_ids: list[str],
    timestamp: str,
) -> None:
    """Update tree indexes and append a finalization event."""

    tree_payload["active_frontier"] = [
        node_id for node_id in tree_payload.get("active_frontier", []) if node_id != request.node_id
    ]
    if request.lifecycle_state == "closed":
        tree_payload["closed_nodes"] = append_unique(tree_payload.get("closed_nodes", []), request.node_id)
    if request.claim_status == "accepted_ts":
        tree_payload["accepted_nodes"] = append_unique(tree_payload.get("accepted_nodes", []), request.node_id)

    events = list(tree_payload.get("events") or [])
    event_id = next_event_id(request.node_id, request.decision, {clean_string(item.get("event_id")) for item in events if isinstance(item, dict)})
    events.append(
        {
            "event_id": event_id,
            "time": timestamp,
            "node_id": request.node_id,
            "event_type": "finalize_node",
            "decision": request.decision,
            "reason": request.summary,
            "evidence_refs": evidence_ids,
        },
    )
    tree_payload["events"] = events


def next_event_id(node_id: str, decision: str, taken_ids: set[str]) -> str:
    """Return an unused event id for a finalization event."""

    base = f"evt_{safe_identifier_token(node_id)}_{safe_identifier_token(decision)}"
    if base not in taken_ids:
        return base
    index = 2
    while f"{base}_{index:02d}" in taken_ids:
        index += 1
    return f"{base}_{index:02d}"


def append_unique(raw_items: Any, item: str) -> list[str]:
    """Append item to a list unless already present, preserving order."""

    items = list(raw_items or [])
    if item not in items:
        items.append(item)
    return items


def update_evidence_registry(registry_payload: dict[str, Any], records: list[dict[str, Any]], *, timestamp: str) -> None:
    """Append evidence records to evidence_registry.json."""

    registry_payload["records"] = list(registry_payload.get("records") or []) + records
    registry_payload["updated_at"] = timestamp


def update_manifest(manifest_payload: dict[str, Any], request: NodeFinalizationRequest) -> None:
    """Update manifest only for workspace-global finalization effects."""

    if request.claim_status == "accepted_ts":
        manifest_payload["current_accepted_ts"] = request.node_id


def write_reflection(path: Path, reflection: ReflectionSpec) -> None:
    """Write reflection.md from structured post-execution fields."""

    knowledge_lines = list(reflection.knowledge_updates) or ["No knowledge-base update requested."]
    text = "\n".join(
        [
            "# Reflection",
            "",
            "## Computational Outcome",
            "",
            reflection.computational_outcome,
            "",
            "## Mechanistic Implication",
            "",
            reflection.mechanistic_implication,
            "",
            "## Knowledge Update",
            "",
            *[f"- {item}" for item in knowledge_lines],
            "",
            "## Next Branch",
            "",
            reflection.next_branch or "No next branch recorded.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def append_knowledge_base(
    path: Path,
    request: NodeFinalizationRequest,
    evidence_ids: list[str],
    *,
    timestamp: str,
) -> None:
    """Append optional source-backed updates to knowledge_base.md."""

    update = request.knowledge
    if not any((update.facts, update.refutations, update.open_questions, update.next_decision)):
        return
    evidence_suffix = f" Evidence: {', '.join(f'`{item}`' for item in evidence_ids)}." if evidence_ids else ""
    lines = [
        "",
        f"## Finalization Update: {request.node_id}",
        "",
        f"- Time: {timestamp}",
    ]
    lines.extend(f"- Validated fact: {item}{evidence_suffix}" for item in update.facts)
    lines.extend(f"- Refuted hypothesis: {item}{evidence_suffix}" for item in update.refutations)
    lines.extend(f"- Open question: {item}" for item in update.open_questions)
    if update.next_decision:
        lines.append(f"- Next decision: {update.next_decision}")
    lines.append("")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def update_mechanism_model(
    path: Path,
    request: NodeFinalizationRequest,
    evidence_ids: list[str],
    *,
    timestamp: str,
) -> None:
    """Append optional machine-readable mechanism-model updates."""

    update = request.knowledge
    if not any(
        (
            update.mechanism_facts,
            update.mechanism_refutations,
            update.mechanism_open_questions,
            update.tool_implications,
            update.mechanism_analysis,
        )
    ):
        return
    model = read_json_object_required(path)
    refs = list(evidence_ids)
    append_records(model, "validated_facts", "fact", update.mechanism_facts, refs)
    append_records(model, "refuted_hypotheses", "hypothesis", update.mechanism_refutations, refs)
    open_questions = list(model.get("open_questions") or [])
    for item in update.mechanism_open_questions:
        if item not in open_questions:
            open_questions.append(item)
    model["open_questions"] = open_questions
    append_records(model, "tool_implications", "implication", update.tool_implications, refs)
    append_mechanism_analysis_records(model, request, refs, timestamp)
    model["updated_at"] = timestamp
    write_json_object(path, model, overwrite_existing=True)


def append_records(model: dict[str, Any], key: str, text_key: str, values: tuple[str, ...], evidence_ids: list[str]) -> None:
    """Append evidence-backed records to a list field in mechanism_model.json."""

    records = list(model.get(key) or [])
    for value in values:
        records.append({text_key: value, "evidence_refs": list(evidence_ids)})
    model[key] = records


def append_mechanism_analysis_records(
    model: dict[str, Any],
    request: NodeFinalizationRequest,
    evidence_ids: list[str],
    timestamp: str,
) -> None:
    """Append structured mechanism-analysis records to mechanism_model.json."""

    analysis = model.get("mechanism_analysis") if isinstance(model.get("mechanism_analysis"), dict) else {}
    for layer in MECHANISM_ANALYSIS_LAYERS:
        if not isinstance(analysis.get(layer), list):
            analysis[layer] = []
    for item in request.knowledge.mechanism_analysis:
        record: dict[str, Any] = {
            "node_id": request.node_id,
            "claim_status": request.claim_status,
            "status": item.status,
            "summary": item.summary,
            "evidence_refs": list(evidence_ids),
            "created_at": timestamp,
        }
        if item.source:
            portable = portable_record_path(request.root, item.source)
            record["source"] = portable["path"]
            if portable["external_path"]:
                record["source_external_path"] = True
            if portable["external_unavailable"]:
                record["source_external_unavailable"] = True
        if item.metrics:
            record["metrics"] = item.metrics
        if item.details:
            record["details"] = item.details
        analysis[item.layer].append(record)
    model["mechanism_analysis"] = analysis


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for workspace records."""

    return datetime.now(timezone.utc).isoformat()
