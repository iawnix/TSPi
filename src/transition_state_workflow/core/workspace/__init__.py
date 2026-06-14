"""Core TS-search workspace primitives."""

from transition_state_workflow.core.workspace.branch import (
    BRANCH_WORK_DIRS,
    PreparedBranchWrite,
    ensure_branch_directories,
    next_branch_event_id,
    prepared_branch_event,
    prepared_branch_node_payload,
    prepared_branch_tree_entry,
    write_prepared_branch_state,
)
from transition_state_workflow.core.workspace.evidence import append_evidence_record, append_portable_evidence_record
from transition_state_workflow.core.workspace.io import (
    relative_artifact_path,
    write_json,
    write_markdown,
    write_text_file_if_allowed,
)
from transition_state_workflow.core.workspace.naming import utc_timestamp, workspace_slug
from transition_state_workflow.core.workspace.nodes import VALID_NODE_STATUSES, next_node_id, node_record
from transition_state_workflow.core.workspace.references import (
    BranchReferenceError,
    clean_optional_node_ref,
    normalize_branch_input_refs,
    parent_graph_would_cycle,
    validate_branch_references,
)
from transition_state_workflow.core.workspace.scaffold import (
    ensure_workspace_directories,
    ensure_tree_skeleton,
    ensure_workspace_root_has_manifest_and_tree,
    finalize_node_report_and_tree,
    initial_evidence_registry,
    initial_workspace_manifest,
    initial_workspace_tree,
    write_final_reflection,
    write_initial_workspace_files,
    write_reflection_template,
)
from transition_state_workflow.core.workspace.tree import (
    read_tree,
    update_tree_node_metadata,
    upsert_tree_node,
    write_tree,
)

__all__ = [
    "BRANCH_WORK_DIRS",
    "BranchReferenceError",
    "PreparedBranchWrite",
    "VALID_NODE_STATUSES",
    "append_evidence_record",
    "append_portable_evidence_record",
    "clean_optional_node_ref",
    "ensure_branch_directories",
    "ensure_workspace_directories",
    "ensure_tree_skeleton",
    "ensure_workspace_root_has_manifest_and_tree",
    "finalize_node_report_and_tree",
    "initial_evidence_registry",
    "initial_workspace_manifest",
    "initial_workspace_tree",
    "next_branch_event_id",
    "next_node_id",
    "node_record",
    "normalize_branch_input_refs",
    "parent_graph_would_cycle",
    "prepared_branch_event",
    "prepared_branch_node_payload",
    "prepared_branch_tree_entry",
    "read_tree",
    "relative_artifact_path",
    "update_tree_node_metadata",
    "upsert_tree_node",
    "utc_timestamp",
    "validate_branch_references",
    "workspace_slug",
    "write_final_reflection",
    "write_initial_workspace_files",
    "write_json",
    "write_markdown",
    "write_prepared_branch_state",
    "write_reflection_template",
    "write_text_file_if_allowed",
    "write_tree",
]
