"""ChemGate workspace validator facade.

The implementation is split by validation responsibility, while this package
keeps the historical ``transition_state_workflow.gate.validate`` import
surface stable for scripts and compatibility shims.
"""

from __future__ import annotations

from .artifacts import (
    iter_gaussian_checkpoint_directives,
    path_escapes_workspace,
    validate_engine_artifact_policy,
    validate_gaussian_checkpoint_paths,
    validate_node_artifact_policy,
    validate_paths_are_portable,
    validate_workspace_root_has_no_engine_artifacts,
)
from .cli import ValidateWorkspaceCLI, main
from .contracts import (
    ENGINE_ROOT_ARTIFACT_NAMES,
    ENGINE_ROOT_ARTIFACT_SUFFIXES,
    GAUSSIAN_INPUT_SUFFIXES,
    PRE_EXECUTION_EVIDENCE_KEYS,
    REFLECTION_TEMPLATE_MARKERS,
    REGISTRY_REQUIRED_SUFFIXES,
    Finding,
)
from .evidence import (
    group_evidence_records_by_node,
    group_registry_paths_by_node,
    normalize_workspace_path,
    path_should_have_registry_record,
    validate_evidence,
    validate_node_evidence_registry_coverage,
)
from .events import validate_events, validate_tree_events
from .finalization import (
    candidate_has_endpoint_gate,
    iter_upstream_nodes,
    reflection_has_empty_template_bullets,
    validate_node_finalization_artifacts,
    validate_reflection_is_finalized,
)
from .io import collect_node_dirs, read_json_optional, require_file, walk_values
from .mechanism import validate_mechanism_model
from .nodes import validate_nodes_contract, validate_normalized_nodes
from .pathway import validate_pathway_model
from .tree import (
    validate_indexes,
    validate_manifest_accepted_ts,
    validate_parent_graph,
    validate_tree_top_level_contract,
)
from .workspace import validate_ts_workspace_contract

__all__ = [
    "Finding",
    "REFLECTION_TEMPLATE_MARKERS",
    "PRE_EXECUTION_EVIDENCE_KEYS",
    "REGISTRY_REQUIRED_SUFFIXES",
    "ENGINE_ROOT_ARTIFACT_NAMES",
    "ENGINE_ROOT_ARTIFACT_SUFFIXES",
    "GAUSSIAN_INPUT_SUFFIXES",
    "ValidateWorkspaceCLI",
    "main",
    "validate_ts_workspace_contract",
    "validate_tree_top_level_contract",
    "validate_parent_graph",
    "validate_nodes_contract",
    "validate_indexes",
    "validate_manifest_accepted_ts",
    "validate_pathway_model",
    "validate_normalized_nodes",
    "validate_evidence",
    "validate_node_finalization_artifacts",
    "candidate_has_endpoint_gate",
    "validate_mechanism_model",
    "iter_upstream_nodes",
    "validate_reflection_is_finalized",
    "reflection_has_empty_template_bullets",
    "validate_node_evidence_registry_coverage",
    "path_should_have_registry_record",
    "group_evidence_records_by_node",
    "group_registry_paths_by_node",
    "normalize_workspace_path",
    "validate_tree_events",
    "validate_events",
    "validate_paths_are_portable",
    "validate_engine_artifact_policy",
    "validate_workspace_root_has_no_engine_artifacts",
    "validate_node_artifact_policy",
    "validate_gaussian_checkpoint_paths",
    "iter_gaussian_checkpoint_directives",
    "path_escapes_workspace",
    "require_file",
    "read_json_optional",
    "collect_node_dirs",
    "walk_values",
]
