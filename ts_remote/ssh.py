"""OpenSSH command builder."""

from __future__ import annotations

from .base import RemoteReceipt, Runner


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


class SshRunner(Runner):
    def submit(self, *, node_id: str, host: str, remote_dir: str, command: list[str]) -> RemoteReceipt:
        return receipt_for_ssh(node_id, host, remote_dir, command)
