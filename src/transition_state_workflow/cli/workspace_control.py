"""Public TS workspace control-plane commands.

This module owns the LLM-facing workspace contract.  The public surface is
small on purpose:

``init_workspace`` creates the root ledger, ``start_node`` creates and starts a
node, ``end_node`` closes a node with structured program/mechanism
explanations, ``report_workspace`` emits a constrained context packet,
``validate_decision`` checks a proposed LLM decision before any workspace
mutation, and ``validate_workspace`` runs the read-only workspace contract
check.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import (
    NODE_CLOSURE_SCHEMA,
    NODE_LEGACY_STATE_FIELDS,
    VALID_END_NODE_DISPOSITIONS,
    VALID_NODE_DISPOSITIONS,
    VALID_WORKFLOW_PHASES,
)
from transition_state_workflow.core.start_node import NodeStartRequest, normalize_start_evidence_refs, start_ts_workspace_node
from transition_state_workflow.core.workspace_state import create_ts_branch_decision_artifacts_from_cli_args
from transition_state_workflow.gate.evidence import record_supports_tsfreq_reframe
from transition_state_workflow.gate.finalize import (
    KnowledgeUpdateSpec,
    NodeFinalizationRequest,
    ReflectionSpec,
    finalize_ts_workspace_node,
    parse_evidence_spec,
)
from transition_state_workflow.gate.validate import validate_ts_workspace_contract
from transition_state_workflow.core.workspace_report import build_workspace_report_packet
from transition_state_workflow.util.json_io import read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import clean_string, list_or_empty


WORKSPACE_REPORT_SCHEMA = "ts-workspace-report"
DECISION_VALIDATION_SCHEMA = "ts-decision-validation"

FORBIDDEN_MODEL_FIELDS = (
    "claim_status",
    "claim_level",
    "outcome",
    "outcome_code",
    "lifecycle_state",
    "run_state",
    "accepted_ts",
    "mechanism_status",
)


@dataclass(frozen=True)
class ClosureInput:
    """Structured closure explanation supplied to ``end_node``."""

    program_summary: str
    mechanism_summary: str
    implication: str
    program_facts: tuple[dict[str, Any], ...] = ()
    mechanism_facts: tuple[dict[str, Any], ...] = ()
    open_questions: tuple[str, ...] = ()


def register_init_workspace_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the public init_workspace command."""

    init = subparsers.add_parser("init_workspace", help="Initialize a TS workspace root ledger.")
    init.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    init.add_argument("--system", required=True, help="Short system label.")
    init.add_argument("--charge", required=True, type=int, help="Total charge.")
    init.add_argument("--multiplicity", required=True, type=int, help="Spin multiplicity.")
    init.add_argument("--reaction-class", default="unknown", help="Initial reaction-class hypothesis.")
    init.add_argument("--key-atoms", nargs="*", default=[], help="Reaction-center atom labels or indices.")
    init.add_argument(
        "--bond-change",
        action="append",
        default=[],
        help="Expected bond change as role:atomA-atomB, e.g. breaking:O7-H5.",
    )
    init.add_argument(
        "--pathway-mode",
        default="unknown",
        choices=("unknown", "multi_step"),
        help="Initialize pathway_model.json as unknown or multi_step.",
    )
    init.add_argument("--pathway-id", default="", help="Pathway id for --pathway-mode multi_step.")
    init.add_argument("--pathway-label", default="", help="Readable pathway label for --pathway-mode multi_step.")
    init.add_argument(
        "--pathway-step",
        action="append",
        default=[],
        help="Elementary step as step_id:from->to; repeat for multi-step pathways.",
    )
    init.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")
    init.add_argument("--no-explorer-register", action="store_true", help="Skip persistent explorer registration.")
    init.add_argument("--explorer-register", action="store_true", help="Register this workspace in the explorer registry.")
    init.add_argument("--explorer-registry", type=Path, default=None, help="Explorer registry path.")
    add_logging_arguments(init)


def register_start_node_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the public start_node command."""

    start = subparsers.add_parser("start_node", help="Create and start one node.")
    start.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    start.add_argument("--node-id", required=True, help="Node id under nodes/.")
    start.add_argument("--phase", required=True, choices=sorted(VALID_WORKFLOW_PHASES))
    start.add_argument("--operation", required=True, help="Operation or route chosen for this test.")
    start.add_argument("--hypothesis", required=True, help="Chemical hypothesis being tested.")
    start.add_argument("--parent-id", default=None, help="Parent node id.")
    start.add_argument("--input-ref", action="append", default=[], help="Additional input/dependency node id.")
    start.add_argument("--pathway-id", default="", help="Optional pathway id.")
    start.add_argument("--step-id", default="", help="Optional elementary step id.")
    start.add_argument("--trigger-source", default="", help="State, user request, or event that triggered this node.")
    start.add_argument("--parent-selection-reason", default="", help="Why this parent node is the right ancestor.")
    start.add_argument("--context-packet-ref", default="", help="Optional report_workspace packet path or id.")
    start.add_argument(
        "--evidence-ref",
        action="append",
        default=[],
        help="Existing evidence id, or a unique evidence_registry path to normalize before creating this node.",
    )
    start.add_argument("--changed-variable", action="append", default=[], help="Changed variable as key=value.")
    start.add_argument("--rationale", default="", help="Why the selected operation is appropriate.")
    start.add_argument("--expected-evidence", action="append", default=[], help="Expected supporting evidence.")
    start.add_argument("--refutation-criteria", action="append", default=[], help="Concrete refutation criterion.")
    start.add_argument("--cost-risk", default="", help="Cost/risk decision for this node.")
    start.add_argument("--next-if-supported", default="", help="Next step if supported.")
    start.add_argument("--next-if-refuted", default="", help="Next step if refuted.")
    start.add_argument(
        "--replaces-node",
        default="",
        help="Failed or ambiguous node that this new branch replaces; requires --parent-id as the backtrack target.",
    )
    start.add_argument(
        "--backtrack-reason-code",
        default="replacement_branch",
        help="Diagnostic reason code for the canonical replacement backtrack event.",
    )
    start.add_argument("--backtrack-reason", default="", help="Human-readable reason for the replacement backtrack event.")
    start.add_argument(
        "--backtrack-evidence-ref",
        action="append",
        default=[],
        help="Evidence id, or unique evidence_registry path, supporting the replacement backtrack.",
    )
    start.add_argument(
        "--supersede-active-backtrack",
        action="store_true",
        help="Supersede any active backtrack before recording this replacement branch event.",
    )
    start.add_argument("--primary-file", default="", help="Primary input/script/log shown while running.")
    start.add_argument("--force", action="store_true", help="Overwrite existing node templates.")
    add_logging_arguments(start)


def register_end_node_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the public end_node command."""

    end = subparsers.add_parser("end_node", help="Close one node with program and mechanism explanations.")
    end.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    end.add_argument("--node-id", required=True, help="Node id under nodes/.")
    end.add_argument("--node-disposition", required=True, choices=sorted(VALID_END_NODE_DISPOSITIONS))
    end.add_argument("--phase", required=True, choices=sorted(VALID_WORKFLOW_PHASES))
    end.add_argument("--decision", required=True, help="Next decision/action token.")
    end.add_argument("--summary", required=True, help="Short closure summary.")
    end.add_argument("--primary-file", required=True, help="Primary evidence file path.")
    end.add_argument("--evidence", action="append", default=[], help="Evidence JSON object; may be repeated.")
    end.add_argument("--program-summary", required=True, help="Program/computation-level explanation.")
    end.add_argument("--program-fact", action="append", default=[], help="Program fact as text or JSON object.")
    end.add_argument("--mechanism-summary", required=True, help="Mechanism-level explanation.")
    end.add_argument("--mechanism-fact", action="append", default=[], help="Mechanism fact as text or JSON object.")
    end.add_argument("--implication", required=True, help="Implication for future planning.")
    end.add_argument("--open-question", action="append", default=[], help="Open question for report_workspace.")
    end.add_argument("--next-branch", required=True, help="Next branch text for reflection.")
    end.add_argument("--pathway-id", default="", help="Optional pathway id.")
    end.add_argument("--step-id", default="", help="Optional elementary step id.")
    end.add_argument(
        "--pathway-step-status",
        choices=("candidate", "ambiguous", "rejected"),
        default="",
        help="Optional pathway-step conclusion when this node updates a multi-step pathway.",
    )
    add_logging_arguments(end)


def register_report_workspace_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the public report_workspace command."""

    report = subparsers.add_parser("report_workspace", help="Emit a constrained LLM-facing workspace report.")
    report.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    report.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    report.add_argument(
        "--alternative-mechanism",
        action="store_true",
        help="Report context for a distinct alternative mechanism after an accepted TS.",
    )
    add_logging_arguments(report)


def register_validate_decision_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the public validate_decision command."""

    validate = subparsers.add_parser("validate_decision", help="Validate a proposed LLM decision JSON.")
    validate.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    validate.add_argument("--decision-file", required=True, type=Path, help="JSON file containing the proposed decision.")
    validate.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    add_logging_arguments(validate)


def register_validate_workspace_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the public validate_workspace command."""

    validate = subparsers.add_parser("validate_workspace", help="Validate a TS workspace contract.")
    validate.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    validate.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    validate.add_argument("--strict", action="store_true", help="Exit nonzero on warnings as well as errors.")
    add_logging_arguments(validate)


def validate_workspace_payload(root: Path) -> dict[str, Any]:
    """Return the read-only workspace validation payload."""

    return validate_ts_workspace_contract(root)


def validate_workspace_exit_code(payload: dict[str, Any], *, strict: bool) -> int:
    """Return the command exit code for a validation payload."""

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if summary.get("errors"):
        return 1
    if strict and summary.get("warnings"):
        return 1
    return 0


def add_logging_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")


def start_node_from_cli_args(args: argparse.Namespace) -> None:
    """Create a node through the old low-level writer, then mark it running."""

    root = args.root.expanduser().resolve()
    evidence_refs = normalize_start_evidence_refs(root, tuple(args.evidence_ref or ()))
    backtrack_evidence_refs = normalize_start_evidence_refs(root, tuple(args.backtrack_evidence_ref or ()))
    bridge_args = argparse.Namespace(
        root=root,
        node_id=args.node_id,
        stage=args.phase,
        parent_id=args.parent_id,
        pathway_id=args.pathway_id,
        step_id=args.step_id,
        input_ref=args.input_ref or [],
        hypothesis=args.hypothesis,
        operation=args.operation,
        trigger_source=args.trigger_source,
        parent_selection_reason=args.parent_selection_reason,
        context_packet_ref=args.context_packet_ref,
        evidence_ref=list(evidence_refs),
        changed_variable=args.changed_variable or [],
        method_or_tool_rationale=args.rationale,
        claim_ceiling=claim_ceiling_for_phase(args.phase),
        support_criteria=args.expected_evidence or [],
        refutation_criteria=args.refutation_criteria or [],
        cost_risk=args.cost_risk,
        next_if_supported=args.next_if_supported,
        next_if_refuted=args.next_if_refuted,
        replaces_node=args.replaces_node,
        backtrack_reason_code=args.backtrack_reason_code,
        backtrack_reason=args.backtrack_reason,
        backtrack_evidence_ref=list(backtrack_evidence_refs),
        supersede_active_backtrack=bool(args.supersede_active_backtrack),
        force=bool(args.force),
    )
    create_ts_branch_decision_artifacts_from_cli_args(bridge_args)
    start_ts_workspace_node(
        NodeStartRequest(
            root=root,
            node_id=args.node_id,
            run_state="running",
            decision="start_node",
            summary=f"Node started in phase {args.phase}: {args.operation}",
            primary_file=args.primary_file,
            badges=("Running", args.phase),
            evidence_refs=evidence_refs,
            force=bool(args.force),
        )
    )
    node_path = root / "nodes" / args.node_id / "node.json"
    node = read_json_object_required(node_path)
    node["phase"] = args.phase
    node["node_disposition"] = "Running"
    write_json_object(node_path, node, overwrite_existing=True)


def end_node_from_cli_args(args: argparse.Namespace) -> None:
    """Close a node with the public closure explanation contract."""

    root = args.root.expanduser().resolve()
    evidence_specs = tuple(parse_evidence_spec(item) for item in (args.evidence or ()))
    claim_status, outcome, run_state, pathway_step_status = closure_state_for(
        phase=args.phase,
        node_disposition=args.node_disposition,
        requested_pathway_step_status=clean_string(args.pathway_step_status),
    )
    closure_input = ClosureInput(
        program_summary=args.program_summary,
        program_facts=tuple(parse_fact(item, default_type="program") for item in (args.program_fact or ())),
        mechanism_summary=args.mechanism_summary,
        mechanism_facts=tuple(parse_fact(item, default_type="mechanism") for item in (args.mechanism_fact or ())),
        implication=args.implication,
        open_questions=tuple(clean_string(item) for item in (args.open_question or ()) if clean_string(item)),
    )
    request = NodeFinalizationRequest(
        root=root,
        node_id=args.node_id,
        claim_status=claim_status,
        outcome=outcome,
        phase=args.phase,
        node_disposition=args.node_disposition,
        outcome_code=outcome_code_for(args.node_disposition, args.phase),
        lifecycle_state="closed",
        run_state=run_state,
        decision=args.decision,
        summary=args.summary,
        primary_file=args.primary_file,
        pathway_id=clean_string(args.pathway_id),
        step_id=clean_string(args.step_id),
        pathway_step_status=pathway_step_status,
        badges=(args.node_disposition, args.phase),
        metrics={},
        evidence=evidence_specs,
        reflection=ReflectionSpec(
            computational_outcome=args.program_summary,
            mechanistic_implication=args.mechanism_summary,
            program_facts=closure_input.program_facts,
            mechanism_facts=closure_input.mechanism_facts,
            knowledge_updates=(args.implication,),
            open_questions=closure_input.open_questions,
            next_branch=args.next_branch,
        ),
        knowledge=KnowledgeUpdateSpec(
            open_questions=closure_input.open_questions,
            next_decision=args.next_branch,
            mechanism_open_questions=closure_input.open_questions,
        ),
    )
    finalize_ts_workspace_node(request)
    append_closure_explanation(
        root=root,
        node_id=args.node_id,
        phase=args.phase,
        node_disposition=args.node_disposition,
        closure=closure_input,
    )


def build_workspace_report_payload(
    root: Path,
    *,
    alternative_mechanism: bool = False,
) -> dict[str, Any]:
    """Build the constrained report_workspace payload."""

    source = root.expanduser().resolve()
    packet = build_workspace_report_packet(
        source,
        alternative_mechanism=alternative_mechanism,
        command_alias="report_workspace",
        validate_workspace=validate_ts_workspace_contract,
        supports_tsfreq_evidence=record_supports_tsfreq_reframe,
    )
    tree = read_json_object_required(source / "tree.json")
    node_ids = sorted((tree.get("nodes") or {}).keys())
    node_index = [public_node_index_entry(source, str(node_id)) for node_id in node_ids]
    focus = packet.get("focus") if isinstance(packet.get("focus"), dict) else {}
    return {
        "schema": WORKSPACE_REPORT_SCHEMA,
        "source": str(source),
        "generated_at": packet.get("generated_at"),
        "workspace": packet.get("workspace", {}),
        "pathway": packet.get("pathway", {}),
        "ledger_refs": workspace_ledger_refs(),
        "current_phase": packet.get("search_state", {}).get("phase") if isinstance(packet.get("search_state"), dict) else "",
        "current_phase_scope": packet.get("search_state", {}).get("phase_scope", {})
        if isinstance(packet.get("search_state"), dict)
        else {},
        "current_phase_reasons": packet.get("search_state", {}).get("phase_reasons", [])
        if isinstance(packet.get("search_state"), dict)
        else [],
        "focus": {
            "mode": clean_string(focus.get("mode")),
            "focus_node": clean_string(focus.get("focus_node")) or None,
            "parent_for_new_branch": clean_string(focus.get("parent_for_new_branch")) or None,
            "reason": clean_string(focus.get("reason")),
        },
        "claim_readiness": packet.get("claim_readiness", {}),
        "available_commands": list_or_empty(packet.get("available_commands")),
        "node_index": node_index,
        "situation": {
            "validation": packet.get("validation_summary", {}),
            "context_items": strip_forbidden_report_fields(packet.get("context_items", [])),
            "endpoint_evidence_blockers": strip_forbidden_report_fields(packet.get("endpoint_evidence_blockers", [])),
            "open_questions": packet.get("open_questions", []),
        },
        "allowed_response_contract": response_contract(),
    }


def workspace_ledger_refs() -> dict[str, str]:
    """Return root-ledger file names the model can read for full state."""

    return {
        "manifest": "manifest.json",
        "tree": "tree.json",
        "evidence_registry": "evidence_registry.json",
        "mechanism_model": "mechanism_model.json",
        "pathway_model": "pathway_model.json",
        "knowledge_base": "knowledge_base.md",
    }


def validate_decision_payload(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    """Validate a proposed LLM decision against the report_workspace contract."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    action = clean_string(decision.get("action"))
    contract = response_contract()
    allowed_actions = set(contract["allowed_actions"])
    if action not in allowed_actions:
        errors.append({"code": "invalid_action", "message": f"action must be one of: {', '.join(sorted(allowed_actions))}"})
    forbidden_hits = sorted(find_forbidden_fields(decision, set(FORBIDDEN_MODEL_FIELDS)))
    if forbidden_hits:
        errors.append({"code": "forbidden_fields", "message": "decision includes forbidden fields: " + ", ".join(forbidden_hits)})
    if action == "start_node":
        require_fields(decision, ("node_id", "phase", "operation", "hypothesis", "rationale", "expected_evidence"), errors)
        validate_phase(decision.get("phase"), errors)
        validate_start_node_backtrack_fields(decision, root, errors)
    elif action == "end_node":
        require_fields(decision, ("node_id", "node_disposition", "phase", "closure_explanation"), errors)
        validate_phase(decision.get("phase"), errors)
        disposition = clean_string(decision.get("node_disposition"))
        if disposition not in VALID_END_NODE_DISPOSITIONS:
            errors.append({"code": "invalid_node_disposition", "message": f"node_disposition must be one of: {', '.join(sorted(VALID_END_NODE_DISPOSITIONS))}"})
        closure = decision.get("closure_explanation")
        if not isinstance(closure, dict):
            errors.append({"code": "closure_explanation_not_object", "message": "closure_explanation must be an object"})
        else:
            validate_explanation_block(closure, "program", errors)
            validate_explanation_block(closure, "mechanism", errors)
            if not clean_string(closure.get("implication")):
                errors.append({"code": "missing_implication", "message": "closure_explanation.implication is required"})
    elif action in {"ask_user", "stop"}:
        require_fields(decision, ("rationale",), errors)

    source = root.expanduser().resolve()
    if action in {"start_node", "end_node"} and clean_string(decision.get("node_id")):
        tree = read_json_object_required(source / "tree.json")
        node_id = clean_string(decision.get("node_id"))
        node_exists = node_id in (tree.get("nodes") or {})
        if action == "start_node" and node_exists:
            errors.append({"code": "node_already_exists", "message": f"node already exists: {node_id}"})
        if action == "end_node" and not node_exists:
            errors.append({"code": "node_missing", "message": f"node does not exist: {node_id}"})

    return {
        "schema": DECISION_VALIDATION_SCHEMA,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "normalized_decision": decision if not errors else {},
    }


def response_contract() -> dict[str, Any]:
    """Return the single LLM response contract shared by report and validator."""

    return {
        "allowed_actions": ["start_node", "end_node", "ask_user", "stop"],
        "forbidden_fields": list(FORBIDDEN_MODEL_FIELDS),
        "schemas_by_action": {
            "start_node": {
                "required": ["action", "node_id", "phase", "operation", "hypothesis", "rationale", "expected_evidence"],
                "optional": [
                    "parent_id",
                    "input_refs",
                    "changed_variables",
                    "cost_risk",
                    "next_if_supported",
                    "next_if_refuted",
                    "replaces_node",
                    "backtrack_reason_code",
                    "backtrack_reason",
                    "backtrack_evidence_refs",
                    "supersede_active_backtrack",
                ],
            },
            "end_node": {
                "required": ["action", "node_id", "node_disposition", "phase", "closure_explanation"],
                "node_disposition": sorted(VALID_END_NODE_DISPOSITIONS),
                "closure_explanation": {
                    "required": ["program.summary", "mechanism.summary", "implication"],
                    "optional": ["program.facts", "mechanism.facts", "open_questions"],
                },
            },
            "ask_user": {"required": ["action", "rationale"], "optional": ["questions"]},
            "stop": {"required": ["action", "rationale"], "optional": []},
        },
    }


def append_closure_explanation(
    *,
    root: Path,
    node_id: str,
    phase: str,
    node_disposition: str,
    closure: ClosureInput,
) -> None:
    """Append the public closure contract to node.json."""

    node_path = root / "nodes" / node_id / "node.json"
    node = read_json_object_required(node_path)
    evidence_refs = sorted({ref for fact in [*closure.program_facts, *closure.mechanism_facts] for ref in fact_evidence_refs(fact)})
    node["phase"] = phase
    node["node_disposition"] = node_disposition
    for field in NODE_LEGACY_STATE_FIELDS:
        node.pop(field, None)
    node["closure_explanation"] = {
        "schema": NODE_CLOSURE_SCHEMA,
        "program": {
            "summary": closure.program_summary,
            "facts": list(closure.program_facts),
        },
        "mechanism": {
            "summary": closure.mechanism_summary,
            "facts": list(closure.mechanism_facts),
        },
        "implication": closure.implication,
        "open_questions": list(closure.open_questions),
        "evidence_refs": evidence_refs,
    }
    write_json_object(node_path, node, overwrite_existing=True)


def fact_evidence_refs(fact: dict[str, Any]) -> list[str]:
    """Return evidence refs from a closure fact supporting list or scalar forms."""

    refs = [clean_string(item) for item in list_or_empty(fact.get("evidence_refs")) if clean_string(item)]
    scalar = clean_string(fact.get("evidence_ref"))
    if scalar:
        refs.append(scalar)
    return refs


def public_node_index_entry(root: Path, node_id: str) -> dict[str, Any]:
    """Return a compact node artifact index for report_workspace."""

    node_path = root / "nodes" / node_id / "node.json"
    node = read_json_object_required(node_path) if node_path.exists() else {}
    display = node.get("display") if isinstance(node.get("display"), dict) else {}
    node_dir = root / "nodes" / node_id
    entry: dict[str, Any] = {
        "node_id": node_id,
        "parent_id": clean_string(node.get("parent_id")) or None,
        "phase": public_phase(node),
        "node_disposition": public_node_disposition(node),
        "operation": clean_string(node.get("operation")),
        "summary": clean_string(display.get("summary")),
        "node_json": f"nodes/{node_id}/node.json",
    }
    if (node_dir / "reflection.md").exists():
        entry["reflection"] = f"nodes/{node_id}/reflection.md"
    if (node_dir / "decision_card.md").exists():
        entry["decision_card"] = f"nodes/{node_id}/decision_card.md"
    evidence_refs = []
    closure = node.get("closure_explanation") if isinstance(node.get("closure_explanation"), dict) else {}
    for ref in list_or_empty(closure.get("evidence_refs")):
        clean_ref = clean_string(ref)
        if clean_ref:
            evidence_refs.append(clean_ref)
    if evidence_refs:
        entry["evidence_refs"] = evidence_refs
    return entry


def public_phase(node: dict[str, Any]) -> str:
    return clean_string(node.get("phase"))


def public_node_disposition(node: dict[str, Any]) -> str:
    disposition = clean_string(node.get("node_disposition"))
    if disposition:
        return disposition
    return ""


def claim_ceiling_for_phase(phase: str) -> str:
    return {
        "preflight": "not_evaluated",
        "endpoint": "endpoint_minima_ready",
        "rp_conformer_generation": "endpoint_minima_ready",
        "candidate_generation": "candidate_found",
        "tsfreq_validation": "tsfreq_validated",
        "connectivity_validation": "endpoint_connected_or_irc_connected",
        "accepted_audit": "accepted_ts",
        "pathway_audit": "accepted_pathway",
    }[phase]


def closure_state_for(
    *,
    phase: str,
    node_disposition: str,
    requested_pathway_step_status: str,
) -> tuple[str, str, str, str]:
    """Map public closure fields to current internal evidence gates."""

    if node_disposition == "Stopped":
        return "not_evaluated", "administrative_stop", "stopped", requested_pathway_step_status
    if node_disposition == "Error":
        return "not_evaluated", "numerical_failure", "error", requested_pathway_step_status
    claim_status = {
        "preflight": "not_evaluated",
        "endpoint": "endpoint_minima_ready",
        "rp_conformer_generation": "endpoint_minima_ready",
        "candidate_generation": "candidate_found",
        "tsfreq_validation": "tsfreq_validated",
        "connectivity_validation": "endpoint_connected",
        "accepted_audit": "accepted_ts",
        "pathway_audit": "accepted_pathway",
    }[phase]
    outcome = {
        "preflight": "none",
        "endpoint": "endpoint_minima_validated",
        "rp_conformer_generation": "endpoint_minima_validated",
        "candidate_generation": "candidate_generated",
        "tsfreq_validation": "tsfreq_validated",
        "connectivity_validation": "connectivity_validated",
        "accepted_audit": "accepted",
        "pathway_audit": "accepted",
    }[phase]
    return claim_status, outcome, "completed", requested_pathway_step_status


def outcome_code_for(node_disposition: str, phase: str) -> str | None:
    if node_disposition == "Error":
        return f"{phase}_program_error"
    if node_disposition == "Stopped":
        return f"{phase}_stopped"
    return None


def parse_fact(raw: str, *, default_type: str) -> dict[str, Any]:
    """Parse a fact supplied as JSON or plain text."""

    text = clean_string(raw)
    if not text:
        return {"type": default_type, "text": ""}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"type": default_type, "text": text}
    if not isinstance(payload, dict):
        return {"type": default_type, "text": text}
    payload.setdefault("type", default_type)
    return payload


def require_fields(payload: dict[str, Any], fields: tuple[str, ...], errors: list[dict[str, str]]) -> None:
    for field in fields:
        if field not in payload or not payload.get(field):
            errors.append({"code": "missing_field", "message": f"missing required field: {field}"})


def validate_phase(value: Any, errors: list[dict[str, str]]) -> None:
    phase = clean_string(value)
    if phase not in VALID_WORKFLOW_PHASES:
        errors.append({"code": "invalid_phase", "message": f"phase must be one of: {', '.join(sorted(VALID_WORKFLOW_PHASES))}"})


def validate_start_node_backtrack_fields(decision: dict[str, Any], root: Path, errors: list[dict[str, str]]) -> None:
    """Validate replacement-backtrack decision fields without mutating state."""

    replaces_node = clean_string(decision.get("replaces_node"))
    if not replaces_node:
        if "supersede_active_backtrack" in decision and not isinstance(decision.get("supersede_active_backtrack"), bool):
            errors.append(
                {
                    "code": "invalid_supersede_active_backtrack",
                    "message": "supersede_active_backtrack must be a boolean",
                }
            )
        return
    parent_id = clean_string(decision.get("parent_id"))
    if not parent_id:
        errors.append({"code": "missing_parent_id", "message": "replaces_node requires parent_id as the backtrack target"})
    if "supersede_active_backtrack" in decision and not isinstance(decision.get("supersede_active_backtrack"), bool):
        errors.append({"code": "invalid_supersede_active_backtrack", "message": "supersede_active_backtrack must be a boolean"})
    raw_evidence_refs = decision.get("backtrack_evidence_refs", [])
    if raw_evidence_refs and not isinstance(raw_evidence_refs, list):
        errors.append({"code": "invalid_backtrack_evidence_refs", "message": "backtrack_evidence_refs must be a list when provided"})
    source = root.expanduser().resolve()
    tree_path = source / "tree.json"
    if not tree_path.exists():
        return
    tree = read_json_object_required(tree_path)
    nodes = tree.get("nodes") if isinstance(tree.get("nodes"), dict) else {}
    if replaces_node and replaces_node not in nodes:
        errors.append({"code": "replaces_node_missing", "message": f"replaces_node does not exist: {replaces_node}"})
    if parent_id and parent_id not in nodes:
        errors.append({"code": "parent_missing", "message": f"parent_id does not exist: {parent_id}"})


def validate_explanation_block(closure: dict[str, Any], key: str, errors: list[dict[str, str]]) -> None:
    block = closure.get(key)
    if not isinstance(block, dict):
        errors.append({"code": f"{key}_explanation_missing", "message": f"closure_explanation.{key} must be an object"})
        return
    if not clean_string(block.get("summary")):
        errors.append({"code": f"{key}_summary_missing", "message": f"closure_explanation.{key}.summary is required"})


def find_forbidden_fields(payload: Any, forbidden: set[str], prefix: str = "") -> set[str]:
    """Return dotted paths where forbidden field names appear."""

    hits: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in forbidden:
                hits.add(path)
            hits.update(find_forbidden_fields(value, forbidden, path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            hits.update(find_forbidden_fields(item, forbidden, f"{prefix}[{index}]"))
    return hits


def strip_forbidden_report_fields(payload: Any) -> Any:
    """Remove model-forbidden state fields from report_workspace context."""

    if isinstance(payload, dict):
        return {
            key: strip_forbidden_report_fields(value)
            for key, value in payload.items()
            if key not in FORBIDDEN_MODEL_FIELDS
        }
    if isinstance(payload, list):
        return [strip_forbidden_report_fields(item) for item in payload]
    return payload


__all__ = [
    "DECISION_VALIDATION_SCHEMA",
    "FORBIDDEN_MODEL_FIELDS",
    "NODE_CLOSURE_SCHEMA",
    "VALID_NODE_DISPOSITIONS",
    "VALID_WORKFLOW_PHASES",
    "WORKSPACE_REPORT_SCHEMA",
    "build_workspace_report_payload",
    "end_node_from_cli_args",
    "register_end_node_parser",
    "register_init_workspace_parser",
    "register_report_workspace_parser",
    "register_start_node_parser",
    "register_validate_decision_parser",
    "register_validate_workspace_parser",
    "response_contract",
    "start_node_from_cli_args",
    "validate_decision_payload",
    "validate_workspace_exit_code",
    "validate_workspace_payload",
]
