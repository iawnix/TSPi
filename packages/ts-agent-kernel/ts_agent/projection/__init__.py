"""TSPi-owned, read-only projection provider for optional clients."""

from .file_preview import MAX_TEXT_BYTES, preview_capability, read_text_preview
from .normalize import (
    claim_payload,
    graph_payload,
    graph_payload_from_view,
    list_node_files,
    node_payload,
    normalize_workspace,
    research_files_payload,
    workspace_snapshot,
    workspace_summary,
)
from .research_map import project_research_map

__all__ = [
    "MAX_TEXT_BYTES",
    "claim_payload",
    "graph_payload",
    "graph_payload_from_view",
    "list_node_files",
    "node_payload",
    "normalize_workspace",
    "preview_capability",
    "project_research_map",
    "read_text_preview",
    "research_files_payload",
    "workspace_snapshot",
    "workspace_summary",
]
