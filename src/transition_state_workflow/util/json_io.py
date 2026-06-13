"""JSON input/output helpers with consistent error messages."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json_object_required(json_file_path: Path) -> dict[str, Any]:
    """Read a required JSON object from disk.

    Args:
        json_file_path: Absolute or relative path to a JSON file.

    Returns:
        The decoded JSON object.

    Raises:
        ValueError: If the file cannot be read or does not contain an object.
    """

    try:
        with json_file_path.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except Exception as exc:
        raise ValueError(f"failed to read JSON {json_file_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {json_file_path}")
    return payload


def read_json_object_optional(json_file_path: Path) -> dict[str, Any]:
    """Read an optional JSON object, returning an empty object when absent."""

    if not json_file_path.exists():
        return {}
    return read_json_object_required(json_file_path)


def write_json_object(json_file_path: Path, payload: dict[str, Any], *, overwrite_existing: bool = True) -> bool:
    """Atomically write a JSON object with stable formatting.

    The payload is written to a temporary file in the same directory and then
    renamed over the destination, so concurrent readers (e.g. the explorer
    service) never observe a partially written file.

    Args:
        json_file_path: Destination file path.
        payload: JSON object to write.
        overwrite_existing: When false, existing files are left untouched.

    Returns:
        True when the file was written, false when skipped.
    """

    if json_file_path.exists() and not overwrite_existing:
        return False
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    directory = json_file_path.parent
    descriptor, tmp_name = tempfile.mkstemp(prefix=json_file_path.name + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, json_file_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return True

