"""Workspace-level orchestration for ChemGate validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import TREE_NODE_FORBIDDEN_RUNTIME_FIELDS
from transition_state_workflow.gate.normalize import normalize_ts_workspace_to_explorer_graph
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, relative_path_or_absolute

from .artifacts import validate_engine_artifact_policy, validate_paths_are_portable
from .common import clean_string_list, validate_known_node_ref
from .contracts import Finding
from .evidence import validate_evidence
from .events import validate_backtrack_replacement_links, validate_events, validate_tree_events
from .finalization import validate_node_finalization_artifacts
from .io import collect_node_dirs, read_json_optional, require_file
from .mechanism import validate_mechanism_model
from .nodes import validate_nodes_v2, validate_normalized_nodes
from .pathway import validate_pathway_model
from .tree import (
    validate_indexes,
    validate_manifest_accepted_ts,
    validate_parent_graph,
    validate_tree_top_level_contract,
)


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
    known_node_ids = set(node_ids)
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
        validate_known_node_ref(
            parent,
            known_node_ids,
            findings,
            code="missing_parent",
            message=f"parent node does not exist: {parent}",
            path=relative_path_or_absolute(source, node_path),
            node_id=node_id,
        )
        input_refs = clean_string_list(
            list_or_empty(node_json.get("input_refs")) + list_or_empty(tree_payload.get("input_refs"))
        )
        for input_ref in sorted(set(input_refs)):
            validate_known_node_ref(
                input_ref,
                known_node_ids,
                findings,
                code="missing_input_ref",
                message=f"input reference node does not exist: {input_ref}",
                path=relative_path_or_absolute(source, node_path),
                node_id=node_id,
            )
        input_refs_by_node[node_id] = sorted(set(input_refs))

    validate_parent_graph(parent_by_node, findings)
    validate_mechanism_preflight_root(manifest, node_json_by_id, parent_by_node, findings)
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
    validate_backtrack_replacement_links(
        node_json_by_id,
        parent_by_node,
        list_or_empty(tree.get("backtrack_events")),
        findings,
    )
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


def validate_mechanism_preflight_root(
    manifest: dict[str, Any],
    node_json_by_id: dict[str, dict[str, Any]],
    parent_by_node: dict[str, str],
    findings: list[Finding],
) -> None:
    """Warn when an undeclared workspace starts compute branches without a preflight root."""

    if any(clean_string(node.get("stage")) == "mechanism_preflight" for node in node_json_by_id.values()):
        return
    if clean_string(manifest.get("mechanism_preflight_storage")) == "workspace_level":
        return
    compute_root_stages = {
        "candidate_generation",
        "gaussian_tsfreq_validation",
        "connectivity_validation",
        "irc_validation",
        "irc_connectivity_validation",
        "qbics_dmecp_candidate",
        "neb",
        "qst",
        "dimer",
    }
    root_compute_nodes = [
        node_id
        for node_id, node in sorted(node_json_by_id.items())
        if not clean_string(parent_by_node.get(node_id)) and clean_string(node.get("stage")) in compute_root_stages
    ]
    if not root_compute_nodes:
        return
    first = root_compute_nodes[0]
    findings.append(
        Finding(
            "warning",
            "mechanism_preflight_node_missing",
            (
                "workspace has root compute branch nodes but no explicit mechanism_preflight node; "
                "record mechanism_preflight_storage=workspace_level or create n000_mechanism_preflight"
            ),
            path="tree.json",
            node_id=first,
        )
    )


__all__ = ["validate_ts_workspace_contract", "validate_mechanism_preflight_root"]
