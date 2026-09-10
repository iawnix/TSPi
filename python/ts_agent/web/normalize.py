"""Compatibility imports for the TSPi projection provider.

New code should import from :mod:`ts_agent.projection`. This module remains
for clients that used the pre-extraction Web import path.
"""

from ts_agent.projection.normalize import (
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

__all__ = [
    "claim_payload",
    "graph_payload",
    "graph_payload_from_view",
    "list_node_files",
    "node_payload",
    "normalize_workspace",
    "research_files_payload",
    "workspace_snapshot",
    "workspace_summary",
]
