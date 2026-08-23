"""Revision identity for canonical v5 scientific state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, sha256_json
from .state import STATE_FILES


def workspace_revision(root: str | Path) -> str:
    root_path = Path(root).expanduser().resolve()
    return workspace_revision_from_documents(
        {name: read_json(root_path / name) for name in STATE_FILES}
    )


def workspace_revision_from_documents(documents: dict[str, Any]) -> str:
    return sha256_json({name: documents[name] for name in STATE_FILES})


def report_id_for_revision(revision: str) -> str:
    return "rep_" + revision.removeprefix("sha256:")[:16]
