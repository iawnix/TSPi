"""Bounded content, digest, and workspace-report path helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def workspace_root(root: Path) -> Path:
    workspace = root.resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace root must be a directory")
    return workspace


def workspace_path(
    workspace: Path,
    value: Any,
    *,
    must_exist: bool,
    allow_existing: bool = False,
) -> tuple[str, Path]:
    ref = bounded_text(value, "workspace ref", 4096).replace("\\", "/")
    parts = ref.split("/")
    if not ref.startswith("reports/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("notification artifacts must use a safe reports/ workspace-relative path")
    path = workspace.joinpath(*parts)
    current = workspace
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"notification artifact path contains a symbolic link: {ref}")
        if not current.exists():
            break
    if must_exist and not path.is_file():
        raise ValueError(f"notification artifact does not exist: {ref}")
    if not must_exist and path.exists() and not allow_existing:
        raise ValueError(f"notification artifact already exists: {ref}")
    return ref, path


def bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if len(text) > maximum or "\x00" in text:
        raise ValueError(f"{label} exceeds its safe limit")
    return text


def bounded_content(value: Any, label: str, maximum: int) -> str:
    text = bounded_text(value, label, maximum)
    return text + ("" if text.endswith("\n") else "\n")


def sha256_path(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
