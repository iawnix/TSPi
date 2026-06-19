"""OpenSSH command builder."""

from __future__ import annotations

from .base import RemoteReceipt


def ssh_command(host: str, remote_command: list[str]) -> list[str]:
    return ["ssh", host, "--", " ".join(remote_command)]


def receipt_for_ssh(node_id: str, host: str, remote_dir: str, command: list[str]) -> RemoteReceipt:
    return RemoteReceipt(
        node_id=node_id,
        host=host,
        remote_dir=remote_dir,
        command=command,
        receipt_path=f"{remote_dir.rstrip('/')}/remote_receipt.json",
    )
