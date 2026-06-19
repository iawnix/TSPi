"""Remote lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RemoteReceipt:
    node_id: str
    host: str
    remote_dir: str
    command: list[str]
    receipt_path: str
    scheduler_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
