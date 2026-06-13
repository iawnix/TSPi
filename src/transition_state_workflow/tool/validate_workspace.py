#!/usr/bin/env python3
"""Validate TS-search workspace schema and explorer-field consistency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any

from transition_state_workflow.base.findings import WorkspaceValidationFinding as Finding
from transition_state_workflow.config.state_contract import (
    CLAIM_LEVEL_RANK,
    MECHANISM_ANALYSIS_LAYERS,
    MECHANISM_ANALYSIS_STATUSES,
    MAXIMUM_CLAIM_LEVEL_BY_CLAIM_STATUS,
    TREE_LEGACY_TOP_LEVEL_FIELDS,
    TREE_NODE_FORBIDDEN_RUNTIME_FIELDS,
    VALID_BACKTRACK_EVENT_STATES,
    VALID_CLAIM_LEVELS,
    VALID_CLAIM_STATUSES,
    VALID_EVIDENCE_STATES,
    VALID_LIFECYCLE_STATES,
    VALID_OUTCOMES,
    VALID_RUN_STATES,
    check_node_contract_violations,
    valid_outcomes_for_claim_status,
)
from transition_state_workflow.tool.evidence_gates import accepted_ts_missing_evidence_gates
from transition_state_workflow.tool.pathway_model import (
    PATHWAY_MODES,
    PATHWAY_STATUSES,
    STEP_STATUSES,
    derive_pathway_status,
)
from transition_state_workflow.tool.normalize_view import normalize_ts_workspace_to_explorer_graph
from transition_state_workflow.util.cli import configure_cli_logging, emit_json
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, relative_path_or_absolute


REFLECTION_TEMPLATE_MARKERS = {"Not run yet.", "Pending."}
PRE_EXECUTION_EVIDENCE_KEYS = {"hypothesis", "decision_card", "reflection", "inputs", "outputs"}
REGISTRY_REQUIRED_SUFFIXES = {".json", ".out", ".log", ".xyz", ".csv", ".txt"}
ENGINE_ROOT_ARTIFACT_NAMES = {
    "charges",
    "coord",
    "energy",
    "g16_driver.out",
    "gradient",
    "hessian",
    "run_metadata.txt",
    "runner.nohup",
    "wbo",
    "xtb.trj",
    "xtbopt.xyz",
    "xtbrestart",
}
ENGINE_ROOT_ARTIFACT_SUFFIXES = {".chk", ".fchk", ".rwf", ".mwfn", ".trj", ".gbw", ".hess"}
GAUSSIAN_INPUT_SUFFIXES = {".gjf", ".com"}


def main() -> int:
    """Run the workspace contract validator command-line interface."""

    parser = argparse.ArgumentParser(description="Validate a tssearch_<system> workspace.")
    parser.add_argument("--source", required=True, type=Path, help="tssearch workspace root.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero on warnings as well as errors.")
    parser.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")
    args = parser.parse_args()
    configure_cli_logging(verbose=args.verbose, quiet=args.quiet)
    payload = validate_ts_workspace_contract(args.source)
    emit_json(payload, pretty=args.pretty)
    if payload["summary"]["errors"]:
        return 1
    if args.strict and payload["summary"]["warnings"]:
        return 1
    return 0


def validate_ts_workspace_contract(workspace_directory: Path) -> dict[str, Any]:
    """Validate a v2 TS-search workspace against the canonical explorer contract."""

    source = workspace_directory.expanduser().resolve()
    findings: list[Finding] = []
    manifest = read_json_optional(source / "manifest.json", findings)
    tree = read_json_optional(source / "tree.json", findings)
    evidence = read_json_optional(source / "evidence_registry.json", findings)
    pathway_model = read_json_optional(source / "pathway_model.json", findings)
    graph: dict[str, Any] = {"schema": "", "nodes": [], "events": [], "backtrack_events": [], "evidence": {"records": []}}
    graph_ready = False
    try:
        graph = normalize_ts_workspace_to_explorer_graph(source)
        graph_ready = True
    except Exception as exc:
        findings.append(
            Finding(
                "error",
                "normalizer_contract_error",
                f"v2 normalizer rejected this workspace: {exc}",
                path=str(source),
            )
        )

    require_file(source / "manifest.json", findings)
    require_file(source / "tree.json", findings)
    if not (source / "nodes").exists():
        findings.append(Finding("error", "missing_nodes_dir", "workspace is missing nodes/ directory", path="nodes"))

    tree_nodes = tree.get("nodes") if isinstance(tree.get("nodes"), dict) else {}
    tree_node_ids = {str(key) for key in tree_nodes}
    dir_node_ids = collect_node_dirs(source)
    node_ids = sorted(tree_node_ids | dir_node_ids)
    if not isinstance(tree.get("nodes"), dict):
        findings.append(Finding("error", "tree_nodes_not_object", "tree.json nodes must be an object", path="tree.json"))

    for node_id in sorted(tree_node_ids - dir_node_ids):
        findings.append(Finding("error", "missing_node_dir", "tree node has no nodes/<node_id>/ directory", path=f"nodes/{node_id}", node_id=node_id))
    for node_id in sorted(dir_node_ids - tree_node_ids):
        findings.append(Finding("warning", "missing_tree_node", "node directory is absent from tree.json nodes", path=f"nodes/{node_id}", node_id=node_id))

    validate_tree_top_level_contract(tree, findings)

    parent_by_node: dict[str, str] = {}
    input_refs_by_node: dict[str, list[str]] = {}
    node_json_by_id: dict[str, dict[str, Any]] = {}
    for node_id in node_ids:
        node_path = source / "nodes" / node_id / "node.json"
        node_json = read_json_optional(node_path, findings)
        node_json_by_id[node_id] = node_json
        if node_id in dir_node_ids and not node_path.exists():
            findings.append(Finding("error", "missing_node_json", "node directory has no node.json", path=relative_path_or_absolute(source, node_path), node_id=node_id))
        # node_id mismatch lives in the shared contract checker (state_contract)
        # so the normalizer's hard-error and the validator's soft-finding stay
        # in sync. validate_nodes_v2 below routes every contract violation,
        # including this one, to a finding.
        tree_payload = tree_nodes.get(node_id) if isinstance(tree_nodes.get(node_id), dict) else {}
        tree_state_fields = [key for key in TREE_NODE_FORBIDDEN_RUNTIME_FIELDS if key in tree_payload]
        if tree_state_fields:
            findings.append(
                Finding(
                    "error",
                    "tree_node_state_cache",
                    f"tree.nodes entry contains non-v2 runtime fields: {', '.join(tree_state_fields)}",
                    path="tree.json",
                    node_id=node_id,
                )
            )
        parent_node = clean_string(node_json.get("parent_id"))
        parent_tree = clean_string(tree_payload.get("parent_id"))
        if parent_node and parent_tree and parent_node != parent_tree:
            findings.append(Finding("error", "parent_conflict", f"node parent {parent_node!r} conflicts with tree parent {parent_tree!r}", path=relative_path_or_absolute(source, node_path), node_id=node_id))
        if parent_node and node_id in tree_node_ids and not parent_tree:
            findings.append(
                Finding(
                    "warning",
                    "tree_parent_missing",
                    f"node.json parent_id {parent_node!r} is missing from tree.json nodes[{node_id!r}].parent_id",
                    path="tree.json",
                    node_id=node_id,
                )
            )
        parent = parent_tree or parent_node
        parent_by_node[node_id] = parent
        if parent and parent not in node_ids:
            findings.append(Finding("error", "missing_parent", f"parent node does not exist: {parent}", path=relative_path_or_absolute(source, node_path), node_id=node_id))
        input_refs = [
            clean_string(value)
            for value in list_or_empty(node_json.get("input_refs")) + list_or_empty(tree_payload.get("input_refs"))
            if clean_string(value)
        ]
        for input_ref in sorted(set(input_refs)):
            if input_ref not in node_ids:
                findings.append(Finding("error", "missing_input_ref", f"input reference node does not exist: {input_ref}", path=relative_path_or_absolute(source, node_path), node_id=node_id))
        input_refs_by_node[node_id] = sorted(set(input_refs))

    validate_parent_graph(parent_by_node, findings)
    if graph_ready:
        validate_indexes(tree, graph, findings)
    validate_nodes_v2(source, node_json_by_id, findings)
    validate_manifest_accepted_ts(manifest, tree, node_json_by_id, findings)
    if graph_ready:
        validate_normalized_nodes(graph, findings)
    validate_evidence(source, evidence, node_ids, findings)
    validate_node_finalization_artifacts(source, node_json_by_id, parent_by_node, input_refs_by_node, evidence, findings)
    validate_pathway_model(source, pathway_model, node_json_by_id, evidence, findings)
    validate_mechanism_model(source, read_json_optional(source / "mechanism_model.json", findings), findings)
    validate_tree_events(tree, node_ids, evidence, findings)
    if graph_ready:
        validate_events(graph, node_ids, findings)
    validate_paths_are_portable(source, node_json_by_id, evidence, findings)
    validate_engine_artifact_policy(source, node_json_by_id, findings)

    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warning")
    return {
        "schema": "ts-workspace-validation-v1",
        "source": str(source),
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "nodes": len(node_ids),
            "tree_nodes": len(tree_node_ids),
            "node_dirs": len(dir_node_ids),
        },
        "findings": [finding.as_dict() for finding in findings],
        "graph_schema": graph.get("schema"),
        "manifest_system": manifest.get("system", ""),
    }


def validate_tree_top_level_contract(tree: dict[str, Any], findings: list[Finding]) -> None:
    """Reject top-level tree fields that duplicate canonical v2 state."""

    legacy = [field for field in TREE_LEGACY_TOP_LEVEL_FIELDS if field in tree]
    if legacy:
        findings.append(
            Finding(
                "error",
                "legacy_tree_top_level_fields",
                f"tree.json contains non-v2 top-level fields: {', '.join(legacy)}",
                path="tree.json",
            )
        )


def validate_parent_graph(parent_by_node: dict[str, str], findings: list[Finding]) -> None:
    """Validate that parent links form an acyclic branch tree."""

    for node_id, parent_id in parent_by_node.items():
        if parent_id == node_id:
            findings.append(
                Finding(
                    "error",
                    "self_parent",
                    "node parent_id points to itself",
                    path=f"nodes/{node_id}/node.json",
                    node_id=node_id,
                )
            )

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node_id: str, path: list[str]) -> None:
        if node_id in active:
            cycle = " -> ".join(path + [node_id])
            findings.append(
                Finding(
                    "error",
                    "parent_cycle",
                    f"parent links contain a cycle: {cycle}",
                    path="tree.json",
                    node_id=node_id,
                )
            )
            return
        if node_id in visited:
            return
        active.add(node_id)
        parent = parent_by_node.get(node_id)
        if parent:
            visit(parent, path + [node_id])
        active.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(parent_by_node):
        visit(node_id, [])


def validate_nodes_v2(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    """Validate required v2 fields and forbid legacy node-level aliases.

    The rule set lives in
    :mod:`transition_state_workflow.config.state_contract`; the normalizer hits
    the same rules but as hard errors. Keeping one source means rule additions
    automatically reach both tools.
    """

    for node_id, node_json in node_json_by_id.items():
        node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
        for code, message in check_node_contract_violations(node_id, node_json):
            findings.append(
                Finding("error", code, message, path=node_path, node_id=node_id)
            )


def validate_indexes(tree: dict[str, Any], graph: dict[str, Any], findings: list[Finding]) -> None:
    """Validate tree index arrays against normalized graph node state."""

    active = set(clean_string(item) for item in list_or_empty(tree.get("active_frontier")) if clean_string(item))
    closed = set(clean_string(item) for item in list_or_empty(tree.get("closed_nodes")) if clean_string(item))
    accepted = set(clean_string(item) for item in list_or_empty(tree.get("accepted_nodes")) if clean_string(item))
    graph_active = set(clean_string(item) for item in list_or_empty(graph.get("active_frontier")) if clean_string(item))
    graph_closed = set(clean_string(item) for item in list_or_empty(graph.get("closed_nodes")) if clean_string(item))
    graph_accepted = set(clean_string(item) for item in list_or_empty(graph.get("accepted_nodes")) if clean_string(item))
    node_by_id = {clean_string(node.get("id")): node for node in list_or_empty(graph.get("nodes")) if isinstance(node, dict)}
    if active != graph_active:
        findings.append(Finding("warning", "active_index_drift", "tree active_frontier differs from normalized active_frontier", path="tree.json"))
    if closed != graph_closed:
        findings.append(Finding("warning", "closed_index_drift", "tree closed_nodes differs from normalized closed_nodes", path="tree.json"))
    if accepted != graph_accepted:
        findings.append(Finding("warning", "accepted_index_drift", "tree accepted_nodes differs from normalized accepted_nodes", path="tree.json"))
    for node_id in active:
        node = node_by_id.get(node_id)
        if not node:
            findings.append(Finding("error", "frontier_missing_node", "active_frontier references a missing node", path="tree.json", node_id=node_id))
            continue
        if clean_string(node.get("lifecycle_state")) != "active":
            findings.append(Finding("error", "frontier_lifecycle_conflict", "active_frontier node is not lifecycle_state=active", path="tree.json", node_id=node_id))
        if clean_string(node.get("run_state")) not in {"pending", "running", "parsing"}:
            findings.append(Finding("warning", "frontier_run_state_unexpected", "active_frontier node run_state is not pending/running/parsing", path="tree.json", node_id=node_id))
    for node_id in closed:
        node = node_by_id.get(node_id)
        if node and clean_string(node.get("lifecycle_state")) != "closed":
            findings.append(Finding("warning", "closed_index_conflict", "closed_nodes entry is not lifecycle_state=closed", path="tree.json", node_id=node_id))
    for node_id in accepted:
        node = node_by_id.get(node_id)
        if node and clean_string(node.get("claim_status")) != "accepted_ts":
            findings.append(Finding("error", "accepted_index_conflict", "accepted_nodes entry is not claim_status=accepted_ts", path="tree.json", node_id=node_id))


def validate_manifest_accepted_ts(
    manifest: dict[str, Any],
    tree: dict[str, Any],
    node_json_by_id: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    """Validate manifest.current_accepted_ts against node and tree state."""

    current = clean_string(manifest.get("current_accepted_ts"))
    if not current:
        return
    node = node_json_by_id.get(current)
    if not node:
        findings.append(
            Finding(
                "error",
                "manifest_accepted_missing_node",
                "manifest current_accepted_ts references a missing node",
                path="manifest.json",
                node_id=current,
            )
        )
        return
    if clean_string(node.get("claim_status")) != "accepted_ts":
        findings.append(
            Finding(
                "error",
                "manifest_accepted_claim_conflict",
                "manifest current_accepted_ts node is not claim_status=accepted_ts",
                path="manifest.json",
                node_id=current,
            )
        )
    accepted_nodes = {clean_string(item) for item in list_or_empty(tree.get("accepted_nodes")) if clean_string(item)}
    if current not in accepted_nodes:
        findings.append(
            Finding(
                "error",
                "manifest_accepted_index_conflict",
                "manifest current_accepted_ts is missing from tree.accepted_nodes",
                path="manifest.json",
                node_id=current,
            )
        )


def validate_pathway_model(
    source: Path,
    model: dict[str, Any],
    node_json_by_id: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate optional pathway_model.json and node step references."""

    node_step_refs = {
        node_id: (
            clean_string(node.get("pathway_id")),
            clean_string(node.get("elementary_step_id")),
        )
        for node_id, node in node_json_by_id.items()
        if clean_string(node.get("pathway_id")) or clean_string(node.get("elementary_step_id"))
    }
    if not model:
        for node_id in node_step_refs:
            findings.append(
                Finding(
                    "error",
                    "pathway_model_missing",
                    "node records pathway_id/elementary_step_id but pathway_model.json is missing",
                    path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                    node_id=node_id,
                )
            )
        return

    if clean_string(model.get("schema")) != "tssearch-pathway-model-v1":
        findings.append(Finding("error", "pathway_schema_invalid", "pathway_model.json must declare schema=tssearch-pathway-model-v1", path="pathway_model.json"))
    mode = clean_string(model.get("mode"))
    if mode not in PATHWAY_MODES:
        findings.append(Finding("error", "pathway_mode_invalid", f"invalid pathway mode: {mode}", path="pathway_model.json"))
    pathways = list_or_empty(model.get("pathways"))
    if not isinstance(model.get("pathways"), list):
        findings.append(Finding("error", "pathways_not_list", "pathway_model.json pathways must be a list", path="pathway_model.json"))
        pathways = []

    pathway_ids: set[str] = set()
    step_index: dict[tuple[str, str], dict[str, Any]] = {}
    accepted_step_by_node: dict[str, tuple[str, str]] = {}
    records_by_node = group_evidence_records_by_node(evidence)
    known_nodes = set(node_json_by_id)
    for p_index, pathway in enumerate(pathways):
        if not isinstance(pathway, dict):
            findings.append(Finding("error", "pathway_not_object", f"pathways[{p_index}] is not an object", path="pathway_model.json"))
            continue
        pathway_id = clean_string(pathway.get("pathway_id"))
        if not pathway_id:
            findings.append(Finding("error", "pathway_missing_id", f"pathways[{p_index}] missing pathway_id", path="pathway_model.json"))
            continue
        if pathway_id in pathway_ids:
            findings.append(Finding("error", "duplicate_pathway_id", f"duplicate pathway_id: {pathway_id}", path="pathway_model.json"))
        pathway_ids.add(pathway_id)
        status = clean_string(pathway.get("status")) or "hypothesis"
        if status not in PATHWAY_STATUSES:
            findings.append(Finding("error", "pathway_status_invalid", f"invalid pathway status: {status}", path="pathway_model.json"))
        steps = list_or_empty(pathway.get("steps"))
        if not isinstance(pathway.get("steps"), list):
            findings.append(Finding("error", "pathway_steps_not_list", f"pathway {pathway_id} steps must be a list", path="pathway_model.json"))
            steps = []
        step_ids: set[str] = set()
        accepted_count = 0
        for s_index, step in enumerate(steps):
            if not isinstance(step, dict):
                findings.append(Finding("error", "pathway_step_not_object", f"{pathway_id}.steps[{s_index}] is not an object", path="pathway_model.json"))
                continue
            step_id = clean_string(step.get("step_id"))
            if not step_id:
                findings.append(Finding("error", "pathway_step_missing_id", f"{pathway_id}.steps[{s_index}] missing step_id", path="pathway_model.json"))
                continue
            key = (pathway_id, step_id)
            if step_id in step_ids:
                findings.append(Finding("error", "duplicate_pathway_step_id", f"duplicate step_id in {pathway_id}: {step_id}", path="pathway_model.json"))
            step_ids.add(step_id)
            step_index[key] = step
            step_status = clean_string(step.get("status")) or "missing"
            if step_status not in STEP_STATUSES:
                findings.append(Finding("error", "pathway_step_status_invalid", f"invalid step status: {step_status}", path="pathway_model.json"))
            accepted_node = clean_string(step.get("accepted_ts_node"))
            if step_status == "accepted_ts":
                accepted_count += 1
                if not accepted_node:
                    findings.append(Finding("error", "pathway_step_missing_accepted_node", "accepted pathway step is missing accepted_ts_node", path="pathway_model.json"))
            if accepted_node:
                node = node_json_by_id.get(accepted_node)
                if accepted_node not in known_nodes or not node:
                    findings.append(Finding("error", "pathway_step_missing_node", "pathway step accepted_ts_node is missing", path="pathway_model.json", node_id=accepted_node))
                elif clean_string(node.get("claim_status")) != "accepted_ts":
                    findings.append(Finding("error", "pathway_step_node_not_accepted_ts", "pathway step accepted_ts_node is not claim_status=accepted_ts", path="pathway_model.json", node_id=accepted_node))
                else:
                    previous_step = accepted_step_by_node.get(accepted_node)
                    if previous_step and previous_step != (pathway_id, step_id):
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_duplicate_accepted_node",
                                "one accepted_ts node is bound to multiple pathway steps",
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
                    accepted_step_by_node[accepted_node] = (pathway_id, step_id)
                    node_pathway_id = clean_string(node.get("pathway_id"))
                    node_step_id = clean_string(node.get("elementary_step_id"))
                    if node_pathway_id != pathway_id or node_step_id != step_id:
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_node_binding_conflict",
                                "pathway step accepted_ts_node does not declare the same pathway_id/elementary_step_id",
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
                    missing = accepted_ts_missing_evidence_gates(source, records_by_node.get(accepted_node, []))
                    if missing:
                        findings.append(
                            Finding(
                                "error",
                                "pathway_step_accepted_ts_missing_evidence_gates",
                                "pathway step accepted_ts_node lacks accepted_ts evidence gates: " + ", ".join(missing),
                                path="pathway_model.json",
                                node_id=accepted_node,
                            )
                        )
            status_node = clean_string(step.get("status_node"))
            if status_node and status_node not in known_nodes:
                findings.append(
                    Finding(
                        "error",
                        "pathway_step_status_node_missing",
                        "pathway step status_node is missing",
                        path="pathway_model.json",
                        node_id=status_node,
                    )
                )
        if steps:
            derived_status = derive_pathway_status([step for step in steps if isinstance(step, dict)])
            if status != derived_status:
                findings.append(
                    Finding(
                        "warning",
                        "pathway_status_not_derived",
                        f"pathway {pathway_id} status is {status}, expected derived status {derived_status}",
                        path="pathway_model.json",
                    )
                )

    active_pathway = clean_string(model.get("active_pathway"))
    if active_pathway and active_pathway not in pathway_ids:
        findings.append(Finding("error", "active_pathway_missing", "active_pathway does not reference an existing pathway", path="pathway_model.json"))

    for node_id, (pathway_id, step_id) in node_step_refs.items():
        node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
        if not pathway_id or not step_id:
            findings.append(Finding("error", "node_pathway_step_pair_incomplete", "pathway_id and elementary_step_id must be provided together", path=node_path, node_id=node_id))
            continue
        step = step_index.get((pathway_id, step_id))
        if not step:
            findings.append(Finding("error", "node_pathway_step_missing", "node references missing pathway step", path=node_path, node_id=node_id))
            continue
        node = node_json_by_id.get(node_id) or {}
        if clean_string(node.get("claim_status")) == "accepted_ts" and clean_string(step.get("accepted_ts_node")) != node_id:
            findings.append(
                Finding(
                    "error",
                    "accepted_node_not_bound_to_pathway_step",
                    "accepted_ts node declares a pathway step but pathway_model does not bind that step to this node",
                    path=node_path,
                    node_id=node_id,
                )
            )


def validate_normalized_nodes(graph: dict[str, Any], findings: list[Finding]) -> None:
    """Validate normalized node state combinations and claim-level invariants."""

    for node in list_or_empty(graph.get("nodes")):
        if not isinstance(node, dict):
            continue
        node_id = clean_string(node.get("id"))
        lifecycle = clean_string(node.get("lifecycle_state"))
        run_state = clean_string(node.get("run_state"))
        claim = clean_string(node.get("claim_status"))
        outcome = clean_string(node.get("outcome"))
        claim_level = clean_string(node.get("claim_level"))
        outcome_code = node.get("outcome_code")
        if lifecycle not in VALID_LIFECYCLE_STATES:
            findings.append(Finding("error", "invalid_lifecycle_state", f"invalid lifecycle_state: {lifecycle}", node_id=node_id))
        if run_state not in VALID_RUN_STATES:
            findings.append(Finding("error", "invalid_run_state", f"invalid run_state: {run_state}", node_id=node_id))
        if claim not in VALID_CLAIM_STATUSES:
            findings.append(Finding("error", "invalid_claim_status", f"invalid claim_status: {claim}", node_id=node_id))
        if outcome not in VALID_OUTCOMES:
            findings.append(Finding("error", "invalid_outcome", f"invalid outcome: {outcome}", node_id=node_id))
        valid_outcomes = valid_outcomes_for_claim_status(claim)
        if valid_outcomes and outcome and outcome not in valid_outcomes:
            findings.append(
                Finding(
                    "error",
                    "claim_outcome_conflict",
                    f"outcome {outcome!r} is not valid for claim_status {claim!r}",
                    node_id=node_id,
                )
            )
        if claim_level not in VALID_CLAIM_LEVELS:
            findings.append(Finding("error", "invalid_claim_level", f"invalid claim_level: {claim_level}", node_id=node_id))
        max_level = MAXIMUM_CLAIM_LEVEL_BY_CLAIM_STATUS.get(claim)
        if max_level and CLAIM_LEVEL_RANK.get(claim_level, 99) > CLAIM_LEVEL_RANK[max_level]:
            findings.append(Finding("error", "claim_level_exceeds_claim_status", f"claim_level {claim_level} exceeds claim_status {claim}", node_id=node_id))
        if claim == "accepted_ts" and claim_level != "accepted_ts":
            findings.append(Finding("error", "accepted_claim_level_conflict", "accepted_ts requires claim_level=accepted_ts", node_id=node_id))
        if claim == "not_evaluated" and claim_level != "none":
            findings.append(Finding("error", "not_evaluated_claim_level_conflict", "not_evaluated requires claim_level=none", node_id=node_id))
        if outcome == "administrative_stop":
            if run_state != "stopped" or claim != "not_evaluated" or claim_level != "none":
                findings.append(Finding("error", "administrative_stop_state_conflict", "administrative_stop requires stopped/not_evaluated/none", node_id=node_id))
        if outcome != "none" and not outcome_code and outcome in {"chemical_failure", "numerical_failure", "wrong_mode", "wrong_endpoint", "administrative_stop", "parser_refused"}:
            findings.append(Finding("warning", "missing_outcome_code", f"outcome {outcome} should include outcome_code", node_id=node_id))
        if outcome == "chemical_failure" and claim == "not_evaluated":
            findings.append(Finding("error", "chemical_failure_not_evaluated", "chemical_failure cannot have claim_status=not_evaluated", node_id=node_id))


def validate_evidence(source: Path, evidence: dict[str, Any], node_ids: list[str], findings: list[Finding]) -> None:
    """Validate evidence registry ids, states, node references, and paths."""

    records = list_or_empty(evidence.get("records"))
    seen_ids: set[str] = set()
    known_nodes = set(node_ids)
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            findings.append(Finding("error", "evidence_record_not_object", "evidence record is not an object", path="evidence_registry.json"))
            continue
        evidence_id = clean_string(item.get("evidence_id")) or f"record[{index}]"
        if evidence_id in seen_ids:
            findings.append(Finding("error", "duplicate_evidence_id", f"duplicate evidence_id {evidence_id}", path="evidence_registry.json"))
        seen_ids.add(evidence_id)
        node_id = clean_string(item.get("node_id"))
        if node_id and node_id not in known_nodes:
            findings.append(Finding("error", "evidence_missing_node", "evidence references missing node", path="evidence_registry.json", node_id=node_id))
        state = clean_string(item.get("evidence_state"))
        if state and state not in VALID_EVIDENCE_STATES:
            findings.append(Finding("warning", "unknown_evidence_state", f"unknown evidence state: {state}", path="evidence_registry.json", node_id=node_id))
        if not state:
            findings.append(Finding("error", "missing_evidence_state", "evidence record missing evidence_state", path="evidence_registry.json", node_id=node_id))
        legacy = [key for key in ("status", "state") if key in item]
        if legacy:
            findings.append(Finding("error", "legacy_evidence_fields", f"evidence record contains legacy fields: {', '.join(legacy)}", path="evidence_registry.json", node_id=node_id))
        path_text = clean_string(item.get("path"))
        if path_text:
            if Path(path_text).is_absolute() and not bool(item.get("external_path")):
                findings.append(Finding("warning", "absolute_evidence_path", "absolute evidence path should be marked external_path or made relative", path="evidence_registry.json", node_id=node_id))
            if not Path(path_text).is_absolute():
                target = source / path_text
                if not target.exists() and not bool(item.get("external_unavailable")):
                    findings.append(Finding("warning", "missing_evidence_path", f"evidence path does not exist: {path_text}", path="evidence_registry.json", node_id=node_id))


def validate_node_finalization_artifacts(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    parent_by_node: dict[str, str],
    input_refs_by_node: dict[str, list[str]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate post-execution node closure across reflection and evidence records."""

    records_by_node = group_evidence_records_by_node(evidence)
    registry_paths_by_node = group_registry_paths_by_node(source, evidence)
    for node_id, node_json in node_json_by_id.items():
        if not node_json:
            continue
        lifecycle = clean_string(node_json.get("lifecycle_state"))
        run_state = clean_string(node_json.get("run_state"))
        claim = clean_string(node_json.get("claim_status"))
        has_post_execution_state = lifecycle == "closed" or run_state in {"completed", "error", "stopped"}
        reflection_path = source / "nodes" / node_id / "reflection.md"
        if has_post_execution_state:
            validate_reflection_is_finalized(source, node_id, reflection_path, claim, findings)
        if claim != "not_evaluated" and not records_by_node.get(node_id):
            findings.append(
                Finding(
                    "warning",
                    "claim_without_evidence",
                    "node has evaluated claim_status but no evidence_registry record",
                    path="evidence_registry.json",
                    node_id=node_id,
                )
            )
        if claim == "accepted_ts":
            missing = accepted_ts_missing_evidence_gates(source, records_by_node.get(node_id, []))
            if missing:
                findings.append(
                    Finding(
                        "error",
                        "accepted_ts_missing_evidence_gates",
                        "accepted_ts requires supporting TS/Freq and connectivity evidence; "
                        f"missing gates: {', '.join(missing)}",
                        path="evidence_registry.json",
                        node_id=node_id,
                    )
                )
        if claim == "candidate_found" and not candidate_has_endpoint_gate(
            node_id=node_id,
            node_json_by_id=node_json_by_id,
            parent_by_node=parent_by_node,
            input_refs_by_node=input_refs_by_node,
        ):
            pathway_id = clean_string(node_json.get("pathway_id"))
            step_id = clean_string(node_json.get("elementary_step_id"))
            code = "pathway_candidate_without_step_endpoint_gate" if pathway_id or step_id else "candidate_without_endpoint_gate"
            suffix = " in the same pathway step" if pathway_id or step_id else ""
            findings.append(
                Finding(
                    "error",
                    code,
                    "candidate_found requires an upstream or dependency node with "
                    f"claim_status=endpoint_minima_ready{suffix}",
                    path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                    node_id=node_id,
                )
            )
        validate_node_evidence_registry_coverage(
            source=source,
            node_id=node_id,
            node_json=node_json,
            registry_paths=registry_paths_by_node.get(node_id, set()),
            findings=findings,
        )


def candidate_has_endpoint_gate(
    *,
    node_id: str,
    node_json_by_id: dict[str, dict[str, Any]],
    parent_by_node: dict[str, str],
    input_refs_by_node: dict[str, list[str]],
) -> bool:
    """Return true when a candidate has an upstream endpoint-minima claim."""

    target = node_json_by_id.get(node_id) or {}
    target_pathway_id = clean_string(target.get("pathway_id"))
    target_step_id = clean_string(target.get("elementary_step_id"))
    for upstream_id in iter_upstream_nodes(node_id, parent_by_node, input_refs_by_node):
        upstream = node_json_by_id.get(upstream_id) or {}
        if clean_string(upstream.get("claim_status")) == "endpoint_minima_ready":
            if target_pathway_id or target_step_id:
                if (
                    clean_string(upstream.get("pathway_id")) == target_pathway_id
                    and clean_string(upstream.get("elementary_step_id")) == target_step_id
                ):
                    return True
                continue
            return True
    return False


def validate_mechanism_model(source: Path, mechanism: dict[str, Any], findings: list[Finding]) -> None:
    """Validate structured mechanism-analysis buckets when mechanism_model.json exists."""

    if not mechanism:
        return
    analysis = mechanism.get("mechanism_analysis")
    if analysis is None:
        findings.append(
            Finding(
                "warning",
                "mechanism_analysis_missing",
                "mechanism_model.json should include structured mechanism_analysis buckets",
                path="mechanism_model.json",
            )
        )
        return
    if not isinstance(analysis, dict):
        findings.append(
            Finding(
                "error",
                "mechanism_analysis_not_object",
                "mechanism_analysis must be an object keyed by analysis layer",
                path="mechanism_model.json",
            )
        )
        return
    for layer in MECHANISM_ANALYSIS_LAYERS:
        records = analysis.get(layer)
        if records is None:
            findings.append(
                Finding(
                    "warning",
                    "mechanism_analysis_layer_missing",
                    f"mechanism_analysis is missing layer: {layer}",
                    path="mechanism_model.json",
                )
            )
            continue
        if not isinstance(records, list):
            findings.append(
                Finding(
                    "error",
                    "mechanism_analysis_layer_not_list",
                    f"mechanism_analysis.{layer} must be a list",
                    path="mechanism_model.json",
                )
            )
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_record_not_object",
                        f"mechanism_analysis.{layer}[{index}] is not an object",
                        path="mechanism_model.json",
                    )
                )
                continue
            status = clean_string(record.get("status"))
            summary = clean_string(record.get("summary"))
            source_text = clean_string(record.get("source"))
            details = record.get("details") if isinstance(record.get("details"), dict) else {}
            details_source = clean_string(details.get("source"))
            evidence_refs = [clean_string(item) for item in list_or_empty(record.get("evidence_refs")) if clean_string(item)]
            if status not in MECHANISM_ANALYSIS_STATUSES:
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_status_invalid",
                        f"invalid mechanism_analysis status: {status}",
                        path="mechanism_model.json",
                    )
                )
            if not summary:
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_summary_missing",
                        f"mechanism_analysis.{layer}[{index}] is missing summary",
                        path="mechanism_model.json",
                    )
                )
            if not evidence_refs and not source_text and not details_source:
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_source_missing",
                        f"mechanism_analysis.{layer}[{index}] has no evidence_refs or source",
                        path="mechanism_model.json",
                    )
                )


def iter_upstream_nodes(
    node_id: str,
    parent_by_node: dict[str, str],
    input_refs_by_node: dict[str, list[str]],
) -> list[str]:
    """Return transitive parent and dependency nodes for one branch node."""

    out: list[str] = []
    seen: set[str] = {node_id}

    def visit(current: str) -> None:
        for upstream in [parent_by_node.get(current, ""), *input_refs_by_node.get(current, [])]:
            upstream = clean_string(upstream)
            if not upstream or upstream in seen:
                continue
            seen.add(upstream)
            out.append(upstream)
            visit(upstream)

    visit(node_id)
    return out


def validate_reflection_is_finalized(
    source: Path,
    node_id: str,
    reflection_path: Path,
    claim_status: str,
    findings: list[Finding],
) -> None:
    """Warn when reflection.md still looks like the pre-execution template."""

    relative_path = relative_path_or_absolute(source, reflection_path)
    if not reflection_path.exists():
        findings.append(
            Finding(
                "warning",
                "missing_reflection",
                "closed or completed node is missing reflection.md",
                path=relative_path,
                node_id=node_id,
            )
        )
        return
    text = reflection_path.read_text(encoding="utf-8", errors="replace")
    lower_text = text.lower()
    template_hits = [line.strip() for line in text.splitlines() if line.strip() in REFLECTION_TEMPLATE_MARKERS]
    if template_hits:
        findings.append(
            Finding(
                "warning",
                "template_reflection_closed_node",
                "closed or completed node still contains template reflection text",
                path=relative_path,
                node_id=node_id,
            )
        )
    if claim_status != "not_evaluated":
        required_sections = ("Computational Outcome", "Mechanistic Implication", "Next Branch")
        missing_sections = [section for section in required_sections if f"## {section}".lower() not in lower_text]
        if missing_sections:
            findings.append(
                Finding(
                    "warning",
                    "reflection_missing_required_sections",
                    f"finalized evaluated node reflection is missing sections: {', '.join(missing_sections)}",
                    path=relative_path,
                    node_id=node_id,
                )
            )
        if reflection_has_empty_template_bullets(text):
            findings.append(
                Finding(
                    "warning",
                    "template_reflection_closed_node",
                    "closed or completed node still contains empty template bullets",
                    path=relative_path,
                    node_id=node_id,
                )
            )
    if claim_status == "accepted_ts" and ("not accepted" in lower_text or "not yet proven" in lower_text):
        findings.append(
            Finding(
                "warning",
                "reflection_claim_conflict",
                "node is accepted_ts but reflection text says the claim is not accepted or not proven",
                path=relative_path,
                node_id=node_id,
            )
        )
    if claim_status == "not_evaluated" and "accepted ts" in lower_text:
        findings.append(
            Finding(
                "warning",
                "reflection_claim_conflict",
                "node is not_evaluated but reflection text appears to claim an accepted TS",
                path=relative_path,
                node_id=node_id,
            )
        )


def reflection_has_empty_template_bullets(text: str) -> bool:
    """Return true when reflection sections still contain only dash placeholders."""

    lines = [line.rstrip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        body: list[str] = []
        for next_line in lines[index + 1 :]:
            if next_line.startswith("## "):
                break
            stripped = next_line.strip()
            if stripped:
                body.append(stripped)
        if body == ["-"] or body == ["- Validated facts:", "- Refuted hypotheses:", "- Open questions:"]:
            return True
    return False


def validate_node_evidence_registry_coverage(
    *,
    source: Path,
    node_id: str,
    node_json: dict[str, Any],
    registry_paths: set[str],
    findings: list[Finding],
) -> None:
    """Warn when post-execution node evidence paths are absent from the registry."""

    node_evidence = node_json.get("evidence") if isinstance(node_json.get("evidence"), dict) else {}
    for key, value in node_evidence.items():
        if key in PRE_EXECUTION_EVIDENCE_KEYS or not isinstance(value, str):
            continue
        evidence_path = clean_string(value)
        if not evidence_path:
            continue
        if not path_should_have_registry_record(source, evidence_path):
            continue
        normalized = normalize_workspace_path(source, evidence_path)
        if normalized not in registry_paths:
            findings.append(
                Finding(
                    "warning",
                    "node_evidence_missing_registry_record",
                    f"node evidence path has no evidence_registry record: {evidence_path}",
                    path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                    node_id=node_id,
                )
            )


def path_should_have_registry_record(source: Path, raw_path: str) -> bool:
    """Return true for evidence-like files that should be registered."""

    path = Path(raw_path)
    target = path if path.is_absolute() else source / path
    if target.exists() and target.is_dir():
        return False
    return path.suffix.lower() in REGISTRY_REQUIRED_SUFFIXES


def group_evidence_records_by_node(evidence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return evidence registry records keyed by node id."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in list_or_empty(evidence.get("records")):
        if not isinstance(item, dict):
            continue
        node_id = clean_string(item.get("node_id"))
        if node_id:
            grouped.setdefault(node_id, []).append(item)
    return grouped


def group_registry_paths_by_node(source: Path, evidence: dict[str, Any]) -> dict[str, set[str]]:
    """Return normalized registry evidence paths keyed by node id."""

    grouped: dict[str, set[str]] = {}
    for item in list_or_empty(evidence.get("records")):
        if not isinstance(item, dict):
            continue
        node_id = clean_string(item.get("node_id"))
        path_text = clean_string(item.get("path"))
        if node_id and path_text:
            grouped.setdefault(node_id, set()).add(normalize_workspace_path(source, path_text))
    return grouped


def normalize_workspace_path(source: Path, raw_path: str) -> str:
    """Normalize an absolute or workspace-relative path for path set comparison."""

    path = Path(raw_path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(source.resolve()).as_posix()
        except ValueError:
            return str(path)
    return path.as_posix()


def validate_tree_events(
    tree: dict[str, Any],
    node_ids: list[str],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate canonical timeline and backtrack events in tree.json."""

    if "branch_decisions" in tree:
        findings.append(Finding("error", "legacy_branch_decisions", "tree.json contains legacy branch_decisions; use events[]", path="tree.json"))
    if "backtrack_edges" in tree:
        findings.append(Finding("error", "legacy_backtrack_edges", "tree.json contains legacy backtrack_edges; use backtrack_events[]", path="tree.json"))
    known_nodes = set(node_ids)
    evidence_ids = {clean_string(item.get("evidence_id")) for item in list_or_empty(evidence.get("records")) if isinstance(item, dict)}
    seen_event_ids: set[str] = set()
    for index, event in enumerate(list_or_empty(tree.get("events"))):
        if not isinstance(event, dict):
            findings.append(Finding("error", "event_not_object", f"events[{index}] is not an object", path="tree.json"))
            continue
        event_id = clean_string(event.get("event_id"))
        node_id = clean_string(event.get("node_id"))
        if not event_id:
            findings.append(Finding("error", "event_missing_id", "event missing event_id", path="tree.json", node_id=node_id))
        elif event_id in seen_event_ids:
            findings.append(Finding("error", "duplicate_event_id", f"duplicate event_id: {event_id}", path="tree.json", node_id=node_id))
        else:
            seen_event_ids.add(event_id)
        if node_id and node_id not in known_nodes:
            findings.append(Finding("error", "event_missing_node", "event references missing node", path="tree.json", node_id=node_id))
        if "evidence" in event:
            findings.append(Finding("error", "legacy_event_evidence", "event uses legacy evidence; use evidence_refs", path="tree.json", node_id=node_id))
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "event_missing_evidence_ref", f"event references missing evidence_id {ref_id}", path="tree.json", node_id=node_id))
    seen_backtrack_ids: set[str] = set()
    active_backtrack_ids: list[str] = []
    for index, event in enumerate(list_or_empty(tree.get("backtrack_events"))):
        if not isinstance(event, dict):
            findings.append(Finding("error", "backtrack_event_not_object", f"backtrack_events[{index}] is not an object", path="tree.json"))
            continue
        event_id = clean_string(event.get("id"))
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        if not event_id:
            findings.append(Finding("error", "backtrack_missing_id", "backtrack event missing id", path="tree.json", node_id=from_node))
        elif event_id in seen_backtrack_ids:
            findings.append(Finding("error", "duplicate_backtrack_event_id", f"duplicate backtrack event id: {event_id}", path="tree.json", node_id=from_node))
        else:
            seen_backtrack_ids.add(event_id)
        if from_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_from_node", "backtrack from_node is missing", path="tree.json", node_id=from_node))
        if to_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_to_node", "backtrack to_node is missing", path="tree.json", node_id=to_node))
        state = clean_string(event.get("event_state")) or "active"
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", path="tree.json", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id or f"backtrack_events[{index}]")
        if "evidence" in event:
            findings.append(Finding("error", "legacy_backtrack_evidence", "backtrack event uses legacy evidence; use evidence_refs", path="tree.json", node_id=from_node))
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "backtrack_missing_evidence_ref", f"backtrack references missing evidence_id {ref_id}", path="tree.json", node_id=from_node))
    if len(active_backtrack_ids) > 1:
        findings.append(
            Finding(
                "error",
                "multiple_active_backtracks",
                f"tree.json has multiple active backtrack events: {', '.join(active_backtrack_ids)}",
                path="tree.json",
            )
        )


def validate_events(graph: dict[str, Any], node_ids: list[str], findings: list[Finding]) -> None:
    """Validate normalized graph events after normalizer processing."""

    known_nodes = set(node_ids)
    evidence_ids = {clean_string(item.get("evidence_id")) for item in list_or_empty(graph.get("evidence", {}).get("records")) if isinstance(item, dict)}
    for event in list_or_empty(graph.get("events")):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("event_id"))
        node_id = clean_string(event.get("node_id"))
        if not event_id:
            findings.append(Finding("error", "event_missing_id", "event missing event_id"))
        if node_id and node_id not in known_nodes:
            findings.append(Finding("error", "event_missing_node", "event references missing node", node_id=node_id))
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "event_missing_evidence_ref", f"event references missing evidence_id {ref_id}", node_id=node_id))
    active_backtrack_ids: list[str] = []
    for index, event in enumerate(list_or_empty(graph.get("backtrack_events"))):
        if not isinstance(event, dict):
            continue
        event_id = clean_string(event.get("id")) or f"backtrack_events[{index}]"
        from_node = clean_string(event.get("from_node"))
        to_node = clean_string(event.get("to_node"))
        if from_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_from_node", "backtrack from_node is missing", node_id=from_node))
        if to_node not in known_nodes:
            findings.append(Finding("error", "backtrack_missing_to_node", "backtrack to_node is missing", node_id=to_node))
        state = clean_string(event.get("event_state"))
        if state not in VALID_BACKTRACK_EVENT_STATES:
            findings.append(Finding("warning", "invalid_backtrack_event_state", f"invalid backtrack event_state: {state}", node_id=from_node))
        elif state == "active":
            active_backtrack_ids.append(event_id)
        for ref in list_or_empty(event.get("evidence_refs")):
            ref_id = clean_string(ref)
            if ref_id and ref_id not in evidence_ids:
                findings.append(Finding("warning", "backtrack_missing_evidence_ref", f"backtrack references missing evidence_id {ref_id}", node_id=from_node))
    if len(active_backtrack_ids) > 1:
        findings.append(
            Finding(
                "error",
                "multiple_active_backtracks",
                f"normalized graph has multiple active backtrack events: {', '.join(active_backtrack_ids)}",
            )
        )


def validate_paths_are_portable(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Warn when workspace metadata stores non-portable absolute paths."""

    for node_id, node_json in node_json_by_id.items():
        for key_path, value in walk_values(node_json):
            if isinstance(value, str) and value.startswith("/") and not value.startswith(str(source)):
                if any(part in key_path for part in ("changed_variables", "evidence", "display")):
                    findings.append(
                        Finding(
                            "warning",
                            "absolute_nested_path",
                            f"absolute path in node field {'.'.join(key_path)} may not be portable",
                            path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                            node_id=node_id,
                        )
                    )
    for index, item in enumerate(list_or_empty(evidence.get("records"))):
        if isinstance(item, dict):
            path_text = clean_string(item.get("path"))
            if path_text.startswith("/") and not bool(item.get("external_path")):
                findings.append(Finding("warning", "absolute_registry_path", f"absolute registry path at records[{index}] is not marked external_path", path="evidence_registry.json", node_id=clean_string(item.get("node_id"))))


def validate_engine_artifact_policy(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    """Detect engine artifacts outside node-scoped run/output directories."""

    validate_workspace_root_has_no_engine_artifacts(source, findings)
    for node_id, node_json in node_json_by_id.items():
        if not node_json:
            continue
        validate_node_artifact_policy(source, node_id, node_json, findings)
        validate_gaussian_checkpoint_paths(source, node_id, findings)


def validate_workspace_root_has_no_engine_artifacts(source: Path, findings: list[Finding]) -> None:
    """Warn when known engine output files are written at workspace root."""

    if not source.exists():
        return
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        lower_name = name.lower()
        if (
            lower_name in ENGINE_ROOT_ARTIFACT_NAMES
            or path.suffix.lower() in ENGINE_ROOT_ARTIFACT_SUFFIXES
            or lower_name.startswith("qbics")
            or lower_name.startswith("xtb_")
        ):
            findings.append(
                Finding(
                    "warning",
                    "engine_artifact_at_workspace_root",
                    "engine artifact is at workspace root; run Gaussian/xTB/QBICS from nodes/<node_id>/outputs or scratch",
                    path=relative_path_or_absolute(source, path),
                )
            )


def validate_node_artifact_policy(
    source: Path,
    node_id: str,
    node_json: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate optional node artifact policy written by new decision cards."""

    policy = node_json.get("artifact_policy")
    if policy is None:
        return
    node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
    if not isinstance(policy, dict):
        findings.append(Finding("warning", "artifact_policy_not_object", "artifact_policy must be an object", path=node_path, node_id=node_id))
        return
    expected = {
        "input_dir": f"nodes/{node_id}/inputs",
        "output_dir": f"nodes/{node_id}/outputs",
        "run_cwd": f"nodes/{node_id}/outputs",
        "scratch_dir": f"nodes/{node_id}/scratch",
    }
    for key, expected_value in expected.items():
        value = clean_string(policy.get(key))
        if not value:
            findings.append(Finding("warning", "artifact_policy_missing_field", f"artifact_policy missing {key}", path=node_path, node_id=node_id))
            continue
        if Path(value).is_absolute() or path_escapes_workspace(value):
            findings.append(Finding("warning", "artifact_policy_nonportable_path", f"artifact_policy {key} should be workspace-relative", path=node_path, node_id=node_id))
        if value != expected_value:
            findings.append(
                Finding(
                    "warning",
                    "artifact_policy_not_node_scoped",
                    f"artifact_policy {key} should be {expected_value!r}, got {value!r}",
                    path=node_path,
                    node_id=node_id,
                )
            )


def validate_gaussian_checkpoint_paths(source: Path, node_id: str, findings: list[Finding]) -> None:
    """Warn on Gaussian checkpoint paths that contradict outputs/ as run cwd."""

    inputs_dir = source / "nodes" / node_id / "inputs"
    if not inputs_dir.exists():
        return
    for input_path in sorted(inputs_dir.iterdir()):
        if not input_path.is_file() or input_path.suffix.lower() not in GAUSSIAN_INPUT_SUFFIXES:
            continue
        for key, raw_value in iter_gaussian_checkpoint_directives(input_path):
            value = raw_value.strip()
            if not value:
                continue
            if Path(value).is_absolute():
                findings.append(
                    Finding(
                        "warning",
                        "gaussian_checkpoint_absolute_path",
                        f"{key} uses an absolute checkpoint path; prefer a path relative to the node outputs/ run directory",
                        path=relative_path_or_absolute(source, input_path),
                        node_id=node_id,
                    )
                )
                continue
            parts = [part for part in PurePosixPath(value).parts if part not in {"", "."}]
            if key.lower() == "%chk" and any(part == ".." for part in parts):
                findings.append(
                    Finding(
                        "warning",
                        "gaussian_checkpoint_escapes_run_cwd",
                        f"{key}={value} would write the checkpoint outside nodes/{node_id}/outputs; use a bare checkpoint name for %chk",
                        path=relative_path_or_absolute(source, input_path),
                        node_id=node_id,
                    )
                )
                continue
            if parts and parts[0] in {"nodes", "inputs", "outputs"}:
                findings.append(
                    Finding(
                        "warning",
                        "gaussian_checkpoint_not_run_cwd_relative",
                        f"{key}={value} looks workspace- or node-root-relative; Gaussian should run from nodes/{node_id}/outputs, so use a bare checkpoint name or a path relative to outputs/",
                        path=relative_path_or_absolute(source, input_path),
                        node_id=node_id,
                    )
                )


def iter_gaussian_checkpoint_directives(input_path: Path) -> list[tuple[str, str]]:
    """Return %chk/%oldchk directives from one Gaussian input."""

    directives: list[tuple[str, str]] = []
    for line in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*(%oldchk|%chk)\s*=\s*(.+?)\s*$", line, re.IGNORECASE)
        if match:
            directives.append((match.group(1), match.group(2)))
    return directives


def path_escapes_workspace(raw_path: str) -> bool:
    """Return true when a workspace-relative path starts with '..'."""

    return any(part == ".." for part in PurePosixPath(raw_path).parts)


def require_file(path: Path, findings: list[Finding]) -> None:
    """Append a missing-file finding when a required workspace file is absent."""

    if not path.exists():
        findings.append(Finding("error", "missing_required_file", f"missing required file {path.name}", path=path.name))


def read_json_optional(path: Path, findings: list[Finding]) -> dict[str, Any]:
    """Read optional JSON for validation, recording errors instead of raising."""

    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        findings.append(Finding("error", "json_read_error", f"failed to read JSON: {exc}", path=str(path)))
        return {}
    if not isinstance(payload, dict):
        findings.append(Finding("error", "json_root_not_object", "JSON root is not an object", path=str(path)))
        return {}
    return payload


def collect_node_dirs(source: Path) -> set[str]:
    """Return node ids that have directories under nodes/."""

    nodes_dir = source / "nodes"
    if not nodes_dir.exists():
        return set()
    return {child.name for child in nodes_dir.iterdir() if child.is_dir()}


def walk_values(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    """Walk nested lists and dicts to expose all values with key paths."""

    out = [(prefix, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            out.extend(walk_values(child, (*prefix, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(walk_values(child, (*prefix, str(index))))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
