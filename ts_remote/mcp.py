"""Placeholder contract for MCP-backed remote runners."""

from __future__ import annotations

from .base import RemoteReceipt


def mcp_receipt(node_id: str, host_label: str, remote_dir: str, command: list[str]) -> RemoteReceipt:
    return RemoteReceipt(
        node_id=node_id,
        host=host_label,
        remote_dir=remote_dir,
        command=command,
        receipt_path=f"{remote_dir.rstrip('/')}/mcp_receipt.json",
    )
