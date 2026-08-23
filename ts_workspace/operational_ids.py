"""Allocate workspace-wide, human-readable IDs for operational records."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from .refs import ACTIVITY_ID, CALCULATION_ID, SUBAGENT_RUN_ID


STATE_SCHEMA = "ts-operational-id-state/1"
STATE_FILE = ".ts-operational-ids.json"
LOCK_FILE = ".ts-operational-ids.lock"
KINDS = frozenset({"calc", "sub", "op"})
_ID_PATTERNS = {
    "calc": CALCULATION_ID,
    "sub": SUBAGENT_RUN_ID,
    "op": ACTIVITY_ID,
}
_SCAN_PATTERNS = {
    "calc": ("acts/*/attempts/calc_*",),
    "sub": (
        "acts/*/attempts/*/runs/sub_*",
        "reviews/*/runs/sub_*",
    ),
    "op": (
        "acts/*/activities/op_*",
        "operations/activities/op_*",
    ),
}


def allocate_operational_id(root: str | Path, kind: str) -> dict[str, Any]:
    """Reserve the next global ordinal for one operational record kind."""

    workspace = _workspace_root(root)
    if kind not in KINDS:
        raise ValueError(f"unsupported operational ID kind: {kind}")
    lock_path = workspace / LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("operational ID lock must be a regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        state = _load_state(workspace)
        high_water = {
            candidate: max(
                int(state["high_water"].get(candidate, 0)),
                _observed_high_water(workspace, candidate),
            )
            for candidate in sorted(KINDS)
        }
        ordinal = high_water[kind] + 1
        high_water[kind] = ordinal
        _write_state(workspace / STATE_FILE, {
            "schema_version": STATE_SCHEMA,
            "high_water": high_water,
        })
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    return {
        "schema_version": "ts-operational-id-allocation/1",
        "kind": kind,
        "ordinal": ordinal,
        "identifier": f"{kind}_{ordinal}",
    }


def _workspace_root(root: str | Path) -> Path:
    candidate = Path(root).expanduser()
    if candidate.is_symlink():
        raise ValueError("workspace root must not be a symbolic link")
    workspace = candidate.resolve(strict=True)
    if not workspace.is_dir() or not (workspace / "workspace.json").is_file():
        raise ValueError("operational IDs require an initialized TS workspace")
    return workspace


def _load_state(workspace: Path) -> dict[str, Any]:
    path = workspace / STATE_FILE
    if not path.exists():
        return {"schema_version": STATE_SCHEMA, "high_water": {}}
    if path.is_symlink() or not path.is_file():
        raise ValueError("operational ID state must be a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"schema_version", "high_water"}:
        raise ValueError("operational ID state has an invalid structure")
    if value.get("schema_version") != STATE_SCHEMA or not isinstance(value.get("high_water"), dict):
        raise ValueError("operational ID state has an invalid schema")
    unknown = set(value["high_water"]) - KINDS
    if unknown:
        raise ValueError("operational ID state contains unknown kinds: " + ", ".join(sorted(unknown)))
    for kind, ordinal in value["high_water"].items():
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError(f"operational ID high-water mark is invalid: {kind}")
    return value


def _observed_high_water(workspace: Path, kind: str) -> int:
    pattern = _ID_PATTERNS[kind]
    ordinals: list[int] = []
    for glob_pattern in _SCAN_PATTERNS[kind]:
        for path in workspace.glob(glob_pattern):
            if path.is_symlink() or not path.is_dir():
                continue
            if pattern.fullmatch(path.name):
                ordinals.append(int(path.name.split("_", 1)[1]))
    return max(ordinals, default=0)


def _write_state(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
