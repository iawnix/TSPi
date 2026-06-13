"""Path and text normalization helpers for TS workflow tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def clean_string(raw_value: Any) -> str:
    """Return a stripped string, using an empty string for null values."""

    return str(raw_value).strip() if raw_value is not None else ""


def first_nonempty_string(*candidate_values: Any) -> str:
    """Return the first nonempty normalized string from candidate values."""

    for candidate_value in candidate_values:
        text_value = clean_string(candidate_value)
        if text_value:
            return text_value
    return ""


def list_or_empty(raw_value: Any) -> list[Any]:
    """Return raw_value when it is a list, otherwise return an empty list."""

    return raw_value if isinstance(raw_value, list) else []


def relative_path_or_absolute(root_directory: Path, file_path: Path) -> str:
    """Return file_path relative to root_directory when possible."""

    try:
        return file_path.resolve().relative_to(root_directory.resolve()).as_posix()
    except ValueError:
        return str(file_path)


def is_path_relative_to(path: Path, possible_parent: Path) -> bool:
    """Return true when path is inside possible_parent after resolution."""

    try:
        path.resolve().relative_to(possible_parent.resolve())
        return True
    except ValueError:
        return False


def safe_identifier_token(raw_value: str) -> str:
    """Return a lowercase filesystem-safe token derived from raw_value."""

    token = "".join(character if character.isalnum() else "_" for character in raw_value.strip().lower())
    return "_".join(part for part in token.split("_") if part) or "item"


def slugify_workspace_id(raw_value: str) -> str:
    """Convert arbitrary workspace text into a stable route-safe id."""

    text = clean_string(raw_value).lower()
    chars = [character if character.isalnum() else "-" for character in text]
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "workspace"


def portable_record_path(root_directory: Path, raw_path: str) -> dict[str, Any]:
    """Represent a path in a workspace-portable way when possible."""

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        try:
            return {
                "path": path.resolve().relative_to(root_directory.resolve()).as_posix(),
                "external_path": False,
                "external_unavailable": False,
            }
        except ValueError:
            return {
                "path": str(path),
                "external_path": True,
                "external_unavailable": not path.exists(),
            }
    return {
        "path": path.as_posix(),
        "external_path": False,
        "external_unavailable": not (root_directory / path).exists(),
    }

