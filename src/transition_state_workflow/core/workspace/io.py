"""Generic workspace file I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    """Write JSON with stable formatting and parent-directory creation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, text: str) -> None:
    """Write markdown with parent-directory creation and one trailing newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def relative_artifact_path(root: Path, path: Path | str | None) -> str:
    """Return a workspace-relative artifact path when possible."""

    if path is None:
        return ""
    artifact = Path(str(path))
    if not artifact.is_absolute():
        return str(artifact)
    try:
        return str(artifact.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(artifact)


__all__ = ["write_json", "write_markdown", "relative_artifact_path"]
