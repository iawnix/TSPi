"""Generic job lifecycle receipts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ts_workspace.io import write_json

from .base import RemoteReceipt


def record_receipt(receipt: RemoteReceipt, local_path: str | Path) -> None:
    write_json(Path(local_path), asdict(receipt))
